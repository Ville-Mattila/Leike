# Leike Multi-File (Combine + Batch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent file-list column with a Combine/Batch toggle so the app can join multiple clips into one file or export many files through one recipe, without changing the single-file editing experience.

**Architecture:** Replace the single `input_path` with a `Clip` list whose *active* clip is what the editor edits (trim + crop are per-file; everything else is one global recipe). **Batch** loops the existing pure `build_commands()` once per clip; **Combine** adds one new pure `build_concat_commands()` that normalizes each clip to a blurred-fill canvas and joins them with the `concat` filter. Both reuse a refactored, resilient pass-runner.

**Tech Stack:** Python 3 + tkinter (single file `leike.py`), ffmpeg (child process), pytest for the pure builder/helper layer.

**Spec:** `docs/superpowers/specs/2026-06-14-leike-multifile-design.md`

---

## Testing approach (read first)

This GUI app tests only its **pure layer** (functions that take data and return
ffmpeg args / values), exactly like the existing `tests/test_build_commands.py`
and `tests/test_preview_vf.py`. The headless `leike` fixture in
`tests/conftest.py` `exec`s `leike.py` into a namespace and exposes its
module-level names (`leike["build_commands"]`, `leike["ExportSettings"]`, …) —
it does **not** instantiate `App`, so methods that read tkinter widgets cannot be
unit-tested and are verified by **building and running** instead.

New pure functions (unit-tested): `clip_from_info`, `_combine_target`,
`_concat_filtergraph`, `build_concat_commands`, `_batch_out_name`.
New `App` methods (run-verified): `_add_clips`, `_select_clip`, `_commit_active`,
the file-list UI, `_settings_for_clip`, `_run_passes`, `_run_batch`,
`_start_single/_start_batch/_start_combine`.

Run tests from the repo root: `python -m pytest tests/ -q`. The suite is
currently **60 passed**; each phase adds to it.

## File structure

- `leike.py` — the app (single file, project convention). Gains: a `Clip`
  dataclass and `clip_from_info()` near `ExportSettings` (~line 198); the combine
  builders (`_combine_target`, `_concat_filtergraph`, `build_concat_commands`)
  and `_batch_out_name()` near `build_commands` (~line 679); `self.clips/active/
  mode` state in `__init__`; the file-list column in `_build_ui`; clip
  select/commit/add methods; a refactored `_run_passes` plus `_run_batch`; and an
  `export()` that branches into single / batch / combine.
- `tests/test_multifile.py` — NEW: unit tests for every pure function above.
- `installer/Leike.iss` — version bump to 2.3 (Phase C).
- `README.md` — a feature bullet for Combine/Batch (Phase C).

Each **Phase** ends in a working, runnable app. Phase C ships **v2.3**.

---

## Phase A — Foundation: file-list column + Clip model

### Task A1: `Clip` dataclass + `clip_from_info()` (pure)

**Files:**
- Modify: `leike.py` (add after the `ExportSettings` dataclass, ~line 239)
- Create: `tests/test_multifile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_multifile.py
def test_clip_from_info_spans_whole_file(leike):
    info = {"w": 1920, "h": 1080, "dur": 12.5, "rotation": 90,
            "fps": 30000 / 1001, "has_audio": False}
    c = leike["clip_from_info"]("a.mp4", info)
    assert c.path == "a.mp4"
    assert c.src_w == 1920 and c.src_h == 1080
    assert c.dur == 12.5
    assert c.start == 0.0 and c.end == 12.5   # trim spans whole file
    assert c.crop is None
    assert c.has_audio is False
    assert c.rotation == 90

def test_clip_from_info_defaults_fps_when_missing(leike):
    c = leike["clip_from_info"]("a.mp4", {"w": 640, "h": 480, "dur": 3.0})
    assert c.fps == 30.0
    assert c.has_audio is True
```

- [ ] **Step 2: Run it — expect failure**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: FAIL (`KeyError: 'clip_from_info'`).

- [ ] **Step 3: Add the dataclass + helper**

In `leike.py`, immediately after the `ExportSettings` class (before
`def _out_dims`), add:

```python
@dataclass
class Clip:
    """One file in the multi-file list. Trim (start/end) and crop are per-file;
    every other setting is the shared global recipe taken from the widgets."""
    path: str
    src_w: int
    src_h: int
    dur: float
    rotation: int = 0
    fps: float = 30.0
    has_audio: bool = True
    start: float = 0.0
    end: float = 0.0
    crop: tuple | None = None       # (x, y, w, h) source px, or None


def clip_from_info(path, info):
    """Build a Clip from a probe() info dict; trim spans the whole file."""
    dur = float(info["dur"])
    return Clip(
        path=path,
        src_w=int(info["w"]), src_h=int(info["h"]), dur=dur,
        rotation=int(info.get("rotation", 0) or 0),
        fps=float(info.get("fps") or 30.0),
        has_audio=bool(info.get("has_audio", True)),
        start=0.0, end=dur, crop=None)
```

(`dataclass` is already imported at the top of `leike.py`.)

- [ ] **Step 4: Run it — expect pass**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add leike.py tests/test_multifile.py
git commit -m "feat: Clip dataclass + clip_from_info for multi-file"
```

---

### Task A2: clip-list state + select / commit / add (single-file still works)

**Why:** Route the existing single-file editor through an active clip in a list,
so opening a file appends a `Clip` and editing writes trim+crop back to it. No
list UI yet (added in A3); the editor shows the most-recently-added clip.

**Files:**
- Modify: `leike.py` — `__init__` (~line 925), `load_path` (~line 1981),
  `open_file` (~line 1969), add `_add_clips`, `_select_clip`, `_commit_active`.

- [ ] **Step 1: Add clip-list state to `__init__`**

In `__init__`, in the `# --- source video state ---` block (after
`self.input_path = None`, ~line 926), add:

