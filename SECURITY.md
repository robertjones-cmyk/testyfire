# Security

This is an internal prototype, but the security work was built in from the
start rather than bolted on, because the interesting parts (feeds, webhooks,
image handling) are exactly where the risk lives.

---

## Threat model summary

**What we are protecting.** Camera imagery of public and customer land; camera
credentials; the dispatch webhook (which can page a human); operator decisions
and the audit trail.

**Who we are worried about, in rough priority order:**

1. **A hostile or compromised camera feed.** This is the main attack surface. A
   feed's JSON is attacker-controlled input: it can name any URL, any camera
   name, and return any bytes. The threats are SSRF (making our server fetch
   internal or cloud-metadata endpoints), path traversal (a camera named
   `../../etc/x`), decompression bombs, and stored XSS through camera names.
2. **Someone on the same network.** The API binds to loopback by default;
   exposing it is an explicit, logged decision.
3. **A stolen browser session.** Session cookies are `HttpOnly`, server-side and
   revocable; CSRF tokens are required on every state-changing request.
4. **Credential leakage through logs.** Camera URLs routinely embed passwords.
5. **A malicious dispatch receiver, or an eavesdropper on the webhook.** Hence
   HTTPS-only, HMAC signing, and payloads that carry a link rather than imagery.
6. **Prompt injection via image content**, if vision-LLM escalation is enabled.

**Explicitly out of scope for a prototype:** a hostile administrator, physical
access to the machine, supply-chain compromise of pinned dependencies beyond
what `pip-audit`/`npm audit` catch, and denial of service.

---

## Run and network

* The backend binds to **`127.0.0.1`** unless `HOST` is set. Setting it logs a
  loud multi-line warning at startup, and `python -m app run` repeats it on
  stderr.
* There is **no TLS in this app and no cloud deployment path** — deliberately.
  If it is ever exposed, put it behind an HTTPS reverse proxy that terminates
  TLS and sets `X-Forwarded-*`.
* **CORS** allows only the frontend's own origin (`app.frontend_origins`), with
  credentials, and only `Content-Type`/`X-CSRF-Token` headers. No wildcards.
* **Security headers on every response:** a strict `Content-Security-Policy`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `frame-ancestors 'none'`,
  `Permissions-Policy` denying camera/mic/geolocation, and `Strict-Transport-
  Security` when served over HTTPS.
* The interactive API schema browsers (`/docs`, `/redoc`, `/openapi.json`) are
  **disabled**.

---

## Login and access

* **Local accounts only.** No SSO, and the login screen deliberately shows no
  fake SSO buttons.
* **Passwords are hashed with argon2id** (argon2-cffi defaults), minimum 12
  characters. There is **no default password**: `python -m app create-admin`
  prompts for one and refuses anything shorter.
* **Sessions are server-side.** The cookie holds an opaque 256-bit id and
  nothing else, so a session is revoked by deleting one row. Cookie flags:
  `HttpOnly`, `SameSite=Lax`, and `Secure` when the request is HTTPS.
* **Timeouts:** 8-hour absolute, 30-minute idle. The UI warns 2 minutes before
  the idle cut-off with a dialog that can be dismissed from the keyboard, and
  extending calls the server rather than just resetting a timer in the browser.
* **CSRF:** every state-changing request must echo the session's CSRF token in
  `X-CSRF-Token`. Rejections are audit-logged.
* **Login rate limiting:** 5 failed attempts per 15 minutes, counted **per
  account and per IP**. A correct password does not bypass an active lockout.
  The error message is always `Email or password is incorrect`, whatever
  actually failed.
* **Roles** are `viewer` (read only), `operator` (mark real / false alarm) and
  `admin` (users, demo controls, audit log). **Every role check runs on the
  server**, on every endpoint — the UI hiding a button is not access control,
  and `tests/test_api_security.py` asserts 401 without a session and 403 for the
  wrong role on each route.
* **Audit log** records logins, failed logins, authorization denials, CSRF
  rejections, alert decisions, user changes, demo triggers and every dispatch
  attempt. Admin-readable in Settings.

---

## Secrets

* All secrets live in **environment variables**, referenced from `config.yaml`
  only by variable *name* (`*_env` keys). `.env` is git-ignored; `.env.example`
  ships with placeholders only.
* Secrets are never written to `config.yaml`, the database, logs, error
  messages, or the frontend bundle.
