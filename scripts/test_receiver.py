"""Local dispatch test receiver.

Logs every payload it receives and verifies the HMAC signature, so you can see
exactly what a real dispatch endpoint would get:

    python scripts/test_receiver.py          # listens on 127.0.0.1:8001

It binds to loopback only and never stores imagery (the payload has none).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI, Request, Response

from app.pipeline.dispatch import (
    DELIVERY_ID_HEADER,
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    verify_signature,
)

MAX_SKEW_SECONDS = 300
app = FastAPI(title="Torch dispatch test receiver")
_seen: set[str] = set()


@app.post("/dispatch-test")
async def receive(request: Request) -> Response:
    body = await request.body()
    timestamp = request.headers.get(TIMESTAMP_HEADER, "")
    signature = request.headers.get(SIGNATURE_HEADER, "")
    delivery_id = request.headers.get(DELIVERY_ID_HEADER, "")
    secret = os.environ.get("DISPATCH_HMAC_SECRET", "")

    checks: list[str] = []
    if not secret:
        checks.append("NO SECRET SET — cannot verify (export DISPATCH_HMAC_SECRET)")
    elif verify_signature(secret, timestamp, body, signature):
        checks.append("signature OK")
    else:
        checks.append("SIGNATURE MISMATCH — payload rejected")
        _log(body, checks, delivery_id, request.headers.get(EVENT_ID_HEADER, "?"))
        return Response(status_code=401, content="bad signature")

    try:
        skew = abs(time.time() - int(timestamp))
        checks.append(f"timestamp skew {skew:.0f}s" + (" — TOO OLD" if skew > MAX_SKEW_SECONDS else " OK"))
        if skew > MAX_SKEW_SECONDS:
            return Response(status_code=400, content="stale timestamp")
    except (TypeError, ValueError):
        checks.append("timestamp unparseable")
        return Response(status_code=400, content="bad timestamp")

    if delivery_id in _seen:
        checks.append("DUPLICATE delivery id — ignored")
        _log(body, checks, delivery_id, request.headers.get(EVENT_ID_HEADER, "?"))
        return Response(status_code=200, content="duplicate ignored")
    _seen.add(delivery_id)

    _log(body, checks, delivery_id, request.headers.get(EVENT_ID_HEADER, "?"))
    return Response(status_code=200, content="ok")


def _log(body: bytes, checks: list[str], delivery_id: str, event_id: str) -> None:
    print("\n" + "=" * 72)
    print(f"DISPATCH RECEIVED  event={event_id}  delivery={delivery_id}")
    for check in checks:
        print(f"  - {check}")
    try:
        print(json.dumps(json.loads(body), indent=2))
    except json.JSONDecodeError:
        print(body[:2000])
    print("=" * 72, flush=True)


if __name__ == "__main__":
    print("Dispatch test receiver on http://127.0.0.1:8001/dispatch-test (loopback only)")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