```python
        self.clips = []        # list[Clip]; the multi-file list
        self.active = -1       # index of the clip in the editor, or -1
        self.mode = "combine"  # "combine" | "batch" (only matters with 2+ clips)
```

- [ ] **Step 2: Add `_add_clips`, `_select_clip`, `_commit_active`**

Add these three methods to `App` (place them just above `load_path`):

```python
    def _add_clips(self, paths):
        """Probe and append each path as a Clip; select the last one added."""
        added = 0
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            info = self.probe(p)
            if not info:
                self.status_label.config(
                    text=f"Skipped (not a video): {os.path.basename(p)}")
                continue
            self.clips.append(clip_from_info(p, info))
            added += 1
        if added:
            self._select_clip(len(self.clips) - 1)
        return added

    def _commit_active(self):
        """Write the editor's current trim+crop back into the active Clip."""
        if not (0 <= self.active < len(self.clips)):
            return
        self.commit_times()        # parse the start/end entries -> start_t/end_t
        c = self.clips[self.active]
        c.start, c.end = self.start_t, self.end_t
        c.crop = tuple(self.crop) if self.crop else None

    def _select_clip(self, i):
        """Load clip i into the editor (saving the current clip first)."""
        if not (0 <= i < len(self.clips)):
            return
        if self.active != i:
            self._commit_active()
        self.stop_play()
        self.active = i
        c = self.clips[i]
        self.input_path = c.path
        self.src_w, self.src_h, self.duration = c.src_w, c.src_h, c.dur
        self.has_audio = c.has_audio
        bits = [f"{c.src_w}x{c.src_h}", fmt_time(c.dur)]
        if c.fps:
            bits.append(f"{c.fps:g} fps")
        self.file_label.config(
            text=f"{os.path.basename(c.path)}   ({', '.join(bits)})")
        self._set_audio_enabled(c.has_audio)
        self._recompute_display()
        self.crop = list(c.crop) if c.crop else None
        self.aspect = None
        self.aspect_var.set(ASPECTS[0][0])
        self.start_t, self.end_t, self.playhead = c.start, c.end, c.start
        self.start_var.set(fmt_time(c.start))
        self.end_var.set(fmt_time(c.end))
        self.scrub.config(to=max(c.dur, 0.001))
        self.scrub_var.set(c.start)
        self.export_btn.config(state="normal")
        self.grab_btn.config(state="normal")
        if HAS_MPV:
            self.play_btn.config(state="normal")
            self.stop_btn.config(state="normal")
        self.update_labels()
        self.request_preview(c.start)
        self._build_filmstrip()
```

- [ ] **Step 3: Route `load_path` and `open_file` through `_add_clips`**

Replace the body of `load_path` (keep the signature) with a thin wrapper, and
make `open_file` accept multiple files. Replace `open_file` (~line 1969) and
`load_path` (~line 1981) with:

```python
    def open_file(self):
        paths = filedialog.askopenfilenames(
            title="Open video(s)",
            filetypes=[
                ("Video files",
                 "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.mpg *.mpeg"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._add_clips(list(paths))

    def load_path(self, path):
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return
        if self._add_clips([path]) == 0:
            messagebox.showerror("Error", "Could not read this file as a video.")
```

- [ ] **Step 4: Make drag-drop append every dropped file**

`on_drop` (~line 1960) currently loads a single path. Replace its body with one
that splits the (possibly multi-file) drop and appends all videos:

```python
    def on_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if paths:
            self._add_clips(list(paths))
```

- [ ] **Step 5: Build and verify by running**

Run: `python leike.py`
Verify: Open a single video — it appears in the editor; crop/trim/scrub/play all
work as before. Open a **second** video — the editor switches to it (the new
active clip). Switch back is not possible yet (no list UI) — that arrives in A3.
Drag-drop a file works. Export still exports the current (active) clip.

- [ ] **Step 6: Run the test suite (no regressions)**

Run: `python -m pytest tests/ -q`
Expected: all green (still 62 — A1 added 2).

- [ ] **Step 7: Commit**

```bash
git add leike.py
git commit -m "refactor: route single-file editing through an active Clip in a list"
```

---

### Task A3: file-list column UI (toggle + list + add/remove/reorder)

**Why:** Make the clip list visible and interactive: a far-left column with the
Combine/Batch toggle, a reorderable list, and Open/Remove/↑/↓ controls.

**Files:**
- Modify: `leike.py` — `_build_ui` (insert the column at body col 0, shift
  preview→col 1 and tabs→col 2), `__init__` (`minsize`), add `_build_file_list`,
  `_refresh_file_list`, `_on_list_select`, `_remove_clip`, `_move_clip`,
  `_set_mode`, `_update_multi_ui`, `_update_export_button`.

- [ ] **Step 1: Bump the minimum window width**

In `__init__` (~line 918) change:

```python
        self.minsize(900, 600)
```
to
```python
        self.minsize(1060, 600)
```

- [ ] **Step 2: Insert the file-list column in `_build_ui`**

In `_build_ui`, the body grid currently is `root` with `left` at column 0 and
the tabs `right` at column 1. Change the column layout so the file list is at
column 0, the preview at column 1, the tabs at column 2.

Replace the body column config (~lines 1205-1211):

