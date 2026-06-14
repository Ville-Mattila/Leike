# Leike — H.265 (HEVC) + AV1 Export — Design

**Date:** 2026-06-14
**Status:** Approved design (pending user review of this spec)
**Ships as:** v2.4

## Goal

Let users export modern, high-efficiency codecs — **H.265 (HEVC)** and **AV1** —
from the same one-click flow as H.264, reusing the existing format dropdown, CRF
slider, and GPU toggle. Also surface a clear note whenever a **target file size**
is set on a format that can't use it.

## Context

`leike.py` (single file) already maps a `fmt` value through the whole export
pipeline:

- `FORMATS` (list of `(label, key)`): `MP4 (H.264)→mp4`, `GIF→gif`,
  `WebM (VP9)→webm`.
- `_venc(s)` returns the video-encoder args: `h264_nvenc` (GPU) or `libx264`
  (software), chosen by `s.hw`.
- `build_commands(s)` branches on `fmt`: `gif` (palette two-pass), `webm`
  (libvpx-vp9), else the **mp4 re-encode path** (which calls `_venc`). Special
  paths: `_is_passthrough` (lossless `-c copy`, H.264 mp4 only), `_size_target_
  passes` (two-pass libx264 to hit MB), `_stabilize_passes` (vidstab; pass-2
  calls `_venc`).
- `build_concat_commands(clips, g)` (combine) has its own `webm` vs mp4 branch;
  the mp4 branch calls `_venc(g)`.
- The save dialog / ext mapping (`_start_single`, `_start_batch`,
  `_start_combine`) maps `fmt` → `.mp4`/`.gif`/`.webm`.
- `_detect_nvenc()` checks only that `h264_nvenc` is compiled in (a weak proxy —
  it does not confirm a working GPU).
- The bundled ffmpeg (gyan GPLv3 full, shipped in the installer/portable) has
  `libx265`, `hevc_nvenc`, `libsvtav1`, `av1_nvenc`, `libaom-av1`.

The key insight: **H.265 and AV1 are video *codecs* inside the existing MP4
container**, so they slot into the `fmt`-driven pipeline as two new `fmt` values
that route through the MP4 re-encode path, with a codec-aware `_venc`.

## Decisions (resolved during brainstorming)

1. **Surfacing:** two new entries in the existing format dropdown — `MP4 (H.265)`
   and `MP4 (AV1)` — both `.mp4`. No new controls.
2. **AV1 encoder:** `av1_nvenc` when the GPU toggle is on **and** a startup probe
   confirms the GPU supports it; otherwise software `libsvtav1`. (H.265 uses the
   GPU toggle directly — `hevc_nvenc` works on virtually all NVENC GPUs.)
3. **Target file-size** stays **H.264-only**; when set on any other format it is
   skipped and a note says so (this also covers the pre-existing silent skips for
   GIF / WebM / MP3).
