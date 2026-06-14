# Built-in Playback with Live Effect Preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play the loaded video in-app with audio and live effect/overlay preview, using embedded libmpv — optional, with graceful fallback to today's frame preview.

**Architecture:** A pure `build_preview_vf(settings)` derives an mpv filter chain + properties from the same `ExportSettings` used for export. A guarded `Player` wraps libmpv (via `python-mpv`) rendering into a Tk frame. The preview area toggles Edit mode (canvas + crop box) ⇄ Play mode (mpv). If mpv/libmpv is missing or embedding fails, playback disables itself and the editor keeps working.

**Tech Stack:** Python 3 stdlib + tkinter, `python-mpv` (ctypes wrapper) + native libmpv, ffmpeg (export path unchanged), pytest.

**Spec:** `docs/superpowers/specs/2026-06-14-leike-playback-design.md`

---

## File structure

- **Modify `leike.py`:**
  - Add `build_preview_vf(s)` near the other pure filter helpers (after `_linear_video`, ~line 400).
  - Add a guarded `import mpv` / `HAS_MPV` near the `tkinterdnd2` guard (~line 24).
  - Add a `Player` class (thin libmpv wrapper) above `class App`.
  - In `App`: a preview-area `tk.Frame` for mpv, a transport row, mode-swap + playback methods, and `Space` binding.
- **Create `tests/test_preview_vf.py`:** pure unit tests for `build_preview_vf`.
- **Modify `tests/test_ui_structure.py`:** assert transport controls + `HAS_MPV` exist.
- **Modify packaging:** `Build-exe.bat`, `installer/Leike.iss`, `installer/staging`, `packaging/README-linux.txt`, `README.md`, `.github/workflows/release.yml` (add `python-mpv` to build deps).
- **No change to `build_commands` or any export filter** — verified by leaving `tests/test_build_commands.py` green.

---

## Task 1: Pure `build_preview_vf(settings)` + tests

**Files:**
- Modify: `leike.py` (add function after `_linear_video`, ~line 400)
- Test: `tests/test_preview_vf.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_preview_vf.py`:

```python
# Pure tests for build_preview_vf — no GUI, no mpv.
def make(leike, **kw):
    base = dict(input_path="in.mp4", output_path="out.mp4",
                src_w=1920, src_h=1080, start=2.0, end=8.0)
    base.update(kw)
    return leike["ExportSettings"](**base)


def vf_props(leike, **kw):
    return leike["build_preview_vf"](make(leike, **kw))


def test_empty_settings_minimal(leike):
    vf, props = vf_props(leike)
    assert "crop=" not in vf and "eq=" not in vf
    assert props.get("speed", 1.0) == 1.0


def test_crop_orient_color(leike):
    vf, _ = vf_props(leike, crop=(10, 20, 1280, 720), rotate=90,
                     flip_h=True, brightness=0.2, contrast=1.1, saturation=1.2)
    assert "crop=1280:720:10:20" in vf
    assert "transpose=1" in vf and "hflip" in vf
    assert "eq=brightness=0.200:contrast=1.100:saturation=1.200" in vf


def test_grayscale_denoise_sharpen(leike):
    vf, _ = vf_props(leike, grayscale=True, denoise=True, sharpen=True)
    assert "hue=s=0" in vf and "hqdn3d" in vf and "unsharp" in vf


def test_text_overlay(leike):
    vf, _ = vf_props(leike, text="Hello")
    assert "drawtext=" in vf and "textfile=" in vf


def test_fades_use_absolute_timeline(leike):
    # mpv plays from s.start, so fade st must be source-absolute
    vf, _ = vf_props(leike, start=2.0, end=8.0, fade_in=1.0, fade_out=1.5)
    assert "fade=t=in:st=2.00:d=1.00" in vf
    assert "fade=t=out:st=6.50:d=1.50" in vf


def test_watermark_bridges_movie_source(leike):
    vf, _ = vf_props(leike, watermark_path="logo.png", watermark_pos="br")
    assert "movie=" in vf and "overlay=" in vf


def test_audio_props(leike):
    _, props = vf_props(leike, speed=2.0, volume=1.5, mute=True)
    assert props["speed"] == 2.0
    assert abs(props["volume"] - 150.0) < 0.01      # mpv volume is 0-100(+)
    assert props["mute"] is True


def test_subtitles_use_native_sub_file(leike):
    _, props = vf_props(leike, subtitles_path="subs.srt")
    assert props["sub-file"] == "subs.srt"


def test_non_live_effects_omitted(leike):
    vf, props = vf_props(leike, reverse=True, boomerang=True, stabilize=True,
                         target_size_mb=10.0)
    assert "vidstab" not in vf and "reverse" not in vf
    # scale is omitted too (mpv fits the window)
    assert "scale=" not in vf
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_preview_vf.py -q`
Expected: FAIL — `KeyError: 'build_preview_vf'`.