```python
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=0)
        root.rowconfigure(0, weight=1)

        # Left: preview + scrub + filmstrip + trim + grab
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsew")
```
with
```python
        root.columnconfigure(0, weight=0, minsize=190)   # file list
        root.columnconfigure(1, weight=1)                # preview
        root.columnconfigure(2, weight=0)                # tabs
        root.rowconfigure(0, weight=1)

        # Column 0: the multi-file list
        self._build_file_list(root, col=0)

        # Column 1: preview + scrub + filmstrip + trim + grab
        left = ttk.Frame(root)
        left.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
```

Then change the tabs `right` frame placement (~line 1268) from
`right.grid(row=0, column=1, ...)` to:

```python
        right.grid(row=0, column=2, sticky="ns", padx=(12, 0))
```

- [ ] **Step 3: Add the file-list builder + helpers**

Add these methods to `App` (place near `_build_trim_row`):

```python
    def _build_file_list(self, parent, col):
        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=col, sticky="nsew")
        wrap.rowconfigure(2, weight=1)
        wrap.columnconfigure(0, weight=1)

        ttk.Label(wrap, text="Files").grid(row=0, column=0, sticky="w")

        # Combine / Batch segmented toggle (disabled until 2+ clips)
        self.mode_var = tk.StringVar(value="combine")
        modebar = ttk.Frame(wrap)
        modebar.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        modebar.columnconfigure(0, weight=1)
        modebar.columnconfigure(1, weight=1)
        self.combine_btn = ttk.Radiobutton(
            modebar, text="Combine", value="combine", variable=self.mode_var,
            command=lambda: self._set_mode("combine"), style="Toolbutton")
        self.batch_btn = ttk.Radiobutton(
            modebar, text="Batch", value="batch", variable=self.mode_var,
            command=lambda: self._set_mode("batch"), style="Toolbutton")
        self.combine_btn.grid(row=0, column=0, sticky="ew")
        self.batch_btn.grid(row=0, column=1, sticky="ew")

        self.file_listbox = tk.Listbox(
            wrap, activestyle="none", exportselection=False,
            bg=PANEL_BG, fg=TEXT, selectbackground=GOLD, selectforeground=BASE_BG,
            highlightthickness=1, highlightbackground=BORDER, borderwidth=0)
        self.file_listbox.grid(row=2, column=0, sticky="nsew")
        self.file_listbox.bind("<<ListboxSelect>>", self._on_list_select)

        btns = ttk.Frame(wrap)
        btns.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(btns, text="Open…", command=self.open_file).pack(
            side="left")
        ttk.Button(btns, text="−", width=3, command=self._remove_clip).pack(
            side="left", padx=(4, 0))
        ttk.Button(btns, text="↑", width=3,
                   command=lambda: self._move_clip(-1)).pack(side="right")
        ttk.Button(btns, text="↓", width=3,
                   command=lambda: self._move_clip(1)).pack(
            side="right", padx=(0, 4))

        self._update_multi_ui()

    def _refresh_file_list(self):
        """Redraw the listbox rows + edited markers, keep the active selected."""
        if not hasattr(self, "file_listbox"):
            return
        self.file_listbox.delete(0, "end")
        for c in self.clips:
            mark = ""
            if c.crop:
                mark += " ✎"
            if c.start > 0.001 or c.end < c.dur - 0.001:
                mark += " ✓"
            self.file_listbox.insert("end", f"{os.path.basename(c.path)}{mark}")
        if 0 <= self.active < len(self.clips):
            self.file_listbox.selection_clear(0, "end")
            self.file_listbox.selection_set(self.active)

    def _on_list_select(self, _e):
        sel = self.file_listbox.curselection()
        if sel and sel[0] != self.active:
            self._select_clip(sel[0])

    def _remove_clip(self):
        if not (0 <= self.active < len(self.clips)):
            return
        idx = self.active
        del self.clips[idx]
        if not self.clips:
            self.active = -1
            self.input_path = None
            self.crop = None
            self.file_label.config(text="No file loaded — drag a video in "
                                        "or click Open…")
            self.export_btn.config(state="disabled")
            self.grab_btn.config(state="disabled")
            self.canvas.delete("all")
            self._draw_drop_hint()
        else:
            self.active = -1
            self._select_clip(min(idx, len(self.clips) - 1))
        self._refresh_file_list()
        self._update_multi_ui()

    def _move_clip(self, delta):
        i = self.active
        j = i + delta
        if not (0 <= i < len(self.clips) and 0 <= j < len(self.clips)):
            return
        self.clips[i], self.clips[j] = self.clips[j], self.clips[i]
        self.active = j
        self._refresh_file_list()

    def _set_mode(self, mode):
        self.mode = mode
        self._update_export_button()

    def _update_multi_ui(self):
        multi = len(self.clips) >= 2
        state = "normal" if multi else "disabled"
        self.combine_btn.config(state=state)
        self.batch_btn.config(state=state)
        self._update_export_button()

    def _update_export_button(self):
        n = len(self.clips)
        if n >= 2 and self.mode == "batch":
            self.export_btn.config(text=f"Export {n} files")
        elif n >= 2 and self.mode == "combine":
            self.export_btn.config(text="Combine & export")
        else:
            self.export_btn.config(text="Export video")
```

- [ ] **Step 4: Call the refresh + multi-UI hooks from the model methods**

In `_add_clips` (Task A2), after the `if added:` selection, add the two UI
refreshers:

```python
        if added:
            self._select_clip(len(self.clips) - 1)
            self._refresh_file_list()
            self._update_multi_ui()
        return added
```

In `_select_clip` (Task A2), add a final line so the highlight + markers update:

```python
        self._build_filmstrip()
        self._refresh_file_list()
```

- [ ] **Step 5: Verify `style="Toolbutton"` exists, else fall back**