* **`redact()`** (`app/security/redact.py`) strips credentials from URLs
  (`rtsp://user:pass@host` → `rtsp://***:***@host`), query-string secrets,
  bearer tokens and API keys. It is applied to every URL that reaches a log
  line, an error, an API response or the UI. `redact_mapping()` does the same
  for structured audit detail.
* **Mapbox:** the frontend gets its token from `/api/config/ui`, which
  **refuses to serve a secret `sk.` token** and returns an explanatory message
  instead. Use a public `pk.` token restricted to your URLs in the Mapbox
  dashboard.
* A **gitleaks** secret scan runs in CI and in the pre-commit hook.

### Rotating the webhook secret

1. Generate a new one: `python -c 'import secrets; print(secrets.token_hex(32))'`
2. Add it to the receiving system first, so it accepts both old and new.
3. Update `DISPATCH_HMAC_SECRET` in `.env` and restart the API.
4. Remove the old secret from the receiver.
5. Confirm delivery: `python scripts/test_receiver.py` prints `signature OK`.

Signatures cover `timestamp . body`, so rotation takes effect on the next
delivery. There is no key id in the header — if you need overlapping keys
without a restart, that is a small change to `sign()` and worth doing before
production.

### Rotating an admin password

```bash
python -m app create-admin --email you@torchsystems.com --force
```

Prompts for a new password and writes an audit entry. Existing sessions for
that user are **not** invalidated automatically — call
`destroy_user_sessions()` or delete the rows if that matters.

---

## Feeds — the main attack surface

Every outbound request from an adapter goes through `app/security/net.py`:

* **Per-adapter scheme allowlist.** `snapshot_url`/`hls` may use `http`/`https`;
  `rtsp` may use `rtsp`/`rtsps`. `file:`, `ftp:`, `gopher:`, `dict:`, `data:`
  and everything else are refused.
* **Destination checks after DNS resolution.** Private, loopback, link-local,
  multicast, reserved and unspecified addresses are blocked, as are cloud
  metadata endpoints (`169.254.169.254`, `metadata.google.internal`,
  `100.100.100.200`, `fd00:ec2::254`). **All** resolved addresses are checked,
  not just the first.
* **The same check on every redirect hop**, with at most 3 redirects. A public
  URL that 302s to the metadata service is refused at the second hop.
* **Customer LAN cameras require explicit opt-in** per feed
  (`allow_private_network: true`).
* **Timeouts and caps:** 5 s connect, 15 s total, 10 MB maximum download,
  enforced while streaming as well as against `Content-Length`.
* **Image intake:** magic bytes must be JPEG or PNG; decoding happens under a
  40 MP Pillow cap (decompression-bomb guard); the image is **re-encoded to
  JPEG**, which drops EXIF and any payload appended after the image data.
* **ffmpeg** is invoked via `subprocess.run([...])` with an argument list and
  **never** `shell=True`, with `-protocol_whitelist` limited to what the feed
  needs, a hard timeout that kills the process group, and `nice(10)`. The
  untrusted stream URL is only ever the value of `-i`, never an option. Only one
  frame is decoded; **no video is retained**.
* **Paths are built only from ids we generate or validate** against
  `^[a-z0-9_-]+$`. A camera named `../../etc/x` is slugified before it can reach
  the filesystem, and `safe_join()` refuses anything that escapes the frame
  directory.
* **All feed JSON is treated as untrusted:** validated with Pydantic, string
  lengths capped, coordinates range-checked. Vue escapes by default and `v-html`
  is never used on feed data.

---

## Data

* **All SQL is parameterised.** No string-built queries anywhere.
* **Images are served only through an authenticated endpoint**
  (`/api/frames/{id}/image`). The frames folder is never mounted as static
  files, and the endpoint refuses to serve any path outside the frame store even
  if a database row says otherwise.
* **Retention:** frames older than `retention.frames_hours` (48 h) are deleted
  from disk and database; logs, login attempts and dispatch records older than
  `retention.logs_days` (30) are deleted; expired sessions are purged. Frames
  attached to a confirmed event are **pinned**, kept with the event, and deleted
  with it.

---

## Dispatch webhook

* **Disabled until an admin sets a URL.**
* **HTTPS required**, with one exception: the loopback test receiver on
  `127.0.0.1`.
* **Only `verified` and `sensor_only` events are ever sent.** The check is in
  `should_dispatch()` and re-asserted in the dispatcher; a refused dispatch is
  audit-logged.