- [ ] **Step 3: Implement `build_preview_vf`**

Add to `leike.py` after `_linear_video` (reuses the existing pure helpers `_crop_filter`, `_orient_filters`, `_adjust_filters`, `_drawtext_filter`, `_ff_escape_path`):

```python
def build_preview_vf(s):
    """Live-preview filtergraph + mpv properties for ExportSettings s.

    Returns (vf, props):
      vf    - an mpv 'vf' filter-chain string (libavfilter), or "".
      props - dict of mpv properties applied directly: speed, volume, mute,
              and sub-file.

    Only the single-pass, live-previewable subset is included. Reverse,
    boomerang and stabilize are omitted (not live-previewable); scale is
    omitted (mpv fits the video to the window); speed/volume/mute/subs are
    mpv properties (so audio stays in sync) rather than filters.
    """
    chain = (_crop_filter(s) + _orient_filters(s) + _adjust_filters(s)
             + _drawtext_filter(s))

    # Fades, absolute to the source timeline (mpv plays from s.start, so PTS
    # are source-absolute — unlike export, which input-seeks and resets PTS).
    fi = getattr(s, "fade_in", 0.0) or 0.0
    fo = getattr(s, "fade_out", 0.0) or 0.0
    if fi > 0:
        chain.append(f"fade=t=in:st={s.start:.2f}:d={fi:.2f}")
    if fo > 0:
        chain.append(f"fade=t=out:st={max(0.0, s.end - fo):.2f}:d={fo:.2f}")

    vf = ",".join(chain)

    # Watermark image, merged via a lavfi movie source bridge.
    wm = getattr(s, "watermark_path", None)
    if wm:
        pos = {"tl": "10:10", "tr": "W-w-10:10",
               "bl": "10:H-h-10", "br": "W-w-10:H-h-10"}.get(
                   getattr(s, "watermark_pos", "br"), "W-w-10:H-h-10")
        pre = vf if vf else "null"
        vf = (f"{pre}[v];movie='{_ff_escape_path(wm)}'[wm];"
              f"[v][wm]overlay={pos}")

    props = {}
    sp = getattr(s, "speed", 1.0) or 1.0
    if sp != 1.0:
        props["speed"] = sp
    vol = getattr(s, "volume", 1.0)
    if vol != 1.0:
        props["volume"] = vol * 100.0          # mpv volume is a percentage
    if getattr(s, "mute", False):
        props["mute"] = True
    subs = getattr(s, "subtitles_path", None)
    if subs:
        props["sub-file"] = subs
    return vf, props
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_preview_vf.py -q`
Expected: PASS (9 passed). Also run the full suite: `python -m pytest -q` — all green (no export tests affected).

- [ ] **Step 5: Commit**

```bash
git add leike.py tests/test_preview_vf.py
git commit -m "feat(playback): pure build_preview_vf — mpv vf + props from settings"
```

---

## Task 2: mpv import guard + `Player` wrapper

**Files:**
- Modify: `leike.py` (import guard ~line 24; `Player` class above `class App`)
- Test: `tests/test_ui_structure.py`

