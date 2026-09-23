# Demo script

About 10 minutes. Shows live camera frames, an alert going from *possible
smoke* to *verified*, the dispatch webhook firing, and the blind-spot map with
a sensor count and hardware cost.

Everything below runs locally. Nothing is deployed and nothing is sent outside
the machine except the camera polls themselves.

---

## Before you start

```bash
./scripts/run.sh
```

It sets everything up and prompts you for an admin password. Optional but worth
it: put a public Mapbox token (`pk....`) in `.env` as `MAPBOX_TOKEN` so the map
renders — without it you get a labelled placeholder and the rest still works.

Open a second terminal for the dispatch receiver's output; `run.sh` starts it
for you and it prints every delivery.

Log in at **http://127.0.0.1:8000** as the admin you just created.

---

## 1. The feeds are real, and adding one is config (1 min)

Start outside the browser, because this is the part that decides whether the
architecture holds up.

```bash
python -m feeds list
```

```
Registered adapter types: hls, local_folder, nmdot, rtsp, snapshot_url, verkada

FEED ID           TYPE            ENABLED   INTERVAL   AUTH
nmdot_abq         nmdot           yes       120s       no
abq_city_axis     snapshot_url    no        120s       no
site_rtsp         rtsp            no        300s       yes
demo_local        local_folder    yes       120s       no
...
```

> **Say this out loud:** six source types, and adding a seventh is one file.
> Five of the six work today; Verkada is an honest stub.

Now validate a feed end to end:

```bash
python -m feeds test demo_local
```

It lists cameras, pulls one frame from each, saves them to `./feed_test/`, and
prints a pass/fail table with frame size and timing. **Open the saved JPEGs** —
that habit catches feeds that "pass" while returning an error page.

If you are on a network that can reach NMDOT, this is the moment to run:

```bash
python -m feeds inspect nmdot_abq
```

which prints the *real* JSON field names the server returned. See the caveat in
the README — that call has not been verified against the live source.

---

## 2. Live frames coming in (2 min)

In the browser, go to **Cameras**.

Cameras are grouped by feed, each with a feed badge, a health dot, the time of
the last frame, and how many times the view changed today.

Click a camera. The drawer shows the latest snapshot, a strip of the last 10
frames, the smoke score, and the view-change status.

> **Point out the Bosque North camera.** Its view changed — an operator re-aimed
> it. The frame is flagged and **cannot raise a smoke alert**. That matters
> because these are PTZ cameras, and every operator nudge would otherwise look
> like a new scene appearing.

To force the pipeline to run instead of waiting two minutes, use **Settings ›
Demo › Poll all cameras now** a few times (admin only).

---

## 3. A possible-smoke alert (1 min)

Go to **Events**.

You should see an event with a grey **Possible smoke** chip.

> **The important thing is what has *not* happened.** Open the event. The
> drawer says: *"Not dispatched: possible smoke events stay in the dashboard
> until a Torch sensor agrees."* Nobody has been paged. This is the product
> decision the whole prototype exists to demonstrate — a camera alone is not
> enough to wake anyone up.

Also worth showing: the chip has an **icon and a text label**, not just a
colour, because red and orange are hard to distinguish for a lot of people.

---

## 4. Trigger the fire, watch it verify (3 min)

**Settings › Demo › Run fire scenario** (admin only).

This ramps one mock Torch sensor (TS-004) near the Bosque Central camera:
PM2.5 + VOC climbing, then a thermal hotspot.

Go to **Sensors** and watch TS-004 climb from ~12 to over 60 on the smoke index.
Click it to see the sparklines — and note each one has a **"Show readings"**
button that reveals the same data as a table, so the trend is not trapped in a
picture.

It takes **about 60–90 seconds** for the sensor to cross the threshold.

Back on **Events**, the same event now shows a red **Verified** chip and
severity **Critical**. Open it:

* the confirming sensor and its readings;
* the timeline: detected → upgraded to verified → dispatched;
* the reason, in words: *"Sensor TS-004 123 m from the camera: smoke/gas index
  66 ≥ 60"*.

Note the **DEMO** badge. Every record the scenario creates is tagged, and demo
events are dispatched **only to the local test receiver**, never to a real URL.

---