`ttk.Radiobutton(... style="Toolbutton")` renders a segmented look in the `clam`
theme. Run the app; if the toggle looks wrong, drop `style="Toolbutton"` (plain
radio buttons are an acceptable fallback). Decide by looking at it.

- [ ] **Step 6: Build and verify by running**

Run: `python leike.py`
Verify: Open 3 videos — all three appear in the list; clicking a row loads that
clip (its own trim+crop persist when you switch away and back); `✎`/`✓` markers
appear after you crop/trim a clip; ↑/↓ reorder; − removes the selected clip and
selects a neighbour; the Combine/Batch toggle is greyed with one clip and becomes
active with two; the Export button relabels with mode/count. Single-clip behavior
is unchanged.

- [ ] **Step 7: Commit (Phase A done)**

```bash
git add leike.py
git commit -m "feat: file-list column with Combine/Batch toggle and reorder"
```

---

## Phase B — Batch export

### Task B1: `_batch_out_name()` (pure)

**Files:**
- Modify: `leike.py` (add near `build_commands`, ~line 711)
- Modify: `tests/test_multifile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_multifile.py
def test_batch_out_name_suffix_and_numbering(leike, tmp_path):
    taken = set()
    p1 = leike["_batch_out_name"](str(tmp_path), "C:/x/clip.mp4", ".mp4", taken)
    assert p1.replace("\\", "/").endswith("clip_export.mp4")
    # same stem again -> auto-numbered, never overwrites
    p2 = leike["_batch_out_name"](str(tmp_path), "D:/y/clip.mov", ".mp4", taken)
    assert p2.replace("\\", "/").endswith("clip_export_2.mp4")
    p3 = leike["_batch_out_name"](str(tmp_path), "E:/z/clip.avi", ".mp4", taken)
    assert p3.replace("\\", "/").endswith("clip_export_3.mp4")

def test_batch_out_name_distinct_stems(leike, tmp_path):
    taken = set()
    a = leike["_batch_out_name"](str(tmp_path), "a.mp4", ".mp4", taken)
    b = leike["_batch_out_name"](str(tmp_path), "b.mp4", ".mp4", taken)
    assert a.endswith("a_export.mp4")
    assert b.endswith("b_export.mp4")
```

- [ ] **Step 2: Run it — expect failure**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: FAIL (`KeyError: '_batch_out_name'`).

- [ ] **Step 3: Implement**

Add near `build_commands` in `leike.py`:

```python
def _batch_out_name(folder, src_path, ext, taken):
    """Auto-named batch output: <stem>_export<ext>, numbered on collision.
    `taken` is a set of lower-cased basenames already used this run; names that
    already exist on disk in `folder` are also skipped. Never overwrites."""
    stem = os.path.splitext(os.path.basename(src_path))[0]
    base = f"{stem}_export"
    name = base + ext
    i = 2
    while name.lower() in taken or os.path.exists(os.path.join(folder, name)):
        name = f"{base}_{i}{ext}"
        i += 1
    taken.add(name.lower())
    return os.path.join(folder, name)
```

- [ ] **Step 4: Run it — expect pass**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add leike.py tests/test_multifile.py
git commit -m "feat: _batch_out_name with _export suffix + collision numbering"
```

---

### Task B2: refactor the pass-runner into `_run_passes`

**Why:** `_run_export` currently runs passes AND reports done in one method.
Batch and Combine both need to run a job's passes and get back a result. Extract
a reusable runner that maps progress into a sub-range and returns `(ok, err)`.

**Files:**
- Modify: `leike.py` — `_run_export` (~line 2536).

- [ ] **Step 1: Add `_run_passes` and slim `_run_export`**

Replace `_run_export` (the whole method, ~lines 2536-2570) with:

```python
    def _run_passes(self, cmds, dur, base_frac, span):
        """Run one job's ffmpeg passes; map progress into
        [base_frac, base_frac+span] of the bar. Returns (ok, err). Honours
        self._cancelled and records self.export_proc for Cancel."""
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        last_err = ""
        n = len(cmds)
        for i, cmd in enumerate(cmds):
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    text=True, creationflags=NO_WINDOW)
            except OSError as exc:
                return (False, str(exc))
            self.export_proc = proc
            for line in proc.stderr:
                if self._cancelled:
                    proc.kill()
                    break
                m = time_re.search(line)
                if m:
                    t = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                         + float(m.group(3)))
                    frac = base_frac + span * (i + min(1.0, t / dur)) / n
                    self.after(0, lambda p=frac * 100:
                               self.progress.config(value=p))
                elif line.strip():
                    last_err = line.strip()
            code = proc.wait()
            if self._cancelled:
                return (False, last_err)
            if code != 0:
                return (False, last_err)
        return (True, last_err)

    def _run_export(self, cmds, dur, out):
        """Single-file export: run all passes, then report done."""
        self._cancelled = False
        ok, err = self._run_passes(cmds, dur, 0.0, 1.0)
        self.after(0, lambda: self._export_done(ok, err, out))
```

- [ ] **Step 2: Build and verify a normal single-file export still works**

Run: `python leike.py` — load one clip, trim + crop, Export. The progress bar
fills 0→100, the file is produced, Cancel still works mid-export. Behavior is
identical to before.

- [ ] **Step 3: Commit**

```bash
git add leike.py
git commit -m "refactor: extract reusable _run_passes from _run_export"
```

---

### Task B3: batch export wiring (`_settings_for_clip`, `_run_batch`, branch)

**Files:**
- Modify: `leike.py` — add `_settings_for_clip`, `_begin_run`, `_run_batch`,
  `_batch_done`, `_start_single`, `_start_batch`; rewrite `export()` to branch.

- [ ] **Step 1: Add `_settings_for_clip` and a `_begin_run` helper**

Add to `App` (near `_settings`):

```python
    def _settings_for_clip(self, clip, out):
        """Global recipe from the widgets, with trim+crop from `clip`."""
        s = self._settings(out)
        s.input_path = clip.path
        s.src_w, s.src_h = clip.src_w, clip.src_h
        s.start, s.end = clip.start, clip.end
        s.crop = tuple(clip.crop) if clip.crop else None
        return s

    def _begin_run(self):
        """Shared pre-run UI: disable Export, enable Cancel, reset progress."""
        self.export_btn.config(state="disabled")
        if getattr(self, "cancel_btn", None):
            self.cancel_btn.config(state="normal")
        self.progress["value"] = 0