- [ ] **Step 1: Add the guarded import**

After the `tkinterdnd2` guard in `leike.py` (~line 31), add:

```python
# Embedded playback (python-mpv + libmpv). Optional; the app falls back to the
# frame preview when it (or its native library) is missing.
try:
    import mpv
    HAS_MPV = True
except Exception:
    HAS_MPV = False
```

- [ ] **Step 2: Write the `Player` wrapper**

Add above `class App`. Every mpv touch is guarded so a missing/broken libmpv never propagates:

```python
class Player:
    """Thin, defensive wrapper around an embedded libmpv instance.

    Construction can fail (no libmpv, or embedding unsupported on this
    platform); callers check `.ok`. All methods no-op when not ok.
    """

    def __init__(self, wid):
        self.ok = False
        self.mpv = None
        if not HAS_MPV:
            return
        try:
            self.mpv = mpv.MPV(wid=str(wid), vo="gpu", keep_open="yes",
                               idle="yes", osc=False, input_default_bindings=False)
            self.ok = True
        except Exception:
            self.mpv = None
            self.ok = False

    def load(self, path, start=0.0):
        if not self.ok:
            return
        try:
            self.mpv.play(path)
            self.mpv.wait_until_playing()
            self.mpv.seek(start, reference="absolute")
        except Exception:
            pass

    def set_graph(self, vf, props):
        if not self.ok:
            return
        try:
            for k, v in props.items():
                self.mpv[k] = v
            self.mpv.vf = vf or ""
        except Exception:
            pass

    def set_pause(self, paused):
        if self.ok:
            try:
                self.mpv.pause = bool(paused)
            except Exception:
                pass

    def set_ab_loop(self, a, b):
        if not self.ok:
            return
        try:
            self.mpv["ab-loop-a"] = a if a is not None else "no"
            self.mpv["ab-loop-b"] = b if b is not None else "no"
        except Exception:
            pass

    def seek(self, t):
        if self.ok:
            try:
                self.mpv.seek(t, reference="absolute")
            except Exception:
                pass

    def time_pos(self):
        if not self.ok:
            return None
        try:
            return self.mpv.time_pos
        except Exception:
            return None

    def destroy(self):
        if self.mpv is not None:
            try:
                self.mpv.terminate()
            except Exception:
                pass
        self.mpv = None
        self.ok = False
```

- [ ] **Step 3: Extend the structural test**

In `tests/test_ui_structure.py`, add:

```python
def test_playback_surface_exists(app, leike):
    # mpv is optional; the flag and the Player class always exist.
    assert "HAS_MPV" in leike
    assert "Player" in leike and "build_preview_vf" in leike
    # transport widgets exist regardless of mpv availability
    assert app.play_btn is not None
    assert hasattr(app, "loop_play_var")
```

(These pass after Task 3 wires the widgets; run this test at the end of Task 3.)

- [ ] **Step 4: Verify import + suite still load**

Run: `python -c "import leike"` then `python -m pytest tests/test_preview_vf.py -q`
Expected: import OK (whether or not libmpv is installed); preview tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add leike.py
git commit -m "feat(playback): guarded mpv import + defensive Player wrapper"
```

---

## Task 3: Preview-area mode swap + transport controls

**Files:**
- Modify: `leike.py` (`_build_ui` preview cell + a new `_build_transport`)
- Test: `tests/test_ui_structure.py`

- [ ] **Step 1: Add the mpv render frame to the preview cell**

In `_build_ui`, where the canvas is created (left column, row 0), wrap canvas + an mpv frame in a container so they share the cell. After the canvas setup add:

```python
        # mpv render surface, stacked under the canvas; raised in Play mode.
        self.video_frame = tk.Frame(left, bg=CANVAS_BG,
                                    highlightthickness=1,
                                    highlightbackground=CANVAS_BORDER)
        self.video_frame.grid(row=0, column=0, sticky="nsew")
        self.canvas.tkraise()          # Edit mode is the default
        self.player = None             # created lazily on first play
        self.playing = False
