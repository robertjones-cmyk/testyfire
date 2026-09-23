# Accessibility

Target: **WCAG 2.2 AA**.

This document says what was tested, how, what passed, and — in a named list at
the end — what is still wrong.

---

## Deliberate departures from the real Torch app

Two things in the public Torch app block users, and the prototype does **not**
copy them:

| Torch app today | This prototype | Why |
|---|---|---|
| `<html lang="">` | `<html lang="en">` | An empty `lang` leaves screen readers guessing the language, which mangles pronunciation. |
| `maximum-scale=1, user-scalable=no` | `width=device-width, initial-scale=1` | Blocking zoom fails WCAG 1.4.4 outright and hurts anyone with low vision. |

Both are one-line fixes that would be worth making in the real app.

---

## Colour and contrast

Every colour in the system is a token in `web/src/styles/theme.css`.
`scripts/check_contrast.py` parses that file, resolves `var()` chains, converts
OKLCH to sRGB, and checks **42 foreground/background pairs across both themes**
against 4.5:1 for normal text and 3:1 for large text and UI components. **It
fails CI on any pair below the bar.**

```bash
python scripts/check_contrast.py --verbose
```

Current result: **42/42 pass in both themes.**

Things the checker forced us to fix or avoid, measured rather than assumed:

* **Brand orange fails as body text on white** — 3.10:1. Links and orange text
  in light mode use `--color-brand-600` (**5.11:1**). Brand orange is fine as
  text in dark mode (**5.39:1**) and fine anywhere as a non-text element.
* **Status colours fail as text on white** — success 2.8:1, warning 2.4:1. Text
  uses darker variants (`--color-success-text` **7.22:1**, `--color-warning-text`
  **7.36:1**, `--color-error-text` **7.49:1**); the raw hues are used only for
  fills, icons and map marks.
* **Input borders needed darkening.** Gray-200 is 1.6:1 and gray-400 only
  2.72:1 — both under the 3:1 required for a UI component. A
  `--color-gray-450` token was added at **3.19:1 on white**. The checker caught
  this; it was not noticed by eye.
* **`--color-text-tertiary`-style greys are never used for text.** Anything
  around 2:1 is decoration or a disabled state only.
* **Dark mode is checked separately**, because several tokens swap and a pair
  that passes in light mode can fail in dark.

### Colour is never the only signal

* **Status chips** carry an icon *and* a text label — "Possible smoke" (grey,
  question-circle), "Verified" (red, check-shield), "Sensor only" (amber, sensor
  icon). Chip text uses the dark 600/700 shades so it clears 4.5:1 **on the
  tinted chip background**, which is the surface that actually matters.
* **The blind-spot map layer is a hatch pattern**, not a colour wash.
* **Proposed sensors are dashed outlines.**
* **Sensor map markers carry a glyph** (`•` nominal, `~` elevated, `!` alarm) as
  well as a colour.
* **Feed health** is a dot *plus* the words "Reachable" / "Unreachable".
* **The map has a legend**, and the blind-spot summary is shown as a sentence of
  text, not only as a layer.

---

## Keyboard and focus

* Everything works keyboard-only: sidebar, tables, filters, drawers, dialogs,
  map layer toggles, buttons. Table rows are focusable and respond to Enter and
  Space.
* **"Skip to main content"** is the first element in the tab order on every
  screen.
* **Visible focus ring everywhere**: 2px, drawn as a double `box-shadow` so it
  reads against both the element and the page, at ≥3:1. No CSS reset removes
  it.
* **Drawers and dialogs** move focus in when opened, trap it while open, close
  on Esc, and **return focus to the element that opened them** (the Events
  table tracks the triggering row explicitly).
