# Leike Feature Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grow Leike from a trim/crop/resize tool into a fast, do-everything-quick video clipper — resizable window, GIF/WebM output, size-targeting, audio controls, transforms (rotate/speed/fade/vertical-fill/boomerang), frame grab, UX upgrades, and power features — without losing its one-panel simplicity.

**Architecture:** Two foundational refactors first: (1) a **resizable, responsive window** with a dynamic preview that re-scales on `<Configure>`, and (2) a pure **`ExportSettings` → `build_commands()`** function that turns the UI state into one or more ffmpeg passes. After that, each feature is a small, unit-tested addition to the builder plus a UI control inside a collapsible "More options" area. Multi-pass features (GIF palette, size-target two-pass, stabilization) reuse one sequential pass-runner with a Cancel button.

**Tech Stack:** Python 3 + tkinter (single file `leike.py`), ffmpeg/ffprobe (child process), PyInstaller + Inno Setup for packaging, pytest for the builder unit tests.

---

## Testing approach (read first)

This is a GUI app with no existing tests. The plan adds **pytest** and unit-tests the one thing worth testing rigorously: the pure `build_commands(settings)` function (UI state → list of ffmpeg arg-lists). Everything UI/encoding-related is verified by **building and running** the app and observing output, because tkinter widgets and real encodes can't be meaningfully unit-tested. Each feature therefore has:
- a **builder change** with concrete code,
- a **unit test** asserting the produced args,
- a **UI control** description, and
- a **manual verification** (an exact ffmpeg-equivalent command + what to look for).

`pip install pytest` once. Run tests with `python -m pytest tests/ -v` from the repo root.

## File structure

- `leike.py` — the app. Will gain: `ExportSettings` dataclass, `build_commands()`, `_s2c/_c2s` coordinate helpers, a collapsible options frame, a process/cancel manager. Keep it single-file (project convention) but section it clearly with comment banners.
- `tests/test_build_commands.py` — unit tests for the command builder (NEW).
- `tests/conftest.py` — loads `leike.py` as a module for testing without launching the GUI (NEW).
- `Build-exe.bat`, `installer/Leike.iss` — version bumps per release; otherwise unchanged.
- `docs/superpowers/plans/2026-06-13-leike-feature-roadmap.md` — this plan.

Each **Phase** below ends in a shippable release (v1.7, v1.8, …) via the existing build+release flow.

---

## Phase 0 — Foundations (ship as v1.7)

### Task 0.1: pytest scaffold that loads leike.py headlessly

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_helpers.py`

- [ ] **Step 1: Write conftest that imports leike.py without running mainloop**

```python
# tests/conftest.py
import os, sys, importlib.util
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.fixture(scope="session")
def leike():
    path = os.path.join(ROOT, "leike.py")
    src = open(path, encoding="utf-8").read().replace("App().mainloop()", "pass")
    ns = {"__file__": path, "__name__": "leike_under_test"}
    exec(compile(src, path, "exec"), ns)
    return ns
```

- [ ] **Step 2: Write tests for existing pure helpers**

```python
# tests/test_helpers.py
def test_even(leike):
    assert leike["even"](721) == 720
    assert leike["even"](720) == 720

def test_fmt_and_parse_roundtrip(leike):
    assert leike["parse_time"]("1:02:03.250") == 3723.25
    assert leike["fmt_time"](3723.25) == "1:02:03.250"
```

- [ ] **Step 3: Run and verify pass**

Run: `python -m pytest tests/ -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_helpers.py
git commit -m "test: add pytest scaffold that loads leike.py headlessly"
```

### Task 0.2: Resizable window + responsive preview with offset mapping

**Why:** The preview currently sizes the canvas to the frame and maps crop coords as `x*scale` from canvas origin (0,0). A resizable window means the canvas fills its pane and the image is drawn **scaled-to-fit and centered** at an offset `(ox, oy)`. All crop math must route through two helpers so the offset lives in one place.

**Files:**
- Modify: `leike.py` — `App.__init__` (resizable/min size), `_build_ui` (grid weights, canvas fills pane), add `_recompute_display`, `_s2c`, `_c2s`; update `redraw`, `_handle_points`, `on_canvas_down/drag`, `request_preview`/`_extract_frame`, `_draw_drop_hint`, and `load_path` (stop fixing canvas size).

- [ ] **Step 1: Make the window resizable with a sensible minimum**

In `__init__`, replace `self.resizable(False, False)` with:

```python
self.resizable(True, True)
self.minsize(900, 600)
```

- [ ] **Step 2: Add coordinate helpers and display recompute**

Add to the class:

```python
def _recompute_display(self):
    """Fit the source frame into the current canvas, centred (letterboxed)."""
    cw = max(self.canvas.winfo_width(), 1)
    ch = max(self.canvas.winfo_height(), 1)
    if not self.src_w or not self.src_h:
        self.scale, self.disp_w, self.disp_h = 1.0, cw, ch
        self.off_x, self.off_y = 0, 0
        return
    self.scale = min(cw / self.src_w, ch / self.src_h)
    self.disp_w = max(1, int(self.src_w * self.scale))
    self.disp_h = max(1, int(self.src_h * self.scale))
    self.off_x = (cw - self.disp_w) // 2
    self.off_y = (ch - self.disp_h) // 2