```

- [ ] **Step 2: Build the transport row**

Add a call `self._build_transport(left, row=5)` after the grab button, and the method:

```python
    def _build_transport(self, parent, row):
        bar = ttk.Frame(parent)
        bar.grid(row=row, column=0, sticky="ew", pady=(6, 0))
        self.play_btn = ttk.Button(bar, text="▶  Play", width=10,
                                   command=self.toggle_play, state="disabled")
        self.play_btn.grid(row=0, column=0)
        self.stop_btn = ttk.Button(bar, text="■", width=3,
                                   command=self.stop_play, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(6, 0))
        self.loop_play_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Loop", variable=self.loop_play_var,
                        command=self._apply_loop).grid(row=0, column=2, padx=(10, 0))
        self.play_hint = ttk.Label(bar, text="", foreground=MUTED)
        self.play_hint.grid(row=0, column=3, padx=(10, 0))
        if not HAS_MPV:
            self.play_hint.config(text="Playback needs mpv (libmpv)")
```

- [ ] **Step 3: Enable the play button once a file loads**

In the method that runs after a video opens (where `grab_btn` is enabled), add:

```python
        if HAS_MPV:
            self.play_btn.config(state="normal")
            self.stop_btn.config(state="normal")
```

- [ ] **Step 4: Add stub playback methods (filled in Task 4)**

```python
    def toggle_play(self):
        pass

    def stop_play(self):
        pass

    def _apply_loop(self):
        pass
```

- [ ] **Step 5: Run the structural test**

Run: `python -m pytest tests/test_ui_structure.py -q`
Expected: PASS (the new `test_playback_surface_exists` plus existing tabs test).

- [ ] **Step 6: Commit**

```bash
git add leike.py tests/test_ui_structure.py
git commit -m "feat(playback): preview-area video frame + transport controls"
```

---

## Task 4: Wire playback — play/pause/stop/loop, scrub sync, live effects

**Files:**
- Modify: `leike.py` (playback methods, scrub seek, live re-apply, non-live notes)

> mpv playback cannot run in CI (no display/libmpv), so this task's verification
> is the **manual checklist in Task 6**. Steps here are concrete code; keep each
> commit small.

- [ ] **Step 1: Implement `toggle_play` / Edit↔Play swap**

```python
    def toggle_play(self):
        if not HAS_MPV or not self.input_path:
            return
        if self.player is None:
            self.player = Player(self.video_frame.winfo_id())
            if not self.player.ok:
                self.play_hint.config(text="Playback unavailable on this system")
                self.play_btn.config(state="disabled")
                return
        if not self.playing:
            self._enter_play_mode()
        else:
            self._set_paused(not self._paused)

    def _enter_play_mode(self):
        self.playing = True
        self._paused = False
        self.video_frame.tkraise()
        s = self._settings(self.output_path or "preview.mp4")
        vf, props = build_preview_vf(s)
        self.player.load(self.input_path, start=s.start)
        self.player.set_graph(vf, props)
        self._apply_loop()
        self._update_nonlive_note(s)
        self.player.set_pause(False)
        self.play_btn.config(text="⏸  Pause")
        self._poll_playhead()

    def _set_paused(self, paused):
        self._paused = paused
        self.player.set_pause(paused)
        self.play_btn.config(text="▶  Play" if paused else "⏸  Pause")
```

- [ ] **Step 2: Implement `stop_play` (return to Edit mode)**

```python
    def stop_play(self):
        if not self.playing:
            return
        self.playing = False
        if self.player:
            self.player.set_pause(True)
        self.canvas.tkraise()
        self.play_btn.config(text="▶  Play")
        self.play_hint.config(text="")
        # snap the still preview to the trim start
        self.request_preview(self.start_sec)
```

- [ ] **Step 3: Loop the trim range**

```python
    def _apply_loop(self):
        if not (self.playing and self.player):
            return
        if self.loop_play_var.get():
            self.player.set_ab_loop(self.start_sec, self.end_sec)
        else:
            self.player.set_ab_loop(None, None)
