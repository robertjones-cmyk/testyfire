/**
 * Naive UI theme overrides driven by the Torch CSS variables.
 *
 * Naive UI cannot read `var(--x)` for every property, so the tokens are read
 * off the document at runtime and fed in as concrete colours. That keeps one
 * source of truth (theme.css) while still theming Naive components.
 */
import type { GlobalThemeOverrides } from 'naive-ui'

/**
 * Convert an `oklch()` colour to `rgb()`.
 *
 * This is NOT optional. Our design tokens are authored in `oklch()`, and Naive
 * UI's colour library (seemly) cannot parse it — it throws
 * "Invalid color value oklch(...)" while deriving hover/pressed shades, which
 * kills the render of every component that does colour maths. NInput renders as
 * nothing at all, so the login form comes up with no fields.
 *
 * Reading the value back through `getComputedStyle` does not help: Chromium
 * preserves the colour space and hands back `oklch(...)` again. So the
 * conversion is done here, with the same maths as `scripts/check_contrast.py`
 * (which is what verifies our contrast ratios), keeping one definition of what
 * a token actually looks like.
 */
const OKLCH = /oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+)%?\s*)?\)/i

function gammaEncode(channel: number): number {
  return channel <= 0.0031308 ? 12.92 * channel : 1.055 * Math.pow(channel, 1 / 2.4) - 0.055
}

export function oklchToRgb(value: string): string {
  const match = OKLCH.exec(value)
  if (!match) return value

  let lightness = Number(match[1])
  // `oklch(68.38% ...)` and `oklch(0.6838 ...)` are the same colour.
  if (value.slice(match.index).includes('%') && lightness > 1.5) lightness /= 100
  else if (lightness > 1.5) lightness /= 100

  const chroma = Number(match[2])
  const hue = (Number(match[3]) * Math.PI) / 180
  const alphaRaw = match[4]

  const a = chroma * Math.cos(hue)
  const b = chroma * Math.sin(hue)

  const l = Math.pow(lightness + 0.3963377774 * a + 0.2158037573 * b, 3)
  const m = Math.pow(lightness - 0.1055613458 * a - 0.0638541728 * b, 3)
  const s = Math.pow(lightness - 0.0894841775 * a - 1.291485548 * b, 3)

  const channels = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((channel) => Math.round(Math.min(1, Math.max(0, gammaEncode(Math.min(1, Math.max(0, channel))))) * 255))

  if (alphaRaw !== undefined) {
    const alpha = alphaRaw.includes('%') ? Number(alphaRaw.replace('%', '')) / 100 : Number(alphaRaw)
    return `rgba(${channels[0]}, ${channels[1]}, ${channels[2]}, ${alpha})`
  }
  return `rgb(${channels[0]}, ${channels[1]}, ${channels[2]})`
}

/** Add an alpha channel to an `rgb()` string (hex-style suffixes do not work). */
function withAlpha(rgb: string, alpha: number): string {
  const match = /rgba?\(([^)]+)\)/.exec(rgb)
  if (!match) return rgb
  const [r, g, b] = match[1].split(',').map((part) => part.trim())
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function token(name: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  if (!value) return fallback
  return value.includes('oklch') ? oklchToRgb(value) : value
}