## 5. The dispatch webhook (1 min)

Switch to the terminal running the test receiver:

```
========================================================================
DISPATCH RECEIVED  event=1  delivery=267e0618-854a-487f-be03-39c7ca45e668
  - signature OK
  - timestamp skew 1s OK
{
  "status": "verified",
  "severity": "Critical",
  "confirming_sensor_id": "TS-004",
  "confirmation": "Sensor TS-004 123 m from the camera: smoke/gas index 66 ≥ 60",
  "review_url": "http://127.0.0.1:5173/events/1",
  "note": "Open review_url and sign in to view the frame. This payload contains no imagery.",
  ...
}
========================================================================
```

Three things to point at:

1. **`signature OK`** — HMAC-SHA256 over timestamp + body, so the receiver can
   tell it really came from us and can reject replays.
2. **No image bytes and no credentials** — just a link that requires a login.
3. **Only this event arrived.** The `possible_smoke` event never did.

---

## 6. The operator decision (30 sec)

Back in the event drawer, click **Real** or **False alarm** (needs the operator
or admin role — a viewer sees an explanation instead).

Every click is written to the audit log (**Settings › Audit log**) and feeds the
false-alarm metric on the dashboard, which is one of the kill criteria.

---

## 7. Blind-spot map and the sensor proposal (2 min)

Go to **Map**.

Turn layers on and off in the floating card, top right:

* **camera view cones** — translucent polygons;
* **blind spots** — a **hatched** fill, not just a colour;
* **proposed sensors** — **dashed** orange circles, one per 10-acre sensor.

> Everything on the map is also in the list panel beside it — Cameras, Sensors,
> Events tabs. Selecting from the list centres the map and opens the same
> drawer. That is deliberate: a Mapbox canvas is close to unusable with a
> screen reader, so nothing is map-only.

Then go to **Dashboard** for the headline in text:

> *"Cameras see X% of the corridor. Y sensors cover Z of the N blind acres.
> Hardware cost Y × $299 = $…"*

And the kill-criteria KPIs: frames ingested and failed, view changes,
possible-smoke alerts, how many a human marked false, verified alerts, and
average cost per frame (**$0.00** — the baseline detector makes no API calls).

Download both CSVs from the Dashboard: the proposed sensor placements and
today's kill-criteria numbers.

**Be straight about the caveats** — they are printed on the screen and belong in
the conversation:

* the viewshed is **bare-earth**: no canopy, no buildings, no camera optics;
* headings and fields of view come from config, **not a survey**;
* if the elevation model fell back to synthetic (no network), the page says so
  and the numbers are illustrative only;
* coverage is only meaningful once the **real NMDOT cameras** are ingesting —
  with just the replay cameras it will look very low.

---

## 8. Optional: it is accessible, and that is tested (1 min)

```bash
python scripts/check_contrast.py        # every token pair, both themes
cd web && npm run test:a11y             # axe-core on every screen, both themes
```

Then, in the browser: hit **Tab** on any screen — the first stop is "Skip to
main content". Toggle the theme from the user menu. Both themes are contrast-
checked in CI.

---

## Resetting between runs

```bash
# Stop the scenario but keep the data
curl -X POST http://127.0.0.1:8000/api/admin/demo/fire-scenario/stop \
     -H "X-CSRF-Token: <token>" -b cookies.txt

# Or start completely fresh
rm -rf data/torch.db data/frames && python -m app run
```

(Deleting the database removes user accounts too, so you will be prompted to
create an admin again.)

---

## If something does not work

| Symptom | What to do |
|---|---|
| Map is a grey placeholder | `MAPBOX_TOKEN` is not set, or it is a secret `sk.` token — the API refuses to send those to a browser. Use a public `pk.` token. |
| No events appear | Click **Poll all cameras now** a few times. The detector needs a few frames of history per camera before it will accuse anything. |
| Fire scenario does not verify | Give it 90 seconds. The ramp has to cross the smoke-index threshold (60) first; watch TS-004 on the Sensors screen. |
| NMDOT feed shows unreachable | Expected on a restricted network. `demo_local` replay cameras carry the whole demo. |
| Receiver prints nothing | It only ever receives `verified` and `sensor_only`. A `possible_smoke` event is supposed to produce silence. |