```

- [ ] **Step 2: Rewrite `export()` to branch into single / batch / combine**

Replace the start of `export()` (the guard + the single-file body) so it
dispatches. Combine is stubbed here and implemented in Phase C.

```python
    def export(self):
        if not self.clips:
            return
        self._commit_active()
        multi = len(self.clips) >= 2
        if multi and self.mode == "batch":
            return self._start_batch()
        if multi and self.mode == "combine":
            return self._start_combine()
        return self._start_single()

    def _start_single(self):
        if not self.input_path:
            return
        if self.audio_only_var.get():
            ext, ftypes = ".mp3", [("MP3 audio", "*.mp3")]
        else:
            fmt = dict(FORMATS)[self.fmt_var.get()]
            ext = {"mp4": ".mp4", "gif": ".gif", "webm": ".webm"}[fmt]
            ftypes = {"mp4": [("MP4 video", "*.mp4")], "gif": [("GIF", "*.gif")],
                      "webm": [("WebM video", "*.webm")]}[fmt]
        base = os.path.splitext(os.path.basename(self.input_path))[0]
        out = filedialog.asksaveasfilename(
            title="Export as", defaultextension=ext,
            initialfile=f"{base}_export{ext}",
            initialdir=self.out_dir or os.path.dirname(self.input_path),
            filetypes=ftypes)
        if not out:
            return
        if os.path.abspath(out) == os.path.abspath(self.input_path):
            messagebox.showerror("Error", "Choose a different output file.")
            return
        self.out_dir = os.path.dirname(out)
        self._save_config()
        dur = max(0.001, self.end_t - self.start_t)
        cmds = build_commands(self._settings(out))
        self._begin_run()
        self.status_label.config(text="Exporting...")
        threading.Thread(target=self._run_export, args=(cmds, dur, out),
                         daemon=True).start()
```

(This `_start_single` is the old `export()` body verbatim, minus the
`if not self.input_path` early-return now living at the top.)

- [ ] **Step 3: Add the batch starter + runner + done**

```python
    def _start_batch(self):
        folder = filedialog.askdirectory(
            title="Choose output folder for the batch",
            initialdir=self.out_dir or os.path.dirname(self.clips[0].path))
        if not folder:
            return
        self.out_dir = folder
        self._save_config()
        if self.audio_only_var.get():
            ext = ".mp3"
        else:
            fmt = dict(FORMATS)[self.fmt_var.get()]
            ext = {"mp4": ".mp4", "gif": ".gif", "webm": ".webm"}[fmt]
        taken = set()
        jobs = []
        for clip in self.clips:
            out = _batch_out_name(folder, clip.path, ext, taken)
            s = self._settings_for_clip(clip, out)
            cmds = build_commands(s)
            dur = max(0.001, clip.end - clip.start)
            jobs.append((clip, cmds, dur, out))
        self._begin_run()
        self.status_label.config(text=f"Exporting 1/{len(jobs)}…")
        threading.Thread(target=self._run_batch, args=(jobs,), daemon=True).start()

    def _run_batch(self, jobs):
        self._cancelled = False
        n = len(jobs)
        done, failed = 0, []
        for k, (clip, cmds, dur, out) in enumerate(jobs):
            if self._cancelled:
                break
            self.after(0, lambda k=k, name=os.path.basename(clip.path):
                       self.status_label.config(
                           text=f"Exporting {k + 1}/{n}: {name}"))
            ok, err = self._run_passes(cmds, dur, k / n, 1.0 / n)
            for f in glob.glob(out + ".2pass*") + glob.glob(out + ".trf"):
                try:
                    os.remove(f)
                except OSError:
                    pass
            if ok:
                done += 1
            else:
                failed.append(os.path.basename(clip.path))
                try:
                    if os.path.exists(out):
                        os.remove(out)
                except OSError:
                    pass
        self.after(0, lambda: self._batch_done(done, failed, n))

    def _batch_done(self, done, failed, n):
        self.export_btn.config(state="normal")
        if getattr(self, "cancel_btn", None):
            self.cancel_btn.config(state="disabled")
        if self._cancelled:
            self.progress["value"] = 0
            self.status_label.config(text=f"Cancelled ({done}/{n} done).")
            return
        self.progress["value"] = 100
        if failed:
            self.status_label.config(text=f"Done: {done}/{n} ({len(failed)} failed).")
            messagebox.showwarning(
                "Batch finished",
                f"Exported {done} of {n}.\nFailed:\n" + "\n".join(failed))
        else:
            self.status_label.config(text=f"Done: {done}/{n} exported.")
            messagebox.showinfo("Batch complete", f"Exported all {n} files.")
