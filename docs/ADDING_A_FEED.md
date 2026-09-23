# Adding a camera feed

This guide is for someone who has been handed a camera (or a whole site full of
them) and needs it showing up in Torch Camera Fusion. You do **not** need to
understand the detection pipeline, the fusion engine or the UI — none of them
know or care where a frame came from. You are only teaching the system how to
get one JPEG.

**Most cameras need no code at all — just a config block.** Work through the
steps in order and stop as soon as one works.

---

## Step 1 — Find out what the camera actually offers

Ask the camera's owner, or poke at it, until you can answer one question:
**how do I get a single still image?** There are four common answers.

| The camera is… | Usual way to get a frame | Adapter to use | Notes |
|---|---|---|---|
| **Axis** | `http://HOST/axis-cgi/jpg/image.cgi` | `snapshot_url` | Basic or digest auth. **Verify** the exact path on the model — older firmware differs. |
| **Hikvision** | `http://HOST/ISAPI/Streaming/channels/101/picture` | `snapshot_url` | Digest auth. RTSP also available at `rtsp://HOST:554/Streaming/Channels/101`. **Verify.** |
| **Dahua** | `http://HOST/cgi-bin/snapshot.cgi?channel=1` | `snapshot_url` | Digest auth. RTSP: `rtsp://HOST:554/cam/realmonitor?channel=1&subtype=0`. **Verify.** |
| **Verkada** | Cloud API (thumbnail endpoint), or enable RTSP/HLS streaming | `verkada` (stub) or `rtsp`/`hls` | The Verkada adapter is a **stub**. If the customer enables streaming, `rtsp` works today with no new code. **Verify.** |
| **Milestone / Genetec (VMS)** | Server-side REST or RTSP re-stream from the VMS, not from the camera | `rtsp` usually, else a new adapter | Auth is against the VMS, not the camera. **Verify** with their integrator. |
| **Public DOT sites** | A JSON camera list plus static JPEG URLs, refreshed every 30–60 s | `nmdot` pattern, or `snapshot_url` if the list is short | Check terms of use before anything customer-facing. **Verify.** |
| **A generic ONVIF camera** | ONVIF Profile S usually exposes RTSP | `rtsp` | ONVIF discovery is not implemented; get the RTSP URL once and put it in config. **Verify.** |

Every row is marked **verify** on purpose: vendor URL patterns change between
firmware versions, and the only way to be sure is to fetch one frame.

> **Rule of thumb.** If you can paste a URL into a browser and see a picture,
> use `snapshot_url`. If you can open it in VLC, use `rtsp` or `hls`.

---

## Step 2 — If an existing adapter fits, just add config

### A camera with a snapshot URL (`snapshot_url`)

The most common case.

```yaml
feeds:
  - id: abq_city_axis          # unique; becomes part of every camera's key
    type: snapshot_url
    enabled: true
    interval_s: 120            # be polite; never faster than the camera refreshes
    cameras:
      - id: coors_bridge       # lowercase, a-z 0-9 _ - only
        name: "Coors Blvd Bridge"
        url: "http://10.20.1.41/axis-cgi/jpg/image.cgi"
        lat: 35.0803
        lon: -106.7065
        heading: 95            # degrees clockwise from true north — see Step 5
        fov: 60
        mast_height: 9
    # Credentials come from the environment, never from this file.
    auth:
      type: digest             # or: basic
      username_env: ABQ_CAM_USER
      password_env: ABQ_CAM_PASS
    # Cameras on a private LAN need this. Without it the SSRF guard refuses
    # every request to a private address, which is the correct default.
    allow_private_network: true
```

Then put the credentials in `.env` (which is git-ignored):

```
ABQ_CAM_USER=torch-readonly
ABQ_CAM_PASS=...
```

### An RTSP camera or NVR (`rtsp`)

Needs `ffmpeg` installed. One frame is grabbed every `interval_s`; **no video
is kept**.

```yaml
  - id: site_rtsp
    type: rtsp
    enabled: true
    interval_s: 300
    allow_private_network: true
    cameras:
      - id: tower1
        name: "Watchtower 1"
        url_env: TOWER1_RTSP_URL   # the URL itself holds the password
        lat: 35.0440
        lon: -106.6791
        heading: 210
        fov: 70
        mast_height: 7.6
```

```
TOWER1_RTSP_URL=rtsp://torch:SECRET@10.20.1.55:554/Streaming/Channels/101
```

The whole URL lives in an environment variable because RTSP credentials are
embedded in it. Everywhere the app shows that URL it is passed through
`redact()` first, so logs and the UI show `rtsp://***:***@10.20.1.55:554/...`.