4. **AV1 container = MP4** (not WebM), for consistency with H.265.
5. **CRF slider is shared** across H.264/H.265/AV1 (same numeric value to each
   encoder's `-crf`/`-cq`).

## Architecture

### New `fmt` values + labels

```python
FORMATS = [
    ("MP4 (H.264)", "mp4"),
    ("MP4 (H.265)", "hevc"),
    ("MP4 (AV1)",   "av1"),
    ("GIF",         "gif"),
    ("WebM (VP9)",  "webm"),
]
```

`hevc` and `av1` are MP4-container formats → `.mp4` extension everywhere `fmt`
maps to an extension.

### Codec-aware `_venc(s)`

`_venc` switches on `s.fmt` and `s.hw`, with the AV1 GPU path gated on a new
capability flag `s.av1_nvenc` (set by the App from the startup probe):

```python
def _venc(s):
    """Video encoder args for the MP4-container formats (h264/hevc/av1),
    choosing GPU (NVENC) vs software per s.hw and s.av1_nvenc."""
    crf = str(s.crf)
    fmt = getattr(s, "fmt", "mp4")
    hw = getattr(s, "hw", False)
    if fmt == "hevc":
        if hw:
            return ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", crf,
                    "-tag:v", "hvc1"]
        return ["-c:v", "libx265", "-preset", "medium", "-crf", crf,
                "-tag:v", "hvc1"]
    if fmt == "av1":
        if hw and getattr(s, "av1_nvenc", False):
            return ["-c:v", "av1_nvenc", "-preset", "p5", "-cq", crf]
        return ["-c:v", "libsvtav1", "-preset", "6", "-crf", crf]
    # h264 (fmt == "mp4")
    if hw:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", crf]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", crf]
```

`-tag:v hvc1` makes H.265 MP4s play in QuickTime / Windows / Apple. Output stays
8-bit `yuv420p` (added by the mp4 path) + `+faststart`, AAC audio — unchanged.

### Startup probe for `av1_nvenc`

`av1_nvenc` is always *listed* in the gyan build but only *works* on Ada
(RTX 40-series). A one-time real test-encode confirms hardware support:

```python
def _probe_encoder(name):
    """True if ffmpeg can actually encode one frame with `name` (real GPU
    capability check, not just 'is it compiled in')."""
    null = "NUL" if os.name == "nt" else "/dev/null"
    try:
        r = run_capture([FFMPEG, "-hide_banner", "-f", "lavfi",
                         "-i", "color=black:s=64x64:d=0.1",
                         "-c:v", name, "-f", "null", null])
        return r.returncode == 0
    except OSError:
        return False
```

App sets `self.has_av1_nvenc = _probe_encoder("av1_nvenc")` at startup (alongside
`_detect_nvenc`), and `_settings()` passes it into `ExportSettings.av1_nvenc`.

### `ExportSettings` change

Add one field: `av1_nvenc: bool = False` (the App-detected capability). `fmt`
already exists and now accepts `"hevc"`/`"av1"`. `hw` and `crf` unchanged.

### Pipeline touch points for `hevc`/`av1`

- **`build_commands`**: `hevc`/`av1` fall through to the existing `else` (mp4)
  re-encode path automatically (it calls `_venc`). The target-size guard becomes
  H.264-only: `if s.target_size_mb and s.fmt == "mp4": return _size_target_passes(s)`
  — so H.265/AV1 use the CRF path (target-size skipped).
- **`_is_passthrough`**: already requires `s.fmt == "mp4"`, so H.265/AV1 always
  re-encode (correct) — no change.
- **`_inputs(s)`** (watermark 2nd input): broaden `s.fmt in ("mp4", "webm")` to
  include `"hevc"`, `"av1"` so the watermark overlay works for them.
- **`_stabilize_passes`**: pass-2 already calls `_venc(s)` → codec-aware for
  free; for `hevc` the `hvc1` tag flows through. No change.
- **Combine (`_start_combine`)**: allow `hevc`/`av1` (don't coerce to mp4); the
  mp4 branch in `build_concat_commands` calls `_venc(g)` → codec-aware for free.
  Update the allowed set + ext + save-dialog filetypes to include H.265/AV1.
- **Ext / save dialogs** (`_start_single`, `_start_batch`, `_start_combine`):
  `hevc`/`av1` → `.mp4`.
- **`_on_format_change`**: `hevc`/`av1` aren't `gif`, so the existing `else`
  branch shows the CRF/quality row (correct) — no special-casing needed.

### Target-size "not supported" note

Today target-size is silently ignored unless `fmt == "mp4"` (H.264). Surface it:
extend the export hint so that **whenever a target size is set and the format
isn't MP4 (H.264)**, a note appears, e.g.:

> *Target size applies to MP4 (H.264) — ignored for this format.*

This fires for `gif`, `webm`, `hevc`, `av1`, and audio-only (MP3). It updates on
format change and on target-size change (the existing `_on_format_change` /
target-size handlers call the hint refresher). Export behaviour is otherwise
unchanged — the note is informational; the export still runs (CRF/native path).

## Error handling

- AV1 GPU never hard-fails for lack of hardware: the probe gates `av1_nvenc`, and
  the fallback is `libsvtav1`. If the probe is wrong on some exotic GPU, the
  worst case is a single failed export surfaced by the existing
  `_export_done(False, err, …)` path (same as any encoder error today).
- H.265 via `hevc_nvenc` on a non-NVIDIA machine fails the same way `h264_nvenc`
  does today (pre-existing GPU-toggle behaviour, not new).

## Testing (pytest, pure layer)

- `_venc(s)` for every combination → exact args:
  - `mp4` + hw/sw → `h264_nvenc -cq` / `libx264 -crf`.
  - `hevc` + hw/sw → `hevc_nvenc … -tag:v hvc1` / `libx265 … -tag:v hvc1`.
  - `av1` + (hw & av1_nvenc) → `av1_nvenc -cq`; `av1` + hw-but-not-capable →
    `libsvtav1`; `av1` + sw → `libsvtav1 -preset 6 -crf`.
- `build_commands` for `fmt="hevc"`/`"av1"`: single pass, MP4 container, the
  right `-c:v`, `+faststart`, AAC, output ends `.mp4`; target-size set on
  `hevc`/`av1` does **not** invoke the two-pass libx264 path.
- A target-size-note helper (pure predicate: `target_size_supported(fmt)` →
  True only for `"mp4"`), unit-tested, drives the UI hint.
- `_probe_encoder` and real H.265/AV1 encodes are **run-verified**: build a
  synthetic clip, export H.265 and AV1, ffprobe the outputs (codec = `hevc` /
  `av1`, plays, `.mp4`).

## Out of scope (v2.4)

- 10-bit / HDR output (stay 8-bit yuv420p for compatibility).
- AV1/H.265 two-pass target-size (target-size stays H.264).
- "WebM (AV1)" as a separate entry.
- Per-codec CRF defaults (shared slider value).