```

- [ ] **Step 4: Build and verify batch by running**

Run: `python leike.py`
Verify: Add 3 clips, choose **Batch**, set a downscale + format in Export, click
"Export 3 files", pick a folder. The bar advances across all three; outputs land
as `<name>_export.<ext>` (numbered if two share a stem); the summary dialog
reports 3/3. Set one clip's trim and confirm only that output is trimmed. Cancel
mid-run stops cleanly and reports `done/n`. Point one clip at a deleted file to
confirm the run continues and the summary lists the failure.

- [ ] **Step 5: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 6: Commit (Phase B done)**

```bash
git add leike.py
git commit -m "feat: batch export — N files through one recipe, resilient + summary"
```

---

## Phase C — Combine export

### Task C1: `_combine_target()` (pure)

**Files:**
- Modify: `leike.py` (add near `build_commands`)
- Modify: `tests/test_multifile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_multifile.py
def test_combine_target_largest_and_fps(leike):
    Clip = leike["Clip"]
    clips = [Clip("a", 1280, 720, 5, fps=30, end=5),
             Clip("b", 1920, 1080, 5, fps=60, end=5)]
    assert leike["_combine_target"](clips) == (1920, 1080, 60.0)

def test_combine_target_uses_per_clip_crop(leike):
    Clip = leike["Clip"]
    clips = [Clip("a", 1920, 1080, 5, end=5, crop=(0, 0, 640, 480))]
    assert leike["_combine_target"](clips)[:2] == (640, 480)

def test_combine_target_applies_scale_cap(leike):
    Clip = leike["Clip"]
    clips = [Clip("a", 1280, 720, 5, fps=30, end=5),
             Clip("b", 1920, 1080, 5, fps=60, end=5)]
    W, H, F = leike["_combine_target"](clips, scale_cap=1280)
    assert max(W, H) == 1280 and (W, H) == (1280, 720) and F == 60.0
```

- [ ] **Step 2: Run it — expect failure**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: FAIL (`KeyError: '_combine_target'`).

- [ ] **Step 3: Implement**

Add near `build_commands` in `leike.py` (`even` is already defined ~line 187):

```python
def _combine_target(clips, scale_cap=None):
    """Common canvas (W, H, fps) for combining: the largest clip size after its
    own crop, the highest fps, with an optional longest-side cap."""
    ws, hs, fpss = [], [], []
    for c in clips:
        if c.crop:
            w, h = even(c.crop[2]), even(c.crop[3])
        else:
            w, h = even(c.src_w), even(c.src_h)
        ws.append(max(2, w))
        hs.append(max(2, h))
        fpss.append(c.fps or 30.0)
    W, H = max(ws), max(hs)
    if scale_cap and max(W, H) > scale_cap:
        f = scale_cap / max(W, H)
        W, H = even(W * f), even(H * f)
    return max(2, W), max(2, H), max(fpss)
```

- [ ] **Step 4: Run it — expect pass**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add leike.py tests/test_multifile.py
git commit -m "feat: _combine_target — largest canvas + highest fps + cap"
```

---

### Task C2: `_concat_filtergraph()` + `build_concat_commands()` (pure)

**Files:**
- Modify: `leike.py` (add near `build_commands`)
- Modify: `tests/test_multifile.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_multifile.py
def _g(leike, **kw):
    S = leike["ExportSettings"]
    base = dict(input_path="", output_path="out.mp4", src_w=0, src_h=0,
                start=0.0, end=0.0, fmt="mp4", crf=20)
    base.update(kw)
    return S(**base)

def test_concat_two_clips_join_and_canvas(leike):
    Clip = leike["Clip"]
    clips = [Clip("a.mp4", 1280, 720, 5, fps=30, end=5),
             Clip("b.mp4", 1920, 1080, 4, fps=30, end=4)]
    cmds = leike["build_concat_commands"](clips, _g(leike))
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd.count("-i") == 2                    # two inputs
    j = " ".join(cmd)
    assert "concat=n=2:v=1:a=1" in j
    assert "gblur=sigma=20" in j                   # blurred fill
    assert "1920:1080" in j                        # target = largest clip
    assert "libx264" in j and "aac" in j
    assert "-map [v]" in j

def test_concat_crop_only_on_cropped_clip(leike):
    Clip = leike["Clip"]
    clips = [Clip("a.mp4", 1920, 1080, 5, end=5, crop=(0, 0, 640, 480)),
             Clip("b.mp4", 1920, 1080, 5, end=5)]
    j = " ".join(leike["build_concat_commands"](clips, _g(leike))[0])
    assert "crop=640:480:0:0" in j
    assert j.count("crop=640:480") == 1            # only the first clip

def test_concat_silent_clip_gets_anullsrc(leike):
    Clip = leike["Clip"]
    clips = [Clip("a.mp4", 1920, 1080, 5, end=5, has_audio=True),
             Clip("b.mp4", 1920, 1080, 5, end=5, has_audio=False)]
    j = " ".join(leike["build_concat_commands"](clips, _g(leike))[0])
    assert "anullsrc" in j

def test_concat_mute_drops_audio(leike):
    Clip = leike["Clip"]
    clips = [Clip("a.mp4", 1920, 1080, 5, end=5),
             Clip("b.mp4", 1920, 1080, 5, end=5)]
    j = " ".join(leike["build_concat_commands"](clips, _g(leike, mute=True))[0])
    assert "concat=n=2:v=1:a=0" in j
    assert "-an" in j
    assert "anullsrc" not in j

def test_concat_global_eq_after_join(leike):
    Clip = leike["Clip"]
    clips = [Clip("a.mp4", 1920, 1080, 5, end=5),
             Clip("b.mp4", 1920, 1080, 5, end=5)]
    j = " ".join(leike["build_concat_commands"](clips, _g(leike, brightness=0.1))[0])
    assert "eq=brightness=0.100" in j
    assert j.index("concat=") < j.index("eq=brightness")   # global, after join

def test_concat_webm_codecs(leike):
    Clip = leike["Clip"]
    clips = [Clip("a.webm", 1280, 720, 5, end=5),
             Clip("b.webm", 1280, 720, 5, end=5)]
    j = " ".join(leike["build_concat_commands"](clips, _g(leike, fmt="webm"))[0])
    assert "libvpx-vp9" in j and "libopus" in j
```