### An HLS stream (`hls`)

Same shape as `rtsp`, with `type: hls` and an `.m3u8` URL.

### A folder of JPEGs (`local_folder`)

For replays, tests and demos with no network:

```yaml
  - id: demo_local
    type: local_folder
    enabled: true
    folder: "./data/replay"
    cameras:
      - {id: bosque_c, name: "Bosque Central", subdir: "bosque_c", lat: 35.1002, lon: -106.6817, heading: 170, fov: 62}
```

---

## Step 3 — Only if nothing fits: write an adapter

Copy the template and fill in three methods:

```bash
cp feeds/template_adapter.py feeds/my_vendor.py
```

`feeds/template_adapter.py` is fully commented and tells you what to change. In
summary:

1. set `type` to the key you will use in `config.yaml`;
2. implement `list_cameras()` — return `Camera` objects;
3. implement `get_frame(camera)` — return a `Frame`, or `None` on failure
   (**never raise**);
4. uncomment `@register`;
5. import your module in `feeds/__init__.py`;
6. add a test (copy `tests/test_fake_adapter_flow.py`).

You get the security machinery for free as long as you use `safe_fetch` and
`normalise_to_jpeg` from the template: scheme allowlisting, private/metadata IP
blocking on every redirect, timeouts, a 10 MB cap, magic-byte checks, a
decompression-bomb guard, EXIF stripping, and path-safe camera ids.

`tests/test_fake_adapter_flow.py` exists to prove this works: it invents a feed
type the pipeline has never heard of and drives it all the way to a `verified`
event **without changing a single line** of ingest, detection or fusion. If your
new adapter needs a change in those modules, something is wrong — say so in the
pull request rather than working around it.

---

## Step 4 — Validate before you enable it

```bash
python -m feeds test abq_city_axis
```

You get a pass/fail table per camera — reachable, auth ok, frame size, time
taken — and every frame is written to `./feed_test/` so you can look at the
actual pictures.

```
=== feed: abq_city_axis  (type=snapshot_url, interval=120s) ===
list_cameras(): 1 camera(s) in 4 ms
CAMERA ID    NAME                  REACHABLE  AUTH OK  FRAME        TIME     RESULT
coors-bridge Coors Blvd Bridge     yes        yes      1920x1080    0.42s    PASS
      -> saved feed_test/abq-city-axis__coors-bridge.jpg  (218 KB)
```

Open the saved JPEGs. A feed that returns an error page, a "camera offline"
placeholder or a privacy-masked black rectangle will happily report PASS —
only your eyes catch that.

Other commands:

```bash
python -m feeds list                 # registered types and configured feeds
python -m feeds test all             # every enabled feed
python -m feeds inspect nmdot_abq    # the RAW field names a JSON source returned
```

`inspect` is the one to reach for when a JSON feed's field names are not what
the adapter expected. It prints the real keys the server returned and the
mapping the adapter resolved, so you can pin them explicitly:

```yaml
  - id: nmdot_abq
    type: nmdot
    field_map:
      name: cameraTitle      # whatever `inspect` showed
      url: imageUrl
      lat: latitude
      lon: longitude
```

---

## Step 5 — Set location, heading and field of view

Fusion and the blind-spot map are only as good as this geometry.

* **lat / lon** — where the camera physically is. If the feed supplies it, it is
  used automatically; otherwise set it in the camera's config block or in
  `camera_overrides`.
* **heading** — the direction the camera looks, in degrees clockwise from true
  north (0 = north, 90 = east, 180 = south, 270 = west).
* **fov** — horizontal field of view in degrees. 60° is a reasonable default for
  a fixed traffic camera; a wide-angle lens may be 90–110°.
* **mast_height** — metres above ground. Used by the viewshed; the default is
  `blind_spot.mast_height_m` (10 m).

**Estimating heading from a map, with no site visit:**

1. Open the camera's latest frame (`./feed_test/`) and find a landmark you can
   identify — a bridge, an interchange, a water tower.
2. Find the camera and that landmark on any map.
3. Draw a line from camera to landmark; read off its compass bearing. That is
   your heading, to within ten degrees or so, which is good enough.
4. Estimate FOV from how much of the scene fits: a view spanning a whole
   interchange is wide (~90°); a view down a single lane is narrow (~40°).

**If you do not know the heading, leave it out.** The camera then gets a 360°
disc instead of a cone, and the UI says "Heading unknown — shown as a 360°
radius" so nobody mistakes a guess for a survey. That is much better than
inventing a number.

Geometry the feed cannot tell you goes in `camera_overrides`, keyed by
`<feed_id>:<camera_id>` or by a case-insensitive name fragment:

```yaml
camera_overrides:
  "abq_city_axis:coors_bridge": {heading: 95, fov: 60, mast_height: 9}
  "name:riogrande":             {heading: 175, fov: 60, is_ptz: true}
```

---

## Step 6 — Checklist before you enable a feed

- [ ] **Permission.** You have written confirmation from the camera's owner, or
      have read the public site's terms of use and they permit this use. For
      public DOT feeds, note that "free to view" is not the same as "free to use
      commercially" — check before anything customer-facing.
- [ ] **Polite poll rate.** `interval_s` is no faster than the camera actually
      refreshes. Re-downloading the same JPEG helps nobody and looks like abuse.
      120 s is the house default; slow down further if the owner asks.
- [ ] **Credentials in env vars.** Nothing secret in `config.yaml`, which is
      committed. `.env` is git-ignored; `.env.example` holds placeholders only.
- [ ] **Private network access is deliberate.** `allow_private_network: true` is
      set only for feeds that genuinely live on a LAN, and you understand it
      relaxes the SSRF guard for that feed.
- [ ] **Retention.** Frames are deleted after `retention.frames_hours` (48 h by
      default), except those attached to a confirmed event. If the camera owner
      requires shorter retention, change it before enabling.
- [ ] **You have looked at real frames** from `./feed_test/`.
- [ ] **Geometry is set** (or deliberately left unknown).
- [ ] **No people-tracking.** This system detects smoke and fire. Do not add
      face recognition, plate reading or person tracking to an adapter.

---

## Worked example: adding a second public DOT feed

The goal is a second public agency alongside NMDOT. Two paths, depending on
what the agency actually publishes.

### If the agency publishes static JPEG snapshot URLs

Several state DOTs (Arizona 511 and Colorado's CDOT among them) publish public
camera pages. **Confirm the current URL pattern and terms of use yourself** —
these change, and neither is documented here as fact.

Once you have a handful of snapshot URLs, no code is needed:

```yaml
  - id: cdot_i25_north
    type: snapshot_url
    enabled: false            # leave disabled until `feeds test` passes
    interval_s: 300           # slower for a courtesy feed
    cameras:
      - id: cdot_monument_hill
        name: "I-25 Monument Hill"
        url: "https://REPLACE_WITH_VERIFIED_URL/monument.jpg"
        lat: 39.0870
        lon: -104.8590
        heading: 180
        fov: 60
```

```bash
python -m feeds test cdot_i25_north   # then look at ./feed_test/*.jpg
```

If that passes and the terms of use allow it, set `enabled: true`. Total code
written: none.

### If the agency publishes a JSON camera list (like NMDOT)

If it looks like NMDOT's — one JSON endpoint listing many cameras — try the
`nmdot` adapter first, since it resolves field names at runtime rather than
assuming them:

```yaml
  - id: other_dot
    type: nmdot                      # the adapter is not NMDOT-specific
    url: "https://REPLACE/GetCameraInfo"
    snapshot_base: "https://REPLACE/snapshots/"
    filter: {name_contains: ["River", "Creek"]}
```

```bash
python -m feeds inspect other_dot    # see the real field names
python -m feeds test other_dot
```

If the resolver guesses wrong, pin the names with `field_map:` (Step 4). Only if
the payload is shaped differently enough that the resolver cannot cope do you
copy `template_adapter.py`.

### If you have no network at all

Use `local_folder`, which is how the offline demo runs:

```bash
python scripts/make_fixtures.py       # writes replay frames to data/replay/
python -m feeds test demo_local
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `blocked non-public address` | The camera is on a LAN. Set `allow_private_network: true` on that feed. |
| `scheme 'rtsp' is not allowed here` | You used `snapshot_url` for an RTSP camera. Switch `type` to `rtsp`. |
| `not a JPEG or PNG (magic bytes did not match)` | The URL returned an HTML error or login page, not an image. Open it in a browser. |
| `ffmpeg is not installed` | Install ffmpeg (`brew install ffmpeg` / `apt install ffmpeg`). Only `rtsp` and `hls` need it. |
| `auth is configured as digest but ... are not set` | The env vars named in `auth:` are missing from your `.env`. |
| Cameras listed but all frames fail | Often a snapshot path that differs by firmware. Try the vendor's alternate path from the Step 1 table. |
| `camera list failed: 403 Forbidden` | Something between you and the source refused the request — a corporate proxy, an egress allowlist, or the site blocking your IP. Test from a normal network before assuming the feed is broken. |
| Frames arrive but every score is 0.00 | Expected for the first few frames: the baseline detector needs a short history per camera before it will accuse anything. |
