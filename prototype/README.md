# Standalone prototype

`torch-camera-fusion.html` is a single self-contained HTML file — open it in a
browser, no server and no install. It exists so the concept can be shown to
someone who is not going to run `./scripts/run.sh`.

**What it is:** a UI prototype of the Camera Fusion module with mock state. Four
screens (Map, Events, Cameras, Dashboard) using the real Torch design tokens,
light and dark. Press **Run fire scenario** to watch a camera-only alert become
verified and dispatch; **Reset** puts it back.

**What it is not:** there is no detector, no fusion engine, no webhook and no
database behind it. The real system is the rest of this repository.

Everything it shows is taken from an actual run rather than invented:

* the camera thumbnails are the replay frames from `data/replay/`, embedded as
  data URIs, including the real smoke plume and the detector's real bounding box;
* the NMDOT feed is shown failing with the real `403 Forbidden`, because a
  broken feed that silently disappears is the worst failure mode;
* the Bosque North camera is flagged view-changed with alerts suppressed;
* the coverage and cost figures are the ones the blind-spot job computed on
  23 Sep, with the "replay cameras only" caveat attached.

The only external request is the Manrope webfont from Google Fonts; it falls
back to a system stack offline.

Regenerate the embedded frames with `python scripts/make_fixtures.py` if the
replay fixtures change.
