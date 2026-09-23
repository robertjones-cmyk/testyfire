"""Feed validation CLI.

    python -m feeds list                 # registered adapter types + configured feeds
    python -m feeds test <feed_id>       # list cameras, pull one frame each, save to ./feed_test/
    python -m feeds test all             # every enabled feed
    python -m feeds inspect <feed_id>    # show the RAW field names the source returned

Run ``test`` before enabling any feed. It never writes to the database.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.config import get_config
from app.security.paths import slugify_id
from app.security.redact import redact

from . import available_types, build
from .base import FeedAdapter

OUT_DIR = Path("./feed_test")


def _row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(str(c)[:w].ljust(w) for c, w in zip(cells, widths))


def cmd_list(config) -> int:
    print(f"Registered adapter types: {', '.join(available_types())}\n")
    widths = [16, 14, 8, 9, 6]
    print(_row(["FEED ID", "TYPE", "ENABLED", "INTERVAL", "AUTH"], widths))
    print("-" * (sum(widths) + 2 * len(widths)))
    for entry in config.feeds():
        try:
            adapter = build(entry)
            auth = "yes" if adapter.auth_required else "no"
            interval = f"{adapter.interval_s}s"
            feed_type = adapter.type
        except Exception as exc:
            auth, interval, feed_type = "?", "?", f"ERROR: {exc}"
        print(_row([
            str(entry.get("id")), feed_type,
            "yes" if entry.get("enabled", True) else "no", interval, auth,
        ], widths))
    return 0


def _test_one(adapter: FeedAdapter, feed_id: str, limit: int) -> tuple[int, int]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n=== feed: {feed_id}  (type={adapter.type}, interval={adapter.interval_s}s) ===")

    started = time.perf_counter()
    cameras = adapter.cameras(refresh=True)
    list_ms = (time.perf_counter() - started) * 1000
    print(f"list_cameras(): {len(cameras)} camera(s) in {list_ms:.0f} ms")

    if not cameras:
        health = adapter.health()
        print(f"  FAIL  no cameras. last_error: {health.get('last_error') or '(none)'}")
        return 0, 1

    widths = [22, 26, 9, 9, 11, 9, 8]
    print(_row(["CAMERA ID", "NAME", "REACHABLE", "AUTH OK", "FRAME", "TIME", "RESULT"], widths))
    print("-" * (sum(widths) + 2 * len(widths)))

    passed = failed = 0
    for camera in cameras[:limit]:
        t0 = time.perf_counter()
        frame = adapter.get_frame(camera)
        elapsed = time.perf_counter() - t0
        if frame is None:
            failed += 1
            print(_row([
                camera.id, camera.name, "no",
                "n/a" if not adapter.auth_required else "check",
                "-", f"{elapsed:.2f}s", "FAIL",
            ], widths))
            print(f"      -> {adapter.health().get('last_error') or 'no frame returned'}")
            continue

        passed += 1
        out_path = OUT_DIR / f"{slugify_id(feed_id)}__{camera.id}.jpg"
        out_path.write_bytes(frame.jpeg)
        size_kb = len(frame.jpeg) / 1024
        print(_row([
            camera.id, camera.name, "yes",
            "yes" if adapter.auth_required else "n/a",
            f"{frame.width}x{frame.height}", f"{elapsed:.2f}s", "PASS",
        ], widths))
        print(f"      -> saved {out_path}  ({size_kb:.0f} KB)  src={redact(frame.source_url)}")

        geo_bits = []
        if not camera.has_location():
            geo_bits.append("no lat/lon (set it in config camera_overrides)")
        if camera.heading is None:
            geo_bits.append("no heading (view cone will be a 360 disc)")
        if camera.fov is None:
            geo_bits.append("no fov")
        if geo_bits:
            print(f"      !  {'; '.join(geo_bits)}")

    if len(cameras) > limit:
        print(f"... {len(cameras) - limit} more camera(s) not tested (use --limit)")

    print(f"\nhealth(): {json.dumps(adapter.health(), indent=2)}")
    print(f"RESULT: {passed} passed, {failed} failed -> frames in {OUT_DIR.resolve()}")
    return passed, failed


def cmd_test(config, feed_id: str, limit: int) -> int:
    entries = config.enabled_feeds() if feed_id == "all" else [config.feed(feed_id)]
    if entries == [None]:
        print(f"No feed with id {feed_id!r} in {config.path}.", file=sys.stderr)
        print(f"Known feeds: {', '.join(str(f.get('id')) for f in config.feeds())}", file=sys.stderr)
        return 2

    total_pass = total_fail = 0
    for entry in entries:
        try:
            adapter = build(entry)
        except Exception as exc:
            print(f"\n=== feed: {entry.get('id')} ===\n  FAIL  could not build adapter: {exc}")
            total_fail += 1
            continue
        passed, failed = _test_one(adapter, str(entry.get("id")), limit)
        total_pass += passed
        total_fail += failed

    print(f"\n==== TOTAL: {total_pass} passed, {total_fail} failed ====")
    return 0 if total_fail == 0 and total_pass > 0 else 1


def cmd_inspect(config, feed_id: str) -> int:
    entry = config.feed(feed_id)
    if entry is None:
        print(f"No feed with id {feed_id!r}", file=sys.stderr)
        return 2
    adapter = build(entry)
    cameras = adapter.cameras(refresh=True)
    print(f"feed {feed_id}: {len(cameras)} camera(s)")
    if hasattr(adapter, "describe_schema"):
        print("\nRAW SOURCE SCHEMA (what the server actually returned):")
        print(json.dumps(adapter.describe_schema(), indent=2, default=str))
        print(
            "\nPin these names in config.yaml under this feed's `field_map:` if the\n"
            "resolved mapping above is wrong."
        )
    else:
        print("(this adapter has no describe_schema(); its cameras come from config)")
    for camera in cameras[:5]:
        print(json.dumps(camera.public_dict(), indent=2, default=str))
    print(f"\nhealth(): {json.dumps(adapter.health(), indent=2)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m feeds", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list registered adapter types and configured feeds")
    p_test = sub.add_parser("test", help="validate a feed end to end")
    p_test.add_argument("feed_id", help="feed id from config.yaml, or 'all'")
    p_test.add_argument("--limit", type=int, default=12, help="max cameras to test (default 12)")
    p_inspect = sub.add_parser("inspect", help="show the raw field names a source returned")
    p_inspect.add_argument("feed_id")

    args = parser.parse_args(argv)
    config = get_config(args.config)

    if args.command == "list":
        return cmd_list(config)
    if args.command == "test":
        return cmd_test(config, args.feed_id, args.limit)
    if args.command == "inspect":
        return cmd_inspect(config, args.feed_id)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
