# Torch Camera Fusion — Prototype

An internal prototype that answers one question: **can Torch turn other
people's cameras into a smoke-detection network, and use that to justify where
Torch sensors should go?**

It pulls snapshots from existing public cameras every two minutes, flags
possible smoke on them, upgrades an alert to *verified* only when a nearby Torch
sensor agrees, and maps the ground the cameras cannot see — which becomes the
sensor placement proposal.

It is built as a module of the Torch platform: same stack (Python/FastAPI +
Vue 3 + Naive UI + Mapbox), same design tokens, same vocabulary.

> **Status: prototype, internal use only.** Not deployed, not customer-facing.
> See [Known limitations](#known-limitations) before quoting any number from it.

---

## Block diagram

```
  public DOT JSON ─┐
  Axis/Hikvision  ─┤
  RTSP NVR        ─┼──▶  FeedAdapter  ──▶  SSRF guard ──▶  JPEG bytes
  HLS stream      ─┤     (one file +       + image             │
  local folder    ─┤      config block)     intake             │
  Verkada (stub)  ─┘                                           │
                                                               ▼
                                       ┌───────────────────────────────┐
                                       │  ingest → view-change → score │
                                       └───────────────┬───────────────┘
                                                       │  score ≥ threshold
                                                       ▼
   Torch sensors ──────────────────────────▶  ┌────────────────┐
   (mock now, real API later)                 │ FUSION ENGINE  │
                                              └───┬───┬────┬───┘
                        no sensor agrees ─────────┘   │    └───── sensor alone
                                │                     │                │
                                ▼                     ▼                ▼
                        possible_smoke            verified        sensor_only
                        (dashboard only)      (camera+sensor)   (sensors see what
                                │                     │          cameras cannot)
                                │                     │                │
                          ✗ never sent                └──── dispatch ──┘
                                                       (HMAC-signed, link only)
```

A fuller diagram, and why the boundaries sit where they do, is in
[`docs/architecture.md`](docs/architecture.md).

---

## Quick start

```bash
./scripts/run.sh
```

That sets up the virtualenv, installs dependencies, writes a `.env` with a
generated webhook signing secret, generates offline replay frames, builds the
frontend, creates the database, prompts you for an admin password, and starts
both the API and the dispatch test receiver.

Then open **http://127.0.0.1:8000** and log in.

Two things worth setting before you start:

```bash
# In .env — a PUBLIC Mapbox token (starts with pk.). Without it the map shows a
# labelled placeholder and everything else still works.
MAPBOX_TOKEN=pk....
```

To create more accounts:

```bash
python -m app create-operator --email operator@torchsystems.com
python -m app create-viewer   --email viewer@torchsystems.com
python -m app create-admin --email you@torchsystems.com --force   # reset a password
```

### Running the pieces separately

```bash
python -m app run                    # API + ingest worker (127.0.0.1:8000)
python scripts/test_receiver.py      # dispatch test receiver (127.0.0.1:8001)
cd web && npm run dev                # frontend with hot reload (127.0.0.1:5173)
python -m app poll-once              # one ingest cycle, no server
python -m app blindspot --csv out.csv
python -m app retention              # run the retention job by hand
```

---

## Adding a camera

**Most cameras need no code — just a config block.** Full guide:
[`docs/ADDING_A_FEED.md`](docs/ADDING_A_FEED.md).

The short version:

```yaml
# config.yaml
feeds:
  - id: my_site
    type: snapshot_url               # or: rtsp, hls, local_folder, nmdot
    enabled: true
    interval_s: 120
    cameras:
      - {id: cam1, name: "Gate camera", url: "http://HOST/axis-cgi/jpg/image.cgi",
         lat: 35.08, lon: -106.65, heading: 270, fov: 60}
    auth: {type: digest, username_env: MY_CAM_USER, password_env: MY_CAM_PASS}
    allow_private_network: true      # required for cameras on a LAN
```

```bash
python -m feeds test my_site         # pass/fail table + frames in ./feed_test/
```

Adapters shipped today: `nmdot`, `snapshot_url`, `rtsp`, `hls`, `local_folder`,
and a `verkada` stub. A genuinely new source means copying
`feeds/template_adapter.py` and implementing three methods — with **no changes
to ingest, detection, fusion or the UI**. `tests/test_fake_adapter_flow.py`
proves that by driving an invented feed type all the way to a verified event.

---

## Plugging in the real Torch sensor API

`app/sensors/torch_api.py` is a stub with TODOs marking exactly what is needed.
Fusion, the database and the UI already speak `SensorReading`, so finishing that
one class is the whole integration:

1. implement `list_sensors()` against the device/asset endpoint;
2. implement `poll()` against the latest-readings endpoint, mapping their fields
   onto `temp_c`, `thermal_hotspot`, `thermal_delta_c`, `smoke_index`,
   `audio_event`, `battery`;
3. put the credential in an env var named from config — never in `config.yaml`;
4. set `sensors.source: torch_api`.

If the platform can push (websocket or webhook), prefer that over polling and
feed readings into the same `record_readings` path.

---

## How it works

| Stage | What happens |
|---|---|
| **Ingest** | Each enabled feed is polled every `interval_s` (default 120 s) per camera. The JPEG is re-encoded, stored under a path built only from generated ids, and recorded in SQLite with its SHA-256. |
| **View change** | These are mostly PTZ cameras that operators move. Each frame is compared to the camera's reference by perceptual hash *and* structural similarity. A moved view is flagged, **cannot raise a smoke alert**, and is adopted as the new reference after 3 stable frames. View changes are counted per camera per day. |
| **Detection** | `BaselineDetector` scores every frame on desaturation, departure from that camera's own recent history, and contrast collapse — a few milliseconds on a laptop CPU, no model weights, no network. `VisionLLMEscalation` can add a second opinion on already-suspicious frames (off by default). |
| **Fusion** | A score above threshold opens `possible_smoke`. If a Torch sensor inside the camera's view polygon (or within `sensor_match_radius_m`) reports smoke/gas or a thermal anomaly within ±10 minutes, it becomes `verified`. A sensor anomaly nobody's camera corroborates becomes `sensor_only`. |
| **Dispatch** | **Only `verified` and `sensor_only` are ever sent.** `possible_smoke` stays in the dashboard. Payloads are HMAC-SHA256 signed with a timestamp and event id, carry a login-gated link, and never contain imagery or credentials. |
| **Blind spot** | A real elevation model (AWS Terrain Tiles, cached and checksummed) drives a per-camera viewshed over the Rio Grande bosque corridor. Everything unseen is the blind-spot layer; greedy set-cover places 10-acre sensors over it, nearest the river and roads first. |

### The detection model, and why there isn't one

The obvious choice is a YOLO model trained on the public **D-Fire** dataset. The
problem is licensing: the popular YOLOv5/YOLOv8 packages (Ultralytics) are
**AGPL-3.0**, which is a poor fit for a commercial product, and many published
D-Fire checkpoints inherit it.

Rather than quietly ship an AGPL dependency, the default detector is classical
computer vision with **no model weights at all** — no licence exposure, no
download, no GPU, and about 7 ms per frame. `app/pipeline/detect/onnx.py` is the
slot for a permissively licensed (MIT/Apache-2.0/BSD) ONNX model: set the URL
and SHA-256, record the licence in config, and weights are only loaded if the
checksum matches.

**This is a real trade-off and worth naming:** the baseline detector is a
motion-and-colour heuristic, not a trained smoke classifier. It will do worse
than a good model on hard cases — thin smoke at distance, dust, low sun, fog.
Picking a licence-clean model is the single highest-value follow-up if this goes
past prototype.

---

## Kill-criteria metrics

On the Dashboard and in a daily CSV (`/api/metrics/daily.csv`), per camera per
day: frames ingested, frames failed, view changes, `possible_smoke` alerts, how
many a human marked false, `verified` alerts, and average inference cost per
frame.

A camera is flagged **red** when false alarms needing a human exceed **3 per
camera per day**, or view changes exceed **10 per camera per day**. Both live in
`config.yaml` under `kill_criteria`.

Cost target: well under **$0.001 per frame**. With the baseline detector the
measured cost is **$0.00** — it makes no API calls. Cost only appears if you
enable vision-LLM escalation, which has an hourly call cap and a monthly spend
cap.

---

## Demo

[`demo.md`](demo.md) is a script you can follow start to finish: bring the
system up, show live frames, trigger the fire scenario, watch an alert go from
*possible smoke* to *verified* and hit the dispatch webhook, then show the
blind-spot map and the sensor count.

For showing someone who will not run the stack,
[`prototype/torch-camera-fusion.html`](prototype/torch-camera-fusion.html) is a
single self-contained HTML file — open it in a browser, press **Run fire
scenario**, and the same story plays out against mock state.

---

## Tests

```bash
python -m pytest                                    # 160 backend tests
python scripts/check_contrast.py                    # WCAG contrast on every token pair
cd web && npm run test:a11y                         # axe-core on every screen, both themes
```

Covered: fusion rules (the upgrade, the ±10-minute window, the distance rule,
the dispatch rule), view-change detection, SSRF, path traversal, credential
redaction, auth (401/403 on every route), CSRF, login rate limiting, dispatch
signing, blind-spot arithmetic, and a fake-adapter test proving a new feed type
flows through the whole pipeline untouched.

Current state: **160 backend tests pass**, **42/42 contrast pairs pass in both
themes**, and **20/20 accessibility tests pass** (axe-core on every screen in
both themes, plus structural checks).

Security and accessibility details: [`SECURITY.md`](SECURITY.md),
[`ACCESSIBILITY.md`](ACCESSIBILITY.md).

---

## Known limitations

* **The NMDOT feed is unverified against the live source.** The adapter is
  written and tested, but the machine this was built on could not reach
  `nmroads.com` (blocked upstream), so the real JSON field names were never
  confirmed. The adapter resolves field names at runtime from a list of common
  aliases and handles several payload shapes; run
  `python -m feeds inspect nmdot_abq` on a normal network to see the real keys
  in one command, and pin them with `field_map:` if the guess is wrong. **Treat
  this as the first thing to check.**
* **The blind-spot viewshed is bare-earth.** It does not model the cottonwood
  canopy, buildings, camera optics or real resolution limits, and headings and
  fields of view come from config rather than a survey. Coverage percentages are
  estimates with a wide error bar.
* **The coverage number depends on which cameras are live.** With only the
  offline replay cameras, corridor coverage looks very low. It is only
  meaningful once the real NMDOT cameras are ingesting.
* **Sensors are mocked.** Readings come from `MockSensorSource`. No Torch
  hardware is involved.
* **The detector is a heuristic, not a trained model** (see above).
* **Detector temporal state is in memory.** Restarting the worker makes each
  camera rebuild its few-frame baseline, during which it will not raise alerts.
* **NMDOT terms of use have not been checked for commercial use.** Public
  viewing is not the same as commercial redistribution. This must be resolved
  before anything customer-facing.
* **No cloud deployment.** Loopback only by design; exposing it needs an HTTPS
  reverse proxy.

## Scope boundaries

This system detects **smoke and fire only**. There is no face recognition, no
licence plate reading, and no person tracking, and none should be added. If a
person or a plate happens to be visible in a frame during internal review that
is unavoidable, but nothing extracts, indexes or exports it. Camera images are
never written to a public location and are served only through an authenticated
endpoint.