- [ ] **Step 2: Run them — expect failure**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: FAIL (`KeyError: 'build_concat_commands'`).

- [ ] **Step 3: Implement the graph helper + builder**

Add near `build_commands` in `leike.py` (reuses `_orient_filters`,
`_adjust_filters`, `_speed_filter`, `_drawtext_filter`, `_subtitles_filter`,
`_af_chain`, `_venc`, `even`):

```python
def _concat_filtergraph(clips, g, W, H, F):
    """filter_complex joining clips on a W×H @F canvas (blurred fill), then the
    global recipe g on the joined stream. Returns (graph, vlabel, alabel);
    alabel is None when audio is dropped (g.mute)."""
    parts = []
    n = len(clips)
    for i, c in enumerate(clips):
        pre = ""
        if c.crop:
            x, y, w, h = c.crop
            pre = f"crop={even(w)}:{even(h)}:{even(x)}:{even(y)},"
        parts.append(
            f"[{i}:v]{pre}split=2[bg{i}][fg{i}];"
            f"[bg{i}]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},gblur=sigma=20[bgb{i}];"
            f"[fg{i}]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs{i}];"
            f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,"
            f"setsar=1,fps={F:g},format=yuv420p[v{i}]")
    muted = getattr(g, "mute", False)
    if not muted:
        for i, c in enumerate(clips):
            if c.has_audio:
                parts.append(f"[{i}:a]aresample=async=1:first_pts=0[a{i}]")
            else:
                d = max(0.001, c.end - c.start)
                parts.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                    f"atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{i}]")
    if muted:
        joins = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{joins}concat=n={n}:v=1:a=0[vc]")
        alabel = None
    else:
        joins = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{joins}concat=n={n}:v=1:a=1[vc][ac]")
        alabel = "[ac]"

    speed = getattr(g, "speed", 1.0) or 1.0
    total = sum(max(0.001, c.end - c.start) for c in clips) / speed
    vchain = _orient_filters(g) + _adjust_filters(g) + _speed_filter(g)
    fi = getattr(g, "fade_in", 0.0) or 0.0
    fo = getattr(g, "fade_out", 0.0) or 0.0
    if fi > 0:
        vchain.append(f"fade=t=in:st=0:d={fi:.2f}")
    if fo > 0:
        vchain.append(f"fade=t=out:st={max(0.0, total - fo):.2f}:d={fo:.2f}")
    vchain += _drawtext_filter(g) + _subtitles_filter(g)
    vchain.append("format=yuv420p")          # final pixfmt; also pins label [v]
    parts.append(f"[vc]{','.join(vchain)}[v]")
    vlabel = "[v]"
    if alabel:
        af = _af_chain(g)
        if af:
            parts.append(f"[ac]{','.join(af)}[a]")
            alabel = "[a]"
    return ";".join(parts), vlabel, alabel


def build_concat_commands(clips, g):
    """Join `clips` into one output. g supplies the global recipe + output_path /
    fmt / crf / scale_cap / hw. Combine targets mp4 or webm. Returns [cmd]."""
    W, H, F = _combine_target(clips, getattr(g, "scale_cap", None))
    graph, vlabel, alabel = _concat_filtergraph(clips, g, W, H, F)
    inputs = []
    for c in clips:
        d = max(0.001, c.end - c.start)
        inputs += ["-ss", f"{c.start:.3f}", "-t", f"{d:.3f}", "-i", c.path]
    cmd = [FFMPEG, "-y", *inputs, "-filter_complex", graph, "-map", vlabel]
    if alabel:
        cmd += ["-map", alabel]
    if g.fmt == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", str(g.crf), "-b:v", "0"]
        cmd += (["-c:a", "libopus", "-b:a", "128k"] if alabel else ["-an"])
    else:  # mp4
        cmd += _venc(g) + ["-pix_fmt", "yuv420p"]
        cmd += (["-c:a", "aac", "-b:a", "128k"] if alabel else ["-an"])
        cmd += ["-movflags", "+faststart"]
    cmd += [g.output_path]
    return [cmd]
```

> Note on `cmd.count("-i")`: each input contributes exactly one `"-i"` token, so
> the test's `cmd.count("-i") == 2` holds. `-map [v]` appears as two adjacent
> tokens `"-map"`, `"[v]"`, so `" ".join(cmd)` contains the substring `-map [v]`.

- [ ] **Step 4: Run them — expect pass**

Run: `python -m pytest tests/test_multifile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add leike.py tests/test_multifile.py
git commit -m "feat: build_concat_commands — blurred-fill normalize + concat join"
```

---

### Task C3: combine export wiring + mode-aware Export controls

**Files:**
- Modify: `leike.py` — implement `_start_combine` (stubbed in B3); disable
  GIF/target-size controls in Combine mode via `_update_multi_ui`.

- [ ] **Step 1: Implement `_start_combine`**

Add to `App` (near `_start_batch`):