```

(Use the app's existing trim-in/out seconds; if they are named differently,
wire `self.start_sec` / `self.end_sec` to the current trim values.)

- [ ] **Step 4: Drive the scrub bar from mpv time-pos**

```python
    def _poll_playhead(self):
        if not (self.playing and self.player and self.player.ok):
            return
        t = self.player.time_pos()
        if t is not None and self.duration:
            self.scrub_var.set(t)
            self.playhead_label.config(text=fmt_time(t))
            if not self.loop_play_var.get() and t >= self.end_sec:
                self.stop_play()
                return
        self.after(33, self._poll_playhead)   # ~30 Hz
```

- [ ] **Step 5: Seek mpv when the user scrubs during playback**

In `on_scrub`, when playing, seek mpv instead of extracting a frame:

```python
    def on_scrub(self, _v):
        if not self.input_path:
            return
        self.playhead = float(self.scrub_var.get())
        self.playhead_label.config(text=fmt_time(self.playhead))
        if self.playing and self.player:
            self.player.seek(self.playhead)
            return
        if self._scrub_after:
            self.after_cancel(self._scrub_after)
        self._scrub_after = self.after(
            120, lambda: self.request_preview(self.playhead))
```

- [ ] **Step 6: Re-apply the graph live when controls change**

Add a helper and call it (debounced) from the effect/overlay/trim control callbacks (the same callbacks that already call `_update_export_hint`):

```python
    def _refresh_preview_graph(self):
        if not (self.playing and self.player and self.player.ok):
            return
        if self._graph_after:
            self.after_cancel(self._graph_after)
        self._graph_after = self.after(150, self._do_refresh_graph)

    def _do_refresh_graph(self):
        s = self._settings(self.output_path or "preview.mp4")
        vf, props = build_preview_vf(s)
        self.player.set_graph(vf, props)
        self._apply_loop()
        self._update_nonlive_note(s)
```

Initialize `self._graph_after = None` in `__init__`, and append
`self._refresh_preview_graph()` to `_update_export_hint` (single choke point
that effect/overlay controls already trigger).

- [ ] **Step 7: "Not shown in preview" note for non-live effects**

```python
    def _update_nonlive_note(self, s):
        skipped = []
        if getattr(s, "stabilize", False):
            skipped.append("stabilize")
        if getattr(s, "reverse", False):
            skipped.append("reverse")
        if getattr(s, "boomerang", False):
            skipped.append("boomerang")
        self.play_hint.config(
            text=("Not shown in preview: " + ", ".join(skipped)) if skipped else "")
```

- [ ] **Step 8: Bind Space and clean up on close**

In `_bind_shortcuts`: `self.bind("<space>", lambda e: self.toggle_play())`.
In the window-close/`destroy` path: `if self.player: self.player.destroy()`.

- [ ] **Step 9: Compile + run the non-GUI suite**

Run: `python -m py_compile leike.py && python -m pytest -q`
Expected: COMPILE OK; all tests PASS (playback paths aren't exercised by tests).

- [ ] **Step 10: Commit**

```bash
git add leike.py
git commit -m "feat(playback): play/pause/stop/loop, scrub sync, live graph refresh"
```

---

## Task 5: Packaging — bundle libmpv (Windows), deps, docs

**Files:**
- Modify: `Build-exe.bat`, `installer/Leike.iss`, `packaging/README-linux.txt`, `README.md`, `.github/workflows/release.yml`

- [ ] **Step 1: Add `python-mpv` to the source/build deps**

Update the dev note in `README.md` ("Run the tests" / "Rebuild the exe") to
`pip install tkinterdnd2 python-mpv pyinstaller`.

- [ ] **Step 2: Bundle `libmpv-2.dll` into the Windows exe**

In `Build-exe.bat`, add a `--add-binary` for the dll (place a known-good
`libmpv-2.dll` at the repo root or a `vendor/` dir first):

```bat
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name Leike ^
  --icon leike.ico ^
  --add-data "leike.ico;." ^
  --add-binary "libmpv-2.dll;." ^
  --collect-all tkinterdnd2 ^
  leike.py