* **Every payload is signed** with HMAC-SHA256 over `timestamp . body`, and
  carries `X-Torch-Timestamp`, `X-Torch-Event-Id` and `X-Torch-Delivery-Id` so
  the receiver can reject replays and duplicates. The bundled test receiver
  demonstrates all three checks.
* **If the signing secret is missing, nothing is sent** — the system refuses
  rather than delivering unsigned.
* **The payload contains event data and a login-gated link.** Never the image
  bytes, never credentials.
* **Demo events never reach a real dispatch URL** — they are routed to the local
  test receiver regardless of configuration.
* Retries use exponential backoff and **every attempt is logged**, with the URL
  redacted.

---

## Vision-LLM escalation (optional, off by default)

* Disabled unless explicitly enabled *and* `ANTHROPIC_API_KEY` is set.
* Only frames the baseline already scored above a threshold are sent.
* **Metadata is stripped and the frame is cropped to the region of interest**
  before it leaves the machine.
* **A strict JSON schema is required.** Anything else — prose, a fenced block, a
  value outside the enum, a different key — is rejected and treated as
  `unsure`.
* **Text visible in an image is data, never instructions.** The system prompt
  says so, and schema validation is the actual enforcement: a reply that "obeys"
  injected text still has to match the schema, and an injected instruction
  cannot change what we do with the answer.
* **The LLM can only raise or lower a score.** It can never create an alert or
  trigger dispatch — that still requires a Torch sensor to agree.
* An hourly call cap and a monthly spend cap stop escalation; every call's cost
  is recorded in `llm_spend`.

---

## Supply chain

* Python and npm dependencies are **pinned** (`requirements.txt`,
  `package-lock.json`).
* CI runs `pip-audit` and `npm audit`.
* **Model weights:** none are shipped. The ONNX slot downloads from a pinned URL
  and **verifies a SHA-256** before loading; a mismatch deletes the file and
  raises. It also refuses to load weights with no recorded licence. The default
  detector uses no weights at all, partly to avoid the AGPL-3.0 licensing of
  common YOLO packages (see README).

---

## Security tests

`python -m pytest tests/test_security_feeds.py tests/test_api_security.py tests/test_dispatch.py`

Covers: SSRF refusal of `169.254.169.254`, `127.0.0.1`, private ranges,
`file:///etc/passwd` and a redirect to a private IP; path traversal for a camera
named `../../etc/x`; 401 without a session and 403 for the wrong role on every
route; CSRF rejection; login rate limiting (including that a correct password
does not bypass it); credential redaction in URLs, logs and audit detail; EXIF
stripping; decompression-bomb refusal; dispatch signing, replay resistance,
HTTPS-only targets, demo routing, and the refusal to send `possible_smoke`.

---

## Known gaps

Honest list. None are hidden.

1. **`style-src 'unsafe-inline'` is required by the CSP.** Naive UI injects
   component styles at runtime (CSS-in-JS). This measurably weakens the policy
   against style-based injection. `script-src` remains `'self'` with no inline
   scripts, which is the more important half. Fixing it properly means
   extracting Naive UI's styles at build time or adopting nonces.
2. **One inline `<script>` in `index.html`** sets the theme before first paint
   to avoid a flash of the wrong theme. It is allowed by a **SHA-256 hash
   computed at startup from the built `index.html` being served**, so
   `script-src` stays `'self'` with no `'unsafe-inline'`, and editing the script
   cannot silently break the policy or silently widen it.
3. **DNS rebinding (TOCTOU).** The SSRF guard resolves a hostname, validates
   every address, and then makes the request — during which DNS could change.
   Closing this needs connecting to the validated IP with SNI pinned, which
   `httpx` does not do out of the box.
4. **No key id in webhook signatures**, so rotating the secret needs the
   receiver to accept both for a moment.
5. **Admin password reset does not invalidate existing sessions.**
6. **`X-Forwarded-For` is not trusted**, so behind a reverse proxy the rate
   limiter and audit log see the proxy's IP until that is configured
   deliberately.
7. **No account lockout beyond the rate limit**, and no 2FA.
8. **The audit log is not tamper-evident.** An admin with database access can
   edit it.
9. **No encryption at rest.** Frames and the SQLite database sit in plain files;
   the host's disk encryption is the only protection.
10. **Detector temporal state is in memory**, so a restart briefly suppresses
    detection while each camera rebuilds its baseline. Not a security issue, but
    it is an availability property worth knowing.