```python
    def _start_combine(self):
        for c in self.clips:
            if not os.path.exists(c.path):
                messagebox.showerror(
                    "Missing file",
                    f"This file is gone:\n{c.path}")
                return
        fmt = dict(FORMATS)[self.fmt_var.get()]
        if fmt not in ("mp4", "webm"):       # GIF/mp3 not supported for combine
            fmt = "mp4"
        ext = ".webm" if fmt == "webm" else ".mp4"
        base = os.path.splitext(os.path.basename(self.clips[0].path))[0]
        out = filedialog.asksaveasfilename(
            title="Combine & export as", defaultextension=ext,
            initialfile=f"{base}_combined{ext}",
            initialdir=self.out_dir or os.path.dirname(self.clips[0].path),
            filetypes=([("MP4 video", "*.mp4")] if fmt == "mp4"
                       else [("WebM video", "*.webm")]))
        if not out:
            return
        self.out_dir = os.path.dirname(out)
        self._save_config()
        g = self._settings(out)
        g.fmt = fmt
        cmds = build_concat_commands(self.clips, g)
        dur = sum(max(0.001, c.end - c.start) for c in self.clips) \
            / (g.speed or 1.0)
        self._begin_run()
        self.status_label.config(text="Combining…")
        threading.Thread(target=self._run_export, args=(cmds, dur, out),
                         daemon=True).start()
```

- [ ] **Step 2: Grey out unsupported format controls in Combine mode**

Extend `_update_export_button` so it also notes the Combine format limitation in
the status line when the chosen format isn't combinable. Add to the end of
`_update_multi_ui`:

```python
        if len(self.clips) >= 2 and self.mode == "combine":
            fmt = dict(FORMATS)[self.fmt_var.get()]
            if fmt not in ("mp4", "webm") or self.audio_only_var.get():
                self.status_label.config(
                    text="Combine exports MP4/WebM — format will be MP4.")
```

- [ ] **Step 3: Build and verify combine by running**

Run: `python leike.py`
Verify: Add a landscape 1080p clip and a portrait phone clip; choose **Combine**;
"Combine & export". The output is a single file at the larger canvas with the
portrait clip centered over a blurred fill; the two clips play back-to-back with
audio in sync. Add a clip with no audio and confirm the join still has continuous
audio (silence over the silent clip). Apply a global colour change and confirm it
affects the whole joined video. Cancel mid-combine removes the partial file.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add leike.py
git commit -m "feat: combine export — join clips into one file"
```

---

### Task C4: docs, version bump, build, ship v2.3

**Files:**
- Modify: `README.md` (features list), `installer/Leike.iss` (version), any
  `leike.py` version constant.

- [ ] **Step 1: Add a README feature bullet**

In `README.md`, under **## Features**, add:

```markdown
- **Combine** several clips into one file (drag them into the list, trim/crop
  each, then export — mismatched sizes are centered over a blurred fill), or
  **Batch**-export a whole list through one recipe to a folder.
```

- [ ] **Step 2: Bump the version to 2.3**

Run a search and update every version string from `2.2`:

```bash
grep -rn "2\.2" installer/Leike.iss leike.py README.md
```
Set `installer/Leike.iss` `#define MyAppVersion "2.3"` and any in-app version
constant in `leike.py` to `2.3`. (Leave unrelated `2.2` matches alone.)

- [ ] **Step 3: Build the exe**

Run: `Build-exe.bat`
Expected: `dist/Leike.exe` rebuilt with no errors.

- [ ] **Step 4: Smoke-test the built exe**

Run `dist/Leike.exe`: add two clips, combine them, then batch them. Both produce
output. (Catches any PyInstaller hidden-import / path issue before release.)

- [ ] **Step 5: Build the installer + portable zip, tag, release**

Run `Build-installer.bat`; assemble the portable zip as in prior releases; then:

```bash
git add README.md installer/Leike.iss leike.py
git commit -m "release: multi-file Combine + Batch — v2.3"
git tag v2.3
git push && git push --tags
gh release create v2.3 --title "Leike v2.3 — Combine & Batch" \
  --notes "Combine multiple clips into one file (blurred-fill normalize), or batch-export a list through one recipe. New file-list column with a Combine/Batch toggle; per-file trim + crop."
```

Attach the exe / installer / portable zip / mac+linux CI artifacts as in the v2.2
release flow.

- [ ] **Step 6: Confirm the landing page picks up v2.3**

The site's version line + changelog modal fetch the latest GitHub release at
runtime, so no site edit is needed — load the page and confirm it shows v2.3 and
the new release notes.

---

## Self-review notes

- **Spec coverage:** clip-list model + per-file trim/crop (A1–A3); file-list
  column + Combine/Batch toggle + reorder/remove (A3); reusable runner (B2);
  batch with folder prompt, `_export` naming + numbering, resilient errors +
  summary (B1, B3); combine with largest-canvas blurred-fill normalize, highest
  fps, `anullsrc` for silent clips, mute path, global recipe after join, mp4/webm
  (C1–C3); window-width bump (A3); release as v2.3 (C4). Every spec section maps
  to a task. ✔
- **Out of scope (stated in spec):** GIF / target-size in Combine — `_start_combine`
  forces mp4/webm and warns in the status line. ✔
- **Type consistency:** `Clip` fields (`path, src_w, src_h, dur, rotation, fps,
  has_audio, start, end, crop`) are used verbatim in `clip_from_info`,
  `_combine_target`, `_concat_filtergraph`, `build_concat_commands`,
  `_settings_for_clip`, and the UI. `build_concat_commands(clips, g)` and
  `build_commands(s)` both return `list[list[str]]`. `_run_passes(cmds, dur,
  base_frac, span) -> (ok, err)` is called by `_run_export` and `_run_batch`. ✔
- **Reverse/boomerang/loop in Combine:** deliberately not wired into the joined
  recipe (they'd desync the concat); single-file export keeps them. Noted so an
  implementer doesn't add them speculatively.
- **Risk:** the A2 refactor is the riskiest change; it lands before any export
  work and is run-verified to match prior single-file behavior exactly.
```