```

- [ ] **Step 3: Ship the dll in the installer/portable**

The portable zip and the installer stage from the built exe; since the dll is
bundled into the onefile exe (Step 2), no separate staging is needed. Confirm
`Leike.exe` runs playback on a clean machine during Task 6.

- [ ] **Step 4: Document mac/linux libmpv**

In `packaging/README-linux.txt`, add under Notes: "Playback needs libmpv —
`sudo apt install libmpv2` (or your distro's `mpv`/`libmpv` package). Without
it, Leike still works with the frame preview." Add an equivalent line to the
README macOS section (`brew install mpv`).

- [ ] **Step 5: Add `python-mpv` to the CI build deps**

In `.github/workflows/release.yml`, both the macOS and Linux "Install build
deps" steps: `pip install pyinstaller python-mpv`. (libmpv itself is the
user's system package on those platforms; the bundled app falls back if
absent.)

- [ ] **Step 6: Commit**

```bash
git add Build-exe.bat installer/Leike.iss packaging/README-linux.txt README.md .github/workflows/release.yml
git commit -m "build(playback): bundle libmpv on Windows; document mac/linux mpv"
```

---

## Task 6: Manual verification + ship v2.2

**Files:** none (verification), then `installer/Leike.iss` version bump.

- [ ] **Step 1: Build and smoke-test on Windows**

`Build-exe.bat`, then run `dist\Leike.exe`. Verify against the checklist:

- Open a video → **Play** plays with **audio**; **Pause**/**Stop** work.
- Crop a region, rotate/mirror, change brightness/contrast/saturation,
  grayscale, denoise, sharpen → each updates the **playing** picture within
  ~0.2 s.
- Add a text caption and a watermark image → both appear over the video.
- Add an SRT → subtitles render.
- Change speed and volume/mute → playback speed and loudness follow.
- Enable **Loop** → playback loops the trim range; disable → stops at trim end.
- Scrubbing during playback seeks; the playhead tracks during play.
- Enable **stabilize**/**reverse**/**boomerang** → "Not shown in preview" note;
  export still applies them (spot-check one export).
- Rename `libmpv-2.dll` away / run on a machine without it → app still opens,
  edits, and exports; Play is disabled with the mpv hint (fallback works).

- [ ] **Step 2: Confirm the export path is unchanged**

Run `python -m pytest -q` (all green) and export one clip; verify output is
identical in behavior to v2.1.

- [ ] **Step 3: Bump version and ship**

- `installer/Leike.iss`: `#define MyAppVersion "2.2"`.
- Build Windows assets (exe + portable + installer) per the v2.1 process.
- `gh release create v2.2 ...` with the Windows assets + notes; the tag
  triggers CI to attach the mac/linux builds.
- Update the landing page if desired (mention live playback).

- [ ] **Step 4: Finish the development branch**

Announce and use **superpowers:finishing-a-development-branch** to verify
tests, present options, and complete the work.

---

## Notes for the implementer

- **`_settings(out)`** already snapshots every `*_var` into an `ExportSettings`;
  reuse it for the preview (`build_preview_vf(self._settings(...))`) so the
  preview always matches the current UI exactly.
- **Trim seconds:** wire `self.start_sec` / `self.end_sec` to whatever the app
  currently uses for trim in/out (the values feeding `s.start` / `s.end` in
  `_settings`). If those attributes don't exist, compute from the trim vars.
- **mpv `vf` escaping** differs subtly from CLI `-vf`; if a filter errors in
  mpv (caught in `Player.set_graph`), the preview simply shows the prior graph
  — never a crash. Validate the watermark `movie=` bridge first; if libmpv's
  build lacks a filter, drop it from `build_preview_vf` and note it.
- Keep `build_commands` and all `_*_filter` helpers untouched in behavior;
  `build_preview_vf` only *reads* them.
```

