# Architecture

## Block diagram

```mermaid
flowchart TB
    subgraph SOURCES["Camera sources — add one with a config block"]
        NM["NMDOT public JSON<br/>+ snapshot URLs"]
        AX["Axis / Hikvision / Dahua<br/>snapshot URL"]
        RT["RTSP NVR<br/>(customer site)"]
        HL["HLS .m3u8"]
        LF["Local folder<br/>(replay / offline demo)"]
        VK["Verkada<br/>(stub)"]
    end

    subgraph ADAPTERS["feeds/ — FeedAdapter registry"]
        direction LR
        A1["nmdot"]
        A2["snapshot_url"]
        A3["rtsp"]
        A4["hls"]
        A5["local_folder"]
        A6["verkada"]
    end

    GUARD{{"SSRF guard + image intake<br/>scheme allowlist · private/metadata IP block<br/>redirect re-check · size cap · magic bytes<br/>Pillow pixel cap · EXIF strip · re-encode"}}

    subgraph PIPE["Pipeline — never learns where a frame came from"]
        ING["Ingest worker<br/>store JPEG + SHA-256 row"]
        VC["View-change detector<br/>pHash + SSIM vs reference<br/>PTZ move ⇒ no smoke alert"]
        DET["Smoke detector<br/>BaselineDetector (CPU, no weights)<br/>optional ONNX slot"]
        LLM["VisionLLMEscalation<br/>off by default · strict JSON<br/>spend cap · can only nudge score"]
    end

    subgraph SENSE["Torch sensors"]
        MOCK["MockSensorSource<br/>+ fire scenario"]
        TAPI["TorchApiSensorSource<br/>(stub, TODOs)"]
    end

    FUSE{{"Fusion engine"}}

    PS["possible_smoke<br/>dashboard only"]
    VF["verified<br/>camera + sensor agree"]
    SO["sensor_only<br/>no camera corroboration"]

    DISP["Dispatch webhook<br/>HMAC-SHA256 · timestamp + event id<br/>HTTPS only · link, never imagery"]

    subgraph GEO["Blind-spot analysis"]
        DEM["DEM<br/>AWS Terrain Tiles<br/>cached + checksummed"]
        VS["Viewshed per camera<br/>cone × range × line of sight"]
        PL["Greedy sensor placement<br/>10 acres / ~113 m each"]
    end

    UI["Vue 3 + Naive UI + Mapbox<br/>Map · Events · Sensors · Cameras<br/>Dashboard · Settings"]
    DB[("SQLite")]

    NM --> A1
    AX --> A2
    RT --> A3
    HL --> A4
    LF --> A5
    VK --> A6

    A1 & A2 & A3 & A4 & A5 & A6 --> GUARD
    GUARD -->|"JPEG bytes only"| ING
    ING --> VC --> DET --> LLM --> FUSE
    MOCK & TAPI --> FUSE

    FUSE --> PS
    FUSE --> VF
    FUSE --> SO
    VF --> DISP
    SO --> DISP
    PS -.->|"never dispatched"| DISP

    DEM --> VS --> PL --> UI
    FUSE --> DB --> UI
    ING --> DB

    classDef rule fill:#ffe2dc,stroke:#a91612,color:#a91612
    classDef muted fill:#f2f5f5,stroke:#7c8d90,color:#2e3638
    class PS,VF,SO rule
    class VK,TAPI muted
```

## The same thing in plain text

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

## Why the boundaries sit where they do

**The adapter boundary is the whole point.** `FeedAdapter` returns JPEG bytes
and nothing else. Ingest, view-change, detection, fusion and the UI have no
idea whether a frame came from a state DOT's public API, an RTSP camera behind
a customer's firewall, or a folder on disk. That is what makes "new feed = one
file plus a config block" true rather than aspirational, and
`tests/test_fake_adapter_flow.py` enforces it by driving an invented feed type
end to end without touching the pipeline.

**Every byte from a camera crosses one guarded doorway.** No adapter fetches
anything itself: they all call `safe_fetch` and `normalise_to_jpeg`. A feed is
untrusted input — a hostile camera name, a redirect to the cloud metadata
service, a 4 GB "JPEG", a decompression bomb — and a single choke point means a
fix applies to all six adapters at once.

**Fusion is the product decision, isolated in one module.** `possible_smoke`
never leaves the dashboard; only `verified` and `sensor_only` dispatch. That
rule lives in `should_dispatch()`, is re-asserted in the dispatcher, and is
covered by tests, because it is the thing that must not drift.

**The sensor source is an interface, not an assumption.** Fusion consumes
`SensorReading` objects. Swapping `MockSensorSource` for the real Torch API is
one class, with no change to fusion, the schema or the UI.