def _s2c(self, x, y):   # source px -> canvas px
    return self.off_x + x * self.scale, self.off_y + y * self.scale

def _c2s(self, ex, ey):  # canvas px -> source px (clamped to frame)
    x = min(max((ex - self.off_x) / self.scale, 0), self.src_w)
    y = min(max((ey - self.off_y) / self.scale, 0), self.src_h)
    return x, y
```

Initialize `self.off_x = self.off_y = 0` in `__init__` alongside the other display state.

- [ ] **Step 3: Let the canvas fill its pane and react to resize**

In `_build_ui`, make the left/preview column and the canvas expand. After creating `self.canvas`, add:

```python
root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)
left.rowconfigure(2, weight=1); left.columnconfigure(0, weight=1)
self.canvas.grid(row=2, column=0, sticky="nsew", pady=6)
self.canvas.bind("<Configure>", self._on_canvas_resize)
```

Add the debounced resize handler:

```python
def _on_canvas_resize(self, _e):
    if self._resize_after:
        self.after_cancel(self._resize_after)
    self._recompute_display()
    self.redraw()  # instant re-letterbox of the cached image
    if self.input_path:
        self._resize_after = self.after(
            150, lambda: self.request_preview(self.playhead))
```

Initialize `self._resize_after = None` in `__init__`.

- [ ] **Step 4: Route every crop coordinate through the helpers**

In `redraw`, replace `x0, y0 = x*self.scale, y*self.scale` and the `(x+w)*self.scale` lines with `self._s2c(...)`; draw the preview image at `(self.off_x, self.off_y)` via `c.create_image(self.off_x, self.off_y, anchor="nw", image=self._preview_img)`. In `on_canvas_down`/`on_canvas_drag`, replace `ev.x/self.scale` with `self._c2s(ev.x, ev.y)`. Hit-testing in `on_canvas_down` already compares canvas px to handle px — recompute handle positions via `self._s2c`. In `_draw_drop_hint`, center the text at `(cw//2, ch//2)` using current canvas size. In `load_path`, **remove** the `self.canvas.config(width=..., height=...)` line and call `self._recompute_display()` then `self.redraw()` after computing `disp_w/disp_h` is no longer needed (the recompute does it).

- [ ] **Step 5: Build and verify by running**

Run: `python leike.py`
Verify: window resizes; the video preview stays centered and scales to fit; the crop box tracks correctly under the cursor at multiple window sizes; drag-to-draw, move, and corner-resize all land where expected; releasing a resize re-renders a crisp frame.

- [ ] **Step 6: Commit**

```bash
git add leike.py
git commit -m "feat: resizable window with responsive, centred preview"
```

### Task 0.3: Collapsible "More options" area (room to grow)

**Why:** Many new controls are coming. Keep the main panel clean by putting everything beyond the core crop/trim/export into a toggleable section, and make the right controls column scrollable so it survives a short window.

**Files:**
- Modify: `leike.py` — `_build_ui` (wrap the right panel in a scrollable frame; add a `More options ▸` toggle that shows/hides an `self.advanced` frame).

- [ ] **Step 1: Add a scrollable container for the controls column**

```python
def _scrollable(self, parent):
    canvas = tk.Canvas(parent, bg=BASE_BG, highlightthickness=0, width=300)
    sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.grid(row=0, column=0, sticky="ns"); sb.grid(row=0, column=1, sticky="ns")
    return inner
```

Use `right = self._scrollable(right_container)` and build the panels into `right`.

- [ ] **Step 2: Add the toggle + advanced frame**

```python
self.adv_shown = tk.BooleanVar(value=False)
self.adv_btn = ttk.Button(right, text="More options  ▸", command=self._toggle_adv)
self.adv_btn.grid(...)
self.advanced = ttk.Frame(right)   # feature panels get added here in later tasks
def _toggle_adv(self):
    if self.adv_shown.get():
        self.advanced.grid_remove(); self.adv_btn.config(text="More options  ▸")
    else:
        self.advanced.grid(); self.adv_btn.config(text="More options  ▾")
    self.adv_shown.set(not self.adv_shown.get())
```

- [ ] **Step 3: Build, run, verify**

Run: `python leike.py` — toggling "More options" shows/hides the (currently empty) advanced frame; a short window scrolls the controls.

- [ ] **Step 4: Commit**

```bash
git add leike.py && git commit -m "feat: scrollable controls + collapsible More options"
```

### Task 0.4: Extract a pure `ExportSettings` → `build_commands()`

**Why:** This is the spine of every later feature. It must reproduce today's behavior exactly first (crop, scale cap, CRF, libx264/yuv420p/faststart/AAC), returning a **list of passes** (today: one) so multi-pass features slot in later.

**Files:**
- Modify: `leike.py` — add `ExportSettings` dataclass and `build_commands()`; rewrite `export()` to populate settings and call it; rewrite `_run_export` to run a list of passes.
- Create/extend: `tests/test_build_commands.py`

- [ ] **Step 1: Write failing tests for the baseline command**

```python
# tests/test_build_commands.py
def make(leike, **kw):
    S = leike["ExportSettings"]
    base = dict(input_path="in.mp4", output_path="out.mp4", src_w=1920, src_h=1080,
                start=1.0, end=4.0, crop=None, scale_cap=None, crf=20, fmt="mp4")
    base.update(kw)
    return S(**base)

def test_baseline_single_pass(leike):
    cmds = leike["build_commands"](make(leike))
    assert len(cmds) == 1
    c = cmds[0]
    assert c[0].endswith("ffmpeg") or c[0] == "ffmpeg"
    assert "-ss" in c and "1.000" in c
    assert "-t" in c and "3.000" in c
    j = " ".join(c)
    assert "format=yuv420p" in j
    assert "libx264" in j and "-crf 20" in j
    assert "+faststart" in j and "aac" in j

def test_crop_and_scale(leike):
    cmds = leike["build_commands"](make(leike, crop=(10, 20, 1280, 720), scale_cap=1280))
    j = " ".join(cmds[0])
    assert "crop=1280:720:10:20" in j
    assert "scale=1280:720" in j  # 1280 longest side already <= cap, but cropped 1280x720 stays
```

Run: `python -m pytest tests/test_build_commands.py -v` → FAIL (`ExportSettings`/`build_commands` undefined).

- [ ] **Step 2: Add the dataclass and builder (baseline parity)**

```python
from dataclasses import dataclass, field

@dataclass
class ExportSettings:
    input_path: str; output_path: str
    src_w: int; src_h: int
    start: float; end: float
    crop: tuple | None = None          # (x, y, w, h) source px
    scale_cap: int | None = None       # longest-side cap
    crf: int = 20
    fmt: str = "mp4"                   # mp4 | gif | webm | mp3 (later phases)

def _even(n): return int(round(n)) - (int(round(n)) % 2)

def _out_dims(s):
    w, h = (s.crop[2], s.crop[3]) if s.crop else (s.src_w, s.src_h)
    w, h = _even(w), _even(h)
    if s.scale_cap and max(w, h) > s.scale_cap:
        f = s.scale_cap / max(w, h)
        w, h = _even(w * f), _even(h * f)
    return max(2, w), max(2, h)

def _video_filters(s):
    chain = []
    if s.crop:
        x, y, w, h = s.crop
        chain.append(f"crop={_even(w)}:{_even(h)}:{_even(x)}:{_even(y)}")
    ow, oh = _out_dims(s)
    cw = _even(s.crop[2]) if s.crop else _even(s.src_w)
    ch = _even(s.crop[3]) if s.crop else _even(s.src_h)
    if (ow, oh) != (cw, ch):
        chain.append(f"scale={ow}:{oh}:flags=lanczos")
    chain.append("format=yuv420p")
    return chain

def build_commands(s):
    dur = max(0.001, s.end - s.start)
    vf = ",".join(_video_filters(s))
    cmd = [FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path,
           "-t", f"{dur:.3f}", "-vf", vf,
           "-c:v", "libx264", "-preset", "medium", "-crf", str(s.crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", s.output_path]
    return [cmd]
```

- [ ] **Step 3: Run tests → PASS.** `python -m pytest tests/test_build_commands.py -v`

- [ ] **Step 4: Rewrite `export()` to use settings, and `_run_export` to run passes**

`export()` builds an `ExportSettings` from the widgets (start/end via `self.start_t/self.end_t`, crop via `self.crop`, scale_cap via the dropdown, crf via the slider) and calls `build_commands`. `_run_export(cmds, dur, out)` loops the passes:

```python
def _run_export(self, cmds, dur, out):
    self._cancelled = False
    last_err = ""
    for i, cmd in enumerate(cmds):
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
        self.export_proc = proc
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        for line in proc.stderr:
            if self._cancelled: proc.kill(); break
            m = time_re.search(line)
            if m:
                t = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
                frac = (i + min(1.0, t/dur)) / len(cmds)
                self.after(0, lambda p=frac*100: self.progress.config(value=p))
            elif line.strip(): last_err = line.strip()
        if proc.wait() != 0 and not self._cancelled:
            return self.after(0, lambda: self._export_done(False, last_err, out))
    self.after(0, lambda: self._export_done(not self._cancelled, last_err, out))
```

- [ ] **Step 5: Build, run, export a real clip; confirm identical output to v1.6**

Run: `python leike.py`, trim+crop+downscale, export. Then `ffprobe` the result: H.264, yuv420p, correct dims/duration, AAC, faststart. Matches prior behavior.

- [ ] **Step 6: Commit**

```bash
git add leike.py tests/test_build_commands.py
git commit -m "refactor: pure ExportSettings -> build_commands(), multi-pass runner"
```

### Task 0.5: Cancel button + status

**Files:** Modify `leike.py` — add a Cancel button next to Export; set `self._cancelled = True` and kill `self.export_proc`.

- [ ] **Step 1:** Add `self._cancelled = False` and `self.export_proc = None` in `__init__`. Add a Cancel `ttk.Button` (disabled until export starts) that does:

```python
def cancel_export(self):
    self._cancelled = True
    if self.export_proc and self.export_proc.poll() is None:
        self.export_proc.kill()
    self.status_label.config(text="Cancelled.")
```

Enable Cancel when export starts, disable Export; reverse in `_export_done`.

- [ ] **Step 2:** Run, start an export of a long clip, click Cancel → ffmpeg dies, partial file is removed (`os.remove(out)` on cancel if exists), UI returns to ready.

- [ ] **Step 3: Commit, then ship v1.7**

```bash
git add leike.py && git commit -m "feat: cancellable exports"
```
Bump `installer/Leike.iss` to 1.7, run `Build-exe.bat` + `Build-installer.bat` + portable zip, `gh release create v1.7`.

---

## Phase 1 — Encode speed & smarts (ship as v1.8)

### Task 1.1: Lossless fast-trim (auto `-c copy`)

**Builder change:** when the only operation is a trim (no crop, no scale_cap, fmt mp4, no transforms/audio changes — all the later flags default off), emit a stream-copy command instead of re-encoding.

```python
def _is_passthrough(s):
    return (s.crop is None and s.scale_cap is None and s.fmt == "mp4"
            and not getattr(s, "rotate", 0) and not getattr(s, "flip_h", False)
            and not getattr(s, "flip_v", False) and getattr(s, "speed", 1.0) == 1.0
            and not getattr(s, "fade_in", 0) and not getattr(s, "fade_out", 0)
            and getattr(s, "fill_mode", "crop") in ("crop", "none")
            and not getattr(s, "boomerang", False) and not getattr(s, "reverse", False)
            and getattr(s, "loop", 0) == 0 and not getattr(s, "mute", False)
            and getattr(s, "volume", 1.0) == 1.0 and not getattr(s, "audio_only", False))

# in build_commands, before the re-encode path:
if _is_passthrough(s):
    dur = max(0.001, s.end - s.start)
    return [[FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path,
             "-t", f"{dur:.3f}", "-c", "copy", "-movflags", "+faststart",
             s.output_path]]
```

- [ ] **Test:** `test_passthrough_is_copy` — baseline trim-only settings produce `-c copy` and no `-vf`.
- [ ] **UI:** a checkbox "Fast trim (no re-encode)" in advanced, default **auto** — show a small "⚡ fast" hint label when the current settings qualify. (Note in tooltip: cuts land on the nearest keyframe.)
- [ ] **Verify:** trim-only export finishes near-instantly; `ffprobe` shows the original codec copied; duration ≈ requested (keyframe-aligned).
- [ ] **Commit:** `feat: lossless fast-trim via stream copy`.

### Task 1.2: Hardware encoding toggle (NVENC)

**Builder change:** add `hw: bool = False`. When true and fmt is mp4, swap the encoder:

```python
venc = (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(s.crf)] if s.hw
        else ["-c:v", "libx264", "-preset", "medium", "-crf", str(s.crf)])
```

- [ ] **Test:** `hw=True` yields `h264_nvenc` and `-cq`; `hw=False` yields `libx264` + `-crf`.
- [ ] **UI:** checkbox "Fast encode (GPU)" in advanced. Detect availability once at startup: run `ffmpeg -hide_banner -encoders` and enable the checkbox only if `h264_nvenc` is listed; otherwise disable with a "(no NVENC GPU found)" note.
- [ ] **Verify:** toggle on, export a large crop+scale clip; it encodes much faster; `ffprobe` shows H.264; plays fine.
- [ ] **Commit + ship v1.8** (version bump, builds, release).

---

## Phase 2 — Output formats (ship as v1.9)

### Task 2.1: GIF export (two-pass palette)

**Builder change:** `fmt == "gif"` returns **two** passes — palette generation to a temp PNG, then render — using a shared filter prefix (crop/scale/fps).

```python
GIF_FPS = 15
def _gif_passes(s, palette):
    pre = [f for f in _video_filters(s) if not f.startswith("format=")]
    pre.append(f"fps={GIF_FPS}")
    pre = ",".join(pre)
    dur = max(0.001, s.end - s.start)
    p1 = [FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}",
          "-vf", pre + ",palettegen=stats_mode=diff", palette]
    p2 = [FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}",
          "-i", palette, "-lavfi", pre + " [x];[x][1:v] paletteuse=dither=bayer",
          s.output_path]
    return [p1, p2]
```

In `build_commands`, when `s.fmt == "gif"`, allocate a temp palette path (`tempfile`) and return `_gif_passes(s, palette)`. Output extension `.gif`. No audio.

- [ ] **Test:** `fmt="gif"` → 2 passes; pass 1 has `palettegen`, pass 2 has `paletteuse`; neither has `-c:a`.
- [ ] **UI:** an "Output format" combobox (MP4 / GIF / WebM) at the top of the Export panel. When GIF: hide CRF/audio, show an FPS spinner (default 15) and reuse the downscale dropdown (GIFs should be small). Change the save dialog's default extension to match.
- [ ] **Verify:** export a 3s crop as GIF; opens and loops; file size reasonable; colors clean (palette working).
- [ ] **Commit:** `feat: GIF export with palettegen/paletteuse`.

### Task 2.2: WebM (VP9) export

**Builder change:** `fmt == "webm"` → libvpx-vp9 video + libopus audio, CRF-based.

```python
# fmt == "webm":
return [[FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}",
         "-vf", ",".join(_video_filters(s)),
         "-c:v", "libvpx-vp9", "-crf", str(s.crf), "-b:v", "0",
         "-c:a", "libopus", "-b:a", "128k", s.output_path]]
```

- [ ] **Test:** `fmt="webm"` → `libvpx-vp9` + `libopus`, single pass.
- [ ] **UI:** the format combobox gains WebM; `.webm` extension.
- [ ] **Verify:** export plays in a browser/VLC; smaller than the H.264 equivalent at similar quality.
- [ ] **Commit + ship v1.9.**

---

## Phase 3 — Fit-under-a-size-limit (ship as v1.10)

### Task 3.1: Target file size (two-pass bitrate)

**Builder change:** `target_size_mb: float | None = None`. When set (mp4/webm), compute total bitrate from duration and do a real two-pass encode.

```python
def _size_target_passes(s):
    dur = max(0.001, s.end - s.start)
    total_kbit = (s.target_size_mb * 8192) / dur          # kbit/s budget
    audio_kbit = 0 if s.audio_only else 128
    vbit = max(64, int(total_kbit - audio_kbit) * 0.97)   # 3% mux headroom
    vf = ",".join(_video_filters(s))
    common = ["-ss", f"{s.start:.3f}", "-i", s.input_path, "-t", f"{dur:.3f}", "-vf", vf,
              "-c:v", "libx264", "-b:v", f"{vbit}k"]
    log = s.output_path + ".2pass"
    p1 = [FFMPEG, "-y", *common, "-pass", "1", "-passlogfile", log,
          "-an", "-f", "mp4", os.devnull if os.name != "nt" else "NUL"]
    p2 = [FFMPEG, "-y", *common, "-pass", "2", "-passlogfile", log,
          "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", s.output_path]
    return [p1, p2]
```

Call this when `s.target_size_mb` and `s.fmt == "mp4"`.

- [ ] **Test:** with `target_size_mb=10, end-start=20` → two passes, `-pass 1`/`-pass 2`, `-b:v` ≈ `((10*8192)/20 - 128)*0.97` kbit. Assert the computed `-b:v` value within ±1k.
- [ ] **UI:** in advanced, a "Target size" row: a combobox of presets (Off / 8 MB / 10 MB / 25 MB / Custom…) with a numeric entry for Custom. When set, it overrides CRF (grey CRF out and show "size-targeted").
- [ ] **Verify:** target 10 MB on a 20s clip → output within ~5% of 10 MB; clean up the `.2pass` log files after.
- [ ] **Commit + ship v1.10.**

---

## Phase 4 — Audio controls (ship as v1.11)

### Task 4.1: Mute, volume, extract-audio

**Builder change:** add `mute: bool=False`, `volume: float=1.0`, `audio_only: bool=False`.
- mute → replace `-c:a aac …` with `-an`.
- volume → prepend audio filter `-af "volume={v}"` (skip if 1.0 or muted).
- audio_only → `fmt` effectively mp3: `-vn -c:a libmp3lame -q:a 2 out.mp3`, ignore video filters.

```python
def _audio_args(s):
    if s.mute: return ["-an"]
    args = ["-c:a", "aac", "-b:a", "128k"]
    if s.volume != 1.0: args = ["-af", f"volume={s.volume:.3f}"] + args
    return args
# audio_only path (highest precedence) in build_commands:
if s.audio_only:
    return [[FFMPEG, "-y", "-ss", f"{s.start:.3f}", "-i", s.input_path,
             "-t", f"{max(0.001,s.end-s.start):.3f}", "-vn",
             "-c:a", "libmp3lame", "-q:a", "2", s.output_path]]
```

Swap the hard-coded `-c:a aac -b:a 128k` in the mp4 path for `*_audio_args(s)`.

- [ ] **Tests:** `mute=True` → `-an`, no `aac`; `volume=1.5` → `volume=1.500`; `audio_only=True` → `-vn` + `libmp3lame`, `.mp3`.
- [ ] **UI:** an Audio panel in advanced — "Mute" checkbox, a volume slider (0–200%), and an "Export audio only (MP3)" checkbox that switches the output to `.mp3` and hides video options.
- [ ] **Verify:** muted export has no audio stream; 150% is audibly louder; audio-only produces a playable MP3 of the trimmed range.
- [ ] **Commit + ship v1.11.**

---

## Phase 5 — Transforms (ship across v1.12–v1.14)

All of these extend `_video_filters` (or move to a `filter_complex` when needed). Add fields to `ExportSettings`: `rotate:int=0`, `flip_h:bool=False`, `flip_v:bool=False`, `speed:float=1.0`, `fade_in:float=0.0`, `fade_out:float=0.0`, `fill_mode:str="crop"`, `target_aspect:float|None=None`, `boomerang:bool=False`, `reverse:bool=False`, `loop:int=0`.

### Task 5.1: Rotate / flip (v1.12)

**Builder:** insert before `format=` —
```python
if s.rotate == 90:  chain.append("transpose=1")
elif s.rotate == 180: chain.append("transpose=1,transpose=1")
elif s.rotate == 270: chain.append("transpose=2")
if s.flip_h: chain.append("hflip")
if s.flip_v: chain.append("vflip")
```
- [ ] **Test:** rotate=90 → `transpose=1`; flip_h → `hflip`.
- [ ] **UI:** four small buttons (⟲ ⟳, mirror-H, mirror-V) in a Transform panel; rotation is cumulative mod 360.
- [ ] **Verify:** rotate a clip 90°, export, dims swapped, orientation correct; preview reflects rotation (apply the same transform to the preview frame extraction filter so the canvas shows it).
- [ ] **Commit.**

### Task 5.2: Speed — slow-mo / timelapse (v1.12)

**Builder:** speed multiplies playback. Video: `setpts={1/speed}*PTS`. Audio: `atempo` (chain to stay in 0.5–2.0 range per stage).
```python
if s.speed != 1.0:
    chain.append(f"setpts={1.0/s.speed:.4f}*PTS")
def _atempo_chain(speed):
    out, r = [], speed
    while r > 2.0: out.append("atempo=2.0"); r /= 2.0
    while r < 0.5: out.append("atempo=0.5"); r *= 2.0
    out.append(f"atempo={r:.4f}"); return ",".join(out)
```
When speed≠1 and not muted, set `-af` to the atempo chain (combined with volume if both). Trim duration math: `-t` still applies to **input** seconds (before setpts), so output length = dur/speed automatically.
- [ ] **Test:** speed=2.0 → `setpts=0.5000*PTS` and audio `atempo=2.0`; speed=0.25 → `setpts=4.0000*PTS` and `atempo=0.5,atempo=0.5`.
- [ ] **UI:** a speed slider/combobox (0.25× / 0.5× / 1× / 2× / 4× + custom) in Transform.
- [ ] **Verify:** 0.5× is slow-mo with pitch-preserved audio; 4× is a timelapse.
- [ ] **Commit + ship v1.12.**

### Task 5.3: Fade in/out (v1.13)

**Builder:** needs the clip duration to place the out-fade. With `dur = end-start` (output dur = dur/speed):
```python
od = (s.end - s.start) / (s.speed or 1.0)
if s.fade_in:  chain.append(f"fade=t=in:st=0:d={s.fade_in:.2f}")
if s.fade_out: chain.append(f"fade=t=out:st={max(0,od-s.fade_out):.2f}:d={s.fade_out:.2f}")
# audio afade similarly when not muted
```
- [ ] **Test:** fade_in=0.5 → `fade=t=in:st=0:d=0.50`; fade_out=1.0 on a 3s/1x clip → `fade=t=out:st=2.00:d=1.00`.
- [ ] **UI:** two small numeric entries (fade in / fade out seconds) in Transform.
- [ ] **Verify:** exported clip fades from/to black; audio fades too.
- [ ] **Commit.**

### Task 5.4: Blurred-background aspect fill (v1.13)

**Builder:** when `fill_mode == "blur_pad"` and `target_aspect` set, replace the scale step with a `filter_complex` that scales a blurred, zoomed copy to the target canvas and overlays the contained video centered. Compute target canvas `(W,H)` from the source (after crop) and `target_aspect`, capped by `scale_cap`.
```python
def _blur_pad_complex(s, W, H):
    return (f"[0:v]split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},gblur=sigma=20[bgb];"
            f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
```
Use `-filter_complex` + `-map "[v]"`. This branch is mutually exclusive with the plain `scale` path; crop still applies first (feed `[0:v]` through crop by prepending `crop=...` inside the `[fg]`/`[bg]` split source, or pre-crop with a `-vf` is simpler: apply crop via an initial `crop` on `[0:v]` before split).
- [ ] **Test:** fill_mode="blur_pad", target_aspect=9/16, src 1920x1080 → complex contains `gblur`, `overlay`, and the computed `W:H` (e.g. 1080x1920 when capped at 1080-wide).
- [ ] **UI:** in the Crop panel, when an aspect preset is chosen, add a radio: "Crop to fit" (today) vs "Fit with blurred bg". The latter sets `fill_mode="blur_pad"`, `target_aspect` from the preset, and disables the draggable crop box.
- [ ] **Verify:** a landscape clip → 9:16 output with the video centered over a blurred fill; no content cropped.
- [ ] **Commit + ship v1.13.**

### Task 5.5: Boomerang / reverse / loop (v1.14)

**Builder:** these reorder/duplicate frames via `filter_complex`.
- reverse: `[0:v]reverse[v]` (+ `areverse` for audio).
- boomerang: `[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]` (audio usually dropped or also mirrored).
- loop: append `,loop=loop={n}:size=...` is awkward for video; simpler to use `-stream_loop` on input for whole-clip loops, or concat N times. Use concat for small N.
- [ ] **Test:** reverse=True → `reverse`; boomerang=True → `concat=n=2`.
- [ ] **UI:** Transform panel radio: None / Reverse / Boomerang, and a "Loop ×N" spinner.
- [ ] **Verify:** boomerang plays forward then backward seamlessly; reverse plays backward; loop ×3 triples length.
- [ ] **Commit + ship v1.14.**

---

## Phase 6 — Frame grab (ship as v1.15)

### Task 6.1: Export current frame as image

**Not part of `build_commands`** (it's an instant single-shot). Add a method:
```python
def grab_frame(self):
    out = filedialog.asksaveasfilename(defaultextension=".png",
        filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
    if not out: return
    vf = ",".join(f for f in _video_filters(self._settings()) if f != "format=yuv420p")
    cmd = [FFMPEG, "-y", "-ss", f"{self.playhead:.3f}", "-i", self.input_path,
           "-frames:v", "1", "-update", "1"] + (["-vf", vf] if vf else []) + [out]
    run_capture(cmd)
```
- [ ] **Test:** builder helper `_video_filters` already covered; add a small test that a crop produces a `crop=` in the grab filter (factor the filter list out so it's testable).
- [ ] **UI:** a "Grab frame" button near the preview that saves the current playhead frame (with crop/transform applied).
- [ ] **Verify:** grabbed PNG matches the preview (cropped/rotated) at the current time.
- [ ] **Commit + ship v1.15.**

---

## Phase 7 — UX multipliers (ship across v1.16–v1.18)

### Task 7.1: Remember settings & output folder (v1.16)
- [ ] Persist a small JSON (`%LOCALAPPDATA%/Leike/config.json`) with last output dir, last format, downscale, CRF, advanced-toggle state; load on startup, save on export. Test the load/save round-trip of the config dict (pure function). Commit.

### Task 7.2: Filmstrip + audio waveform under the trim slider (v1.17)
- [ ] Generate ~12 thumbnails (`ffmpeg ... -vf fps,scale,tile`) and an audio waveform PNG (`showwavespic`) once per load (background thread), draw them as the slider's backdrop so cuts land on visible action/sound. Manual verify. Commit + ship v1.17.

### Task 7.3: Real preview playback (v1.18)
- [ ] Add a Play button that launches `ffplay` on the current trim range (`ffplay -ss start -t dur -autoexit -window_title "Leike preview" input`) as a child process, with the same crop/transform `-vf`. Note in plan: ffplay ships with the gyan build and is bundled the same way as ffmpeg (add `ffplay.exe` to the portable bundle + installer staging + `tool_path("ffplay")`). Manual verify playback + audio. Commit + ship v1.18. (This is the heaviest UX item; keep it a subprocess — do **not** attempt an in-canvas player.)

### Task 7.4: Keyboard shortcuts (v1.18)
- [ ] Bind: Space = play preview, `[`/`]` = set start/end to playhead, Ctrl+E = export, Esc = cancel, arrows = nudge playhead. Manual verify. Commit.

---

## Phase 8 — Power features (ship across v1.19+)

Each is an independent, optional addition; do them in this order, one release each, same pattern (builder change + test + UI in advanced + manual verify + release):

- [ ] **8.1 Join/concat** multiple clips (`concat` demuxer; new multi-file picker + ordered list UI). Larger — consider its own plan.
- [ ] **8.2 Watermark/logo overlay** (`overlay` a chosen PNG at a corner with padding + opacity).
- [ ] **8.3 Text/title** (`drawtext` with a bundled font; position + size + color from the brand palette).
- [ ] **8.4 Burn-in subtitles** (`subtitles=file.srt`; SRT file picker).
- [ ] **8.5 Color adjust** (`eq=brightness:contrast:saturation`, plus a Grayscale toggle `hue=s=0`).
- [ ] **8.6 Stabilization** (two-pass `vidstabdetect` → `vidstabtransform`; warn it's slow; reuse the multi-pass runner).
- [ ] **8.7 Denoise / sharpen** (`hqdn3d`, `unsharp`).
- [ ] **8.8 Batch mode** (apply the current recipe to a queue of input files; a new file-list UI + loop over `build_commands` with auto-named outputs). Larger — consider its own plan.

---

## Self-review notes

- **Spec coverage:** every feature from the brainstorm maps to a task — GIF (2.1), size-target (3.1), audio mute/extract (4.1), blurred vertical fill (5.4), fast-trim (1.1), plus Tier-2/3 and UX. Window resize is Task 0.2. ✔
- **Type consistency:** `ExportSettings` field names (`crop`, `scale_cap`, `fmt`, `rotate`, `flip_h/v`, `speed`, `fade_in/out`, `fill_mode`, `target_aspect`, `boomerang`, `reverse`, `loop`, `mute`, `volume`, `audio_only`, `hw`, `target_size_mb`) are introduced once and reused verbatim in later tasks. `build_commands` always returns `list[list[str]]`. ✔
- **Ordering rationale:** foundation (resize + builder + cancel) precedes all features so each feature is a small, tested delta; passthrough/hwaccel precede formats so the encode path is settled; transforms come after formats since they share the filter chain that formats also touch. ✔
- **Risk flags:** 5.4 (blur-pad filter_complex interaction with crop) and 7.3 (ffplay bundling + size) are the two to watch; 8.1/8.8 may each deserve their own plan.
