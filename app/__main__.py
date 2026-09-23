"""Torch Camera Fusion CLI.

    python -m app create-admin              # prompts for a password (min 12 chars)
    python -m app create-user --role operator
    python -m app run                       # start the API + ingest worker
    python -m app retention                 # run the retention job once
    python -m app blindspot                 # compute and print the blind-spot summary
    python -m app poll-once                 # one ingest cycle, no server (useful in tests)
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import db
from .audit import record as audit_record
from .config import get_config
from .security.auth import MIN_PASSWORD_LENGTH, create_user, get_user_by_email, set_password


def _prompt_password(label: str = "Password") -> str:
    while True:
        first = getpass.getpass(f"{label} (min {MIN_PASSWORD_LENGTH} chars): ")
        if len(first) < MIN_PASSWORD_LENGTH:
            print(f"  Too short — {MIN_PASSWORD_LENGTH} characters minimum.", file=sys.stderr)
            continue
        second = getpass.getpass("Repeat: ")
        if first != second:
            print("  Passwords do not match.", file=sys.stderr)
            continue
        return first


def cmd_create_user(args, role: str) -> int:
    email = args.email or input("Email: ").strip()
    if get_user_by_email(email):
        if not args.force:
            print(f"User {email} already exists. Use --force to reset the password.", file=sys.stderr)
            return 1
        set_password(email, _prompt_password("New password"))
        audit_record("user.password_reset", target=email, detail={"via": "cli"})
        print(f"Password updated for {email}.")
        return 0

    create_user(email, _prompt_password(), role)
    audit_record("user.created", target=email, detail={"role": role, "via": "cli"})
    print(f"Created {role} {email}.")
    return 0


def cmd_run(args) -> int:
    import uvicorn

    from .main import resolve_host

    config = get_config()
    host, exposed = resolve_host()
    port = int(args.port or config.get("app.port", 8000))
    if exposed:
        print(
            f"WARNING: HOST={host} exposes this prototype on the network with no TLS.\n"
            "         Put it behind an HTTPS reverse proxy. See SECURITY.md.",
            file=sys.stderr,
        )
    uvicorn.run("app.main:app", host=host, port=port, reload=bool(args.reload), log_level="info")
    return 0


def cmd_retention(args) -> int:
    from .pipeline.retention import run_retention

    print(json.dumps(run_retention(get_config()), indent=2))
    return 0


def cmd_blindspot(args) -> int:
    from .geo import blindspot

    report = blindspot.build(get_config(), refresh=True)
    print(json.dumps(report["summary"], indent=2))
    print("\n" + report["accuracy_note"])
    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as handle:
            handle.write(report["csv"])
        print(f"\nProposed sensor placements written to {args.csv}")
    return 0


def cmd_poll_once(args) -> int:
    from .pipeline.ingest import IngestWorker

    worker = IngestWorker(get_config())
    worker.build_adapters()
    worker.sync_cameras()
    worker.sync_sensors()
    frames = worker.poll_once()
    readings = worker.poll_sensors()
    print(f"stored {frames} frame(s), {readings} sensor reading(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("create-admin", "create-operator", "create-viewer", "create-user"):
        p = sub.add_parser(name)
        p.add_argument("--email", default=None)
        p.add_argument("--force", action="store_true", help="reset the password if the user exists")
        if name == "create-user":
            p.add_argument("--role", default="viewer", choices=("viewer", "operator", "admin"))

    p_run = sub.add_parser("run")
    p_run.add_argument("--port", type=int, default=None)
    p_run.add_argument("--reload", action="store_true")

    sub.add_parser("retention")
    p_blind = sub.add_parser("blindspot")
    p_blind.add_argument("--csv", default=None, help="also write the proposed placements to this CSV")
    sub.add_parser("poll-once")

    args = parser.parse_args(argv)
    config = get_config(args.config)
    db.configure(config.db_path)
    db.init_db()

    if args.command == "create-admin":
        return cmd_create_user(args, "admin")
    if args.command == "create-operator":
        return cmd_create_user(args, "operator")
    if args.command == "create-viewer":
        return cmd_create_user(args, "viewer")
    if args.command == "create-user":
        return cmd_create_user(args, args.role)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "retention":
        return cmd_retention(args)
    if args.command == "blindspot":
        return cmd_blindspot(args)
    if args.command == "poll-once":
        return cmd_poll_once(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