export function buildThemeOverrides(): GlobalThemeOverrides {
  const brand = token('--color-brand', '#FF5B24')
  const brand600 = token('--color-brand-600', brand)
  const primary = token('--color-primary', '#101828')
  const textBody = token('--color-text-body', '#2e3638')
  const textMuted = token('--color-text-muted', '#5c6d70')
  const surface = token('--color-surface', '#ffffff')
  const page = token('--color-page', '#f8fafa')
  const sunken = token('--color-surface-sunken', '#f2f5f5')
  const border = token('--color-border', '#d5dcdd')
  const borderStrong = token('--color-border-strong', '#7c8d90')
  const divider = token('--color-divider', '#e3e7e8')
  const success = token('--color-success', '#1fa463')
  const warning = token('--color-warning', '#f2a33c')
  const error = token('--color-error', '#e5484d')
  const info = token('--color-blue', '#5b8def')

  return {
    common: {
      fontFamily: token('--font-sans', 'Manrope, sans-serif'),
      fontWeight: '500',
      fontWeightStrong: '700',
      primaryColor: primary,
      primaryColorHover: primary,
      primaryColorPressed: primary,
      primaryColorSuppl: primary,
      infoColor: info,
      successColor: success,
      warningColor: warning,
      errorColor: error,
      textColorBase: textBody,
      textColor1: token('--color-text-strong', primary),
      textColor2: textBody,
      textColor3: textMuted,
      baseColor: surface,
      bodyColor: page,
      cardColor: surface,
      modalColor: surface,
      popoverColor: surface,
      tableColor: surface,
      inputColor: surface,
      borderColor: border,
      dividerColor: divider,
      // Shape
      borderRadius: token('--radius-control', '8px'),
      borderRadiusSmall: token('--radius-tag', '4px'),
      heightMedium: token('--control-height', '44px'),
      heightLarge: token('--control-height-lg', '48px'),
      boxShadow2: token('--shadow-float', '0 12px 16px -4px rgba(0,0,0,.08)'),
    },
    Button: {
      // Primary button: navy in light, light in dark. Orange is an accent only.
      colorPrimary: token('--color-btn-primary-bg', primary),
      colorHoverPrimary: token('--color-btn-primary-bg', primary),
      colorPressedPrimary: token('--color-btn-primary-bg', primary),
      colorFocusPrimary: token('--color-btn-primary-bg', primary),
      textColorPrimary: token('--color-btn-primary-text', '#fff'),
      textColorHoverPrimary: token('--color-btn-primary-text', '#fff'),
      textColorPressedPrimary: token('--color-btn-primary-text', '#fff'),
      textColorFocusPrimary: token('--color-btn-primary-text', '#fff'),
      borderPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      borderHoverPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      borderFocusPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      borderPressedPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      border: `1px solid ${borderStrong}`,
      textColor: textBody,
      heightMedium: token('--control-height', '44px'),
      heightLarge: token('--control-height-lg', '48px'),
      fontWeight: '600',
      borderRadiusMedium: token('--radius-control', '8px'),
    },
    Input: {
      border: `1px solid ${borderStrong}`,
      borderHover: `1px solid ${borderStrong}`,
      borderFocus: `1px solid ${brand600}`,
      boxShadowFocus: `0 0 0 2px ${withAlpha(brand600, 0.25)}`,
      heightMedium: token('--control-height', '44px'),
      heightLarge: token('--control-height-lg', '48px'),
      borderRadius: token('--radius-control', '8px'),
      color: surface,
      textColor: textBody,
      placeholderColor: textMuted,
    },
    Card: {
      borderRadius: token('--radius-card', '12px'),
      color: surface,
      borderColor: border,
      titleFontWeight: '700',
    },
    DataTable: {
      thColor: sunken,
      thTextColor: token('--color-text-strong', primary),
      thFontWeight: '700',
      tdColor: surface,
      tdTextColor: textBody,
      borderColor: divider,
      borderRadius: token('--radius-card', '12px'),
      thPaddingMedium: '12px 16px',
      tdPaddingMedium: '12px 16px',
    },
    Drawer: { color: surface, textColor: textBody },
    Tabs: {
      tabTextColorActiveLine: token('--color-text-strong', primary),
      tabTextColorLine: textMuted,
      barColor: brand,
      tabFontWeightActive: '700',
    },
    Select: { peers: { InternalSelection: { border: `1px solid ${borderStrong}` } } },
    Tag: { borderRadius: token('--radius-tag', '4px'), heightMedium: '24px' },
    Switch: { railColorActive: brand, loadingColor: brand },
    Progress: { fillColor: brand, fillColorInfo: info },
    Dialog: { borderRadius: token('--radius-card', '12px') },
    Alert: { borderRadius: token('--radius-card', '12px') },
    Message: { borderRadius: token('--radius-control', '8px') },
  }
}