* The idle-timeout dialog is an `alertdialog`, focuses the safe action ("Stay
  signed in"), and treats Esc as *extend* rather than *log out*.
* Tab order follows the visual order. No keyboard traps.

---

## The map

Mapbox canvases are close to unusable with a screen reader, so the map is never
the only route to anything:

* **A synced list panel sits beside the map** with tabs for Cameras, Sensors and
  Events, containing the same items. Selecting one centres the map *and* opens
  the same drawer. Anything you can do on the map you can do from the list.
* The map container is a `role="region"` labelled "Map of cameras, sensors and
  events".
* **Mapbox's own keyboard pan/zoom stays on.**
* Zoom buttons are enlarged from Mapbox's 29px to **44×44**, with a visible
  focus ring.
* Map markers are real `<button>` elements with `aria-label`s.
* **The blind-spot summary is also plain text** on both the Map and the
  Dashboard.
* If `MAPBOX_TOKEN` is missing the map degrades to a labelled panel explaining
  the situation — and says that everything is also in the list.

---

## Screen readers

* Semantic HTML first: real `<button>`, `<nav>`, `<main>`, `<table>` with
  `<th scope>`, headings in order, `<dl>` for fact lists, `<fieldset>`/`<legend>`
  for the layer toggles. ARIA only where markup cannot express it.
* **New events are announced** through an `aria-live` region: `polite` for
  Possible smoke and Warning, `assertive` (`role="alert"`) only for Verified and
  Critical. **The 2-minute frame refresh is never announced**, and neither is
  the first load.
* **Camera images have useful alt text**, generated from the actual state, e.g.
  *"Camera Bosque Central, 5:42 PM, possible smoke detected in upper left, score
  0.72"* — and the same sentence appears as a visible `<figcaption>`, so the
  bounding box is not the only carrier of that information.
* **Sparklines have a text equivalent**: a visually-hidden summary sentence plus
  a **"Show readings"** toggle that reveals the same series as a real table.
* Decorative icons are `aria-hidden="true"`; icon-only controls have
  `aria-label`s.
* Form fields have **visible labels** (never placeholder-only), errors in text
  beside the field, linked with `aria-describedby` and marked `aria-invalid`.
* The document title updates on navigation so the current screen is announced.

---

## Motion, zoom and timing

* **`prefers-reduced-motion` is respected**: transitions are reduced globally,
  and the map jumps rather than flying when selecting an item.
* No flashing content. **No auto-playing sound** — there is no alert sound at
  all in this prototype, so there is nothing to opt out of.
* The layout works at **200% zoom and at 320px width** without losing content:
  the map stacks under the list, the sidebar becomes a horizontal strip, and
  there is no horizontal page scroll (asserted in the test suite).
* **"Pause live updates"** stops polling entirely, so an auto-refresh can never
  move the row a keyboard user is working on. When paused, the UI says so.
* The **session-timeout warning** is announced, appears 2 minutes before the
  cut-off, and can be extended from the keyboard.

---

## Automated tests

```bash
python scripts/check_contrast.py     # 42 token pairs, both themes
cd web && npm run test:a11y          # axe-core via Playwright
```

**axe-core runs on every screen in both themes** — Login, Map, Events, Sensors,
Cameras, Dashboard, Settings — plus the Events drawer in its open state. CI
fails on any `serious` or `critical` violation.

Current result: **20/20 tests pass.**

### Three real defects this suite caught

Worth recording, because none was visible by eye and two broke the app outright:

1. **The login fields had no accessible label — and did not render at all.**
   Naive UI puts a bare `id` on its *wrapper div*, so `<label for="login-email">`
   pointed at a non-form element and the input was unlabelled. Fixed by passing
   the id through `input-props` so it lands on the real `<input>`. The same
   pattern was wrong on every filter control; those now use `aria-labelledby`,
   and the filterable select's internal search input is labelled through
   `input-props`.
2. **Every Naive UI component that does colour maths was throwing.** Our tokens
   are authored in `oklch()`, which Naive UI's colour library cannot parse — it
   threw "Invalid color value oklch(...)" and killed the render, which is *why*
   the login inputs were missing. Tokens are now converted to `rgb()` before
   being handed to `themeOverrides`, using the same maths as the contrast
   checker.
3. **The Dashboard's metrics table was not keyboard-scrollable.** Ten columns
   scroll horizontally, and the scroll container was not focusable
   (`scrollable-region-focusable`, WCAG 2.1.1) — a keyboard user simply could
   not reach the right-hand columns. Scrollable regions are now made focusable
   and labelled automatically.

The Mapbox canvas itself is excluded from the scan (it is third-party and not
keyboard-reachable by nature); the synced list panel that duplicates its
contents **is** scanned, which is the part users actually need.

Structural assertions in the same suite:

* `lang="en"` is set and the viewport does not block zoom;
* the skip link is the first focusable element and works;
* no horizontal scrolling at 320px;
* status chips always carry text, never colour alone;
* live updates can be paused.

### Lighthouse

Target: **accessibility ≥ 95**. Run it against a built app:

```bash
cd web && npm run build && cd .. && python -m app run
npx lighthouse http://127.0.0.1:8000/events --only-categories=accessibility --view
```

*Not yet run on this build* — Lighthouse fetches its own resources at runtime
and the build machine's network was restricted. The axe-core suite covers
substantially the same rule set and is the gate in CI; run Lighthouse once on a
normal network to confirm the score.

---

## Manual checklist

Automation catches maybe 40% of accessibility problems. These must be done by
hand before anyone calls this done, and none has been done yet:

### Keyboard-only walkthrough of the demo script
- [ ] Unplug the mouse. Run all of `demo.md` start to finish.
- [ ] Log in, reach every screen from the sidebar.
- [ ] Open a camera drawer, move through the frame strip, close with Esc,
      confirm focus returns to the card you opened it from.
- [ ] Filter the Events table, open an event, mark it Real, close.
- [ ] Toggle every map layer, select an item from each list tab.
- [ ] Trigger the fire scenario and dismiss the resulting announcement.

### Screen reader pass (VoiceOver on macOS, or NVDA on Windows)
- [ ] **Login**: is the form announced as a form, are labels and errors read?
- [ ] **Events**: are table headers announced with each cell, are status chips
      read as text?
- [ ] **Event drawer**: is it announced as a dialog, is the image alt text
      useful, can the sensor readings table be reached?
- [ ] Does a new **Verified** event interrupt appropriately, and does a
      possible-smoke one *not*?

### Zoom and reflow
- [ ] 200% browser zoom on every screen: nothing clipped, nothing lost.
- [ ] 320px wide: the map stacks under the list, no horizontal scroll.
- [ ] 400% zoom on Events — the hardest case, because of the table.

---

## Known gaps

Honest list.

1. **No screen-reader pass has been done.** The markup is built for it and axe
   is clean, but nobody has listened to it with VoiceOver or NVDA. This is the
   biggest gap.
2. **No Lighthouse run on this build** (see above). The axe-core suite passes,
   which covers most of what Lighthouse's accessibility category checks.
3. **Naive UI components are trusted, not audited.** They are used in their
   accessible modes and axe finds no serious violations, but the library's
   internals — particularly the data table's focus handling at 400% zoom — have
   not been examined by hand.
4. **The Mapbox canvas is excluded from the axe scan.** Mitigated by the synced
   list panel, but it means the map itself is unverified.
5. **The 400% zoom case is untested.** 200% and 320px are handled; 400% on the
   Events table is likely the first thing to break.
6. **No high-contrast / forced-colors mode support.** `prefers-contrast` and
   Windows High Contrast are not handled.
7. **Announcement wording is not user-tested.** The live-region messages read
   sensibly but no screen-reader user has told us whether they are useful or
   annoying at volume.
8. **The theme toggle lives in the user menu**, which is two interactions deep.
   Fine, but not obvious.
9. **No reduced-data or offline messaging** beyond the map fallback.
