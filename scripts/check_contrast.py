"""Contrast checker for the Torch design tokens.

Parses ``web/src/styles/theme.css``, resolves every colour token (including
``var()`` indirection) in **both** themes, converts OKLCH to sRGB and checks
each declared text/background pair against WCAG 2.2:

* normal text        -> 4.5:1
* large text and UI parts (borders, icons, focus rings) -> 3:1

Exits non-zero if any pair fails, so CI catches a token change that quietly
breaks readability.

    python scripts/check_contrast.py            # check
    python scripts/check_contrast.py --verbose  # print every pair
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

THEME_CSS = Path(__file__).resolve().parents[1] / "web" / "src" / "styles" / "theme.css"

AA_NORMAL = 4.5
AA_LARGE = 3.0


# --------------------------------------------------------------------------- #
# colour maths
# --------------------------------------------------------------------------- #
def oklch_to_srgb(lightness: float, chroma: float, hue_deg: float) -> tuple[float, float, float]:
    """OKLCH -> sRGB (0..1), clamped to gamut."""
    hue = math.radians(hue_deg)
    a = chroma * math.cos(hue)
    b = chroma * math.sin(hue)

    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3

    r_lin = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g_lin = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b_lin = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    return tuple(_gamma_encode(max(0.0, min(1.0, c))) for c in (r_lin, g_lin, b_lin))


def _gamma_encode(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _gamma_decode(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_gamma_decode(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


# --------------------------------------------------------------------------- #
# token parsing
# --------------------------------------------------------------------------- #
OKLCH = re.compile(r"oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+([\d.]+)\s*(?:/\s*([\d.]+)%?\s*)?\)", re.I)
HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.I)
VAR = re.compile(r"var\(\s*(--[\w-]+)\s*\)")
DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def parse_blocks(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(light_tokens, dark_overrides)`` as raw declaration strings."""
    light: dict[str, str] = {}
    dark: dict[str, str] = {}

    root = re.search(r":root\s*{(.*?)}", css, re.S)
    if root:
        light.update({m.group(1): m.group(2).strip() for m in DECL.finditer(root.group(1))})

    dark_block = re.search(r"\[data-theme=['\"]dark['\"]\]\s*{(.*?)}", css, re.S)
    if dark_block:
        dark.update({m.group(1): m.group(2).strip() for m in DECL.finditer(dark_block.group(1))})

    return light, dark


def resolve(token: str, tokens: dict[str, str], depth: int = 0) -> tuple[float, float, float] | None:
    """Resolve a token name (or literal) to sRGB, following ``var()`` chains."""
    if depth > 10:
        return None
    raw = tokens.get(token, token).strip()

    match = VAR.search(raw)
    if match:
        return resolve(match.group(1), tokens, depth + 1)

    match = OKLCH.search(raw)
    if match:
        lightness = float(match.group(1))
        if "%" in raw[match.start():match.end()].split()[0] or lightness > 1.5:
            lightness /= 100.0
        return oklch_to_srgb(lightness, float(match.group(2)), float(match.group(3)))

    if HEX.match(raw):
        value = raw.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return None


# --------------------------------------------------------------------------- #
# the pairs we promise to meet
# --------------------------------------------------------------------------- #
PAIRS: list[tuple[str, str, float, str]] = [
    # (foreground, background, minimum, description)
    ("--color-text-body", "--color-surface", AA_NORMAL, "body text on a card"),
    ("--color-text-body", "--color-page", AA_NORMAL, "body text on the page"),
    ("--color-text-strong", "--color-surface", AA_NORMAL, "headings on a card"),
    ("--color-text-muted", "--color-surface", AA_NORMAL, "secondary text on a card"),
    ("--color-text-muted", "--color-page", AA_NORMAL, "secondary text on the page"),
    ("--color-text-link", "--color-surface", AA_NORMAL, "links on a card"),
    ("--color-text-link", "--color-page", AA_NORMAL, "links on the page"),
    ("--color-btn-primary-text", "--color-btn-primary-bg", AA_NORMAL, "primary button label"),
    ("#ffffff", "--color-brand", AA_LARGE, "white mark on the orange logo tile (non-text)"),
    ("--color-success-text", "--color-surface", AA_NORMAL, "success text"),
    ("--color-warning-text", "--color-surface", AA_NORMAL, "warning text"),
    ("--color-error-text", "--color-surface", AA_NORMAL, "error text"),
    ("--color-blue-text", "--color-surface", AA_NORMAL, "info text"),
    ("--color-border-strong", "--color-surface", AA_LARGE, "input border (UI part)"),
    ("--color-border-strong", "--color-page", AA_LARGE, "input border on the page"),
    ("--color-brand-600", "--color-surface", AA_LARGE, "focus ring (UI part)"),
    ("--color-text-gray-500", "--color-surface", AA_LARGE, "large/secondary label"),
]

# Chip text on its tinted chip background (set in the .chip--* rules).
CHIP_PAIRS_LIGHT = [
    ("--color-gray-900", "oklch(92.52% .0045 214.33)", "Possible smoke chip"),
    ("--color-error-text", "oklch(94% .04 28.54)", "Verified chip"),
    ("--color-warning-text", "oklch(94% .05 62.11)", "Sensor only chip"),
    ("--color-blue-text", "oklch(93% .05 261.34)", "DEMO chip"),
]
CHIP_PAIRS_DARK = [
    ("oklch(92% .01 214)", "oklch(32% .01 214)", "Possible smoke chip"),
    ("--color-error-text", "oklch(30% .07 28.54)", "Verified chip"),
    ("--color-warning-text", "oklch(30% .06 62.11)", "Sensor only chip"),
    ("--color-blue-text", "oklch(30% .06 261.34)", "DEMO chip"),
]


def check(verbose: bool = False) -> int:
    css = THEME_CSS.read_text(encoding="utf-8")
    light_tokens, dark_overrides = parse_blocks(css)
    dark_tokens = {**light_tokens, **dark_overrides}

    failures: list[str] = []
    checked = 0

    for theme_name, tokens, chips in (
        ("light", light_tokens, CHIP_PAIRS_LIGHT),
        ("dark", dark_tokens, CHIP_PAIRS_DARK),
    ):
        print(f"\n=== {theme_name} theme ===")
        rows = [(fg, bg, minimum, label) for fg, bg, minimum, label in PAIRS]
        rows += [(fg, bg, AA_NORMAL, label) for fg, bg, label in chips]

        for fg_token, bg_token, minimum, label in rows:
            fg = resolve(fg_token, tokens)
            bg = resolve(bg_token, tokens)
            if fg is None or bg is None:
                failures.append(f"[{theme_name}] could not resolve {fg_token} on {bg_token}")
                continue
            ratio = contrast_ratio(fg, bg)
            checked += 1
            ok = ratio >= minimum
            mark = "PASS" if ok else "FAIL"
            if not ok:
                failures.append(
                    f"[{theme_name}] {label}: {ratio:.2f}:1 "
                    f"({to_hex(fg)} on {to_hex(bg)}) — needs {minimum}:1"
                )
            if verbose or not ok:
                print(f"  {mark}  {ratio:5.2f}:1  (min {minimum})  {label}"
                      f"  [{to_hex(fg)} on {to_hex(bg)}]")

    print(f"\nChecked {checked} token pairs across both themes.")
    if failures:
        print(f"\n{len(failures)} FAILURE(S):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("All pairs meet WCAG 2.2 AA.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    return check(args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
