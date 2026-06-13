# Leike UI Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize Leike's controls into a tabbed layout (header bar, left preview+trim, right `ttk.Notebook` with a persistent Export footer) and refine the styling — without changing any export behavior.

**Architecture:** Pure widget-layout/styling refactor of `leike.py`. `_build_ui` is rewritten; each `_build_*_panel` is re-homed into a notebook tab frame; `_apply_theme` gains Notebook + accent-button styles. `ExportSettings`, `build_commands`, the filter graph, and all 42 tests are untouched — every `*_var` keeps the same name, only its parent container changes.

**Tech Stack:** Python 3 + tkinter/ttk (single file `leike.py`), pytest, PyInstaller + Inno Setup.

---

## Testing approach

GUI layout can't be meaningfully unit-tested, so verification per task is: (1) the **full pytest suite stays green** (proves no logic broke), (2) `py_compile` clean, (3) **launch-alive** (`pythonw leike.py` stays running 5s — catches widget-construction crashes), and (4) one **structural headless test** that constructs the App once and asserts the notebook tabs and that every `_settings`-read variable still exists. The final look is confirmed by the user visually. Reference spec: `docs/superpowers/specs/2026-06-14-leike-ui-modernization-design.md`.

Run the suite: `python -m pytest tests/ -q`. Launch check (PowerShell):
```powershell
$p = Start-Process pythonw -ArgumentList "leike.py" -PassThru; Start-Sleep 5
if (-not $p.HasExited) { "OK"; Stop-Process $p.Id -Force } else { "EXIT $($p.ExitCode)" }
```

## File structure
- `leike.py` — all changes. Sections touched: `_apply_theme` (new styles), `_build_ui` (rewritten), `_build_crop_panel` / `_build_trim_panel` / `_build_export_panel` / `_build_encoding_panel` / `_build_audio_panel` / `_build_transform_panel` / `_build_adjust_panel` / `_build_overlay_panel` (re-parented into tabs; Transform+Adjust merged into an Effects tab; Encoding folded into Export). Removed: `_scrollable`, `_toggle_adv`.
- `tests/test_ui_structure.py` — NEW structural test.

---

### Task 1: Theme — Notebook and accent-button styles

**Files:** Modify `leike.py` → end of `_apply_theme` (the method that configures the `clam` styles).

- [ ] **Step 1: Add the styles.** At the end of `_apply_theme`, after the existing Progressbar config, append:

```python
        # Notebook (tabs)
        style.configure("TNotebook", background=BASE_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_BG, foreground=MUTED,
                        padding=(10, 6), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", PANEL_HI)],
                  foreground=[("selected", GOLD)])
        # Primary (accent) button — gold fill, dark text
        style.configure("Accent.TButton", background=GOLD, foreground=BASE_BG,
                        bordercolor=GOLD_DEEP, relief="flat", padding=7)
        style.map("Accent.TButton",
                  background=[("active", GOLD_LIGHT), ("pressed", GOLD_DEEP)],
                  foreground=[("disabled", MUTED)])
        # Small uppercase section label
        style.configure("Section.TLabel", foreground=MUTED, background=BASE_BG)
```

- [ ] **Step 2: Verify.** Run `python -c "import py_compile; py_compile.compile('leike.py', doraise=True)"` → no error. Run the launch check → OK. Run `python -m pytest tests/ -q` → 42 passed.

- [ ] **Step 3: Commit.**
```bash
git add leike.py
git commit -m "style: add Notebook + accent-button theme styles"
```

---

### Task 2: Rewrite the layout — header, left preview+trim, right notebook + footer

This replaces the body of `_build_ui` and re-homes panels. The panel-builder methods keep their bodies; only their **target parent** and the **row they grid into** change. Build the tab frames first, then call the existing builders with those frames as `parent`.

**Files:** Modify `leike.py` → `_build_ui` (full rewrite), and adjust the `box.grid(...)` line at the top of each `_build_*_panel` so each panel fills its tab (`row=0, column=0, sticky="ew"`), plus the merge/fold described below.

- [ ] **Step 1: Replace `_build_ui` entirely** with:

```python
    def _build_ui(self):
        self.configure(bg=BASE_BG)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # ---- Header bar ----
        header = ttk.Frame(self, padding=(12, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(3, weight=1)
        logo = tk.Canvas(header, width=16, height=16, bg=BASE_BG,
                         highlightthickness=0)
        logo.create_rectangle(0, 0, 16, 16, fill=GOLD, outline="")
        logo.grid(row=0, column=0, padx=(0, 8))
        ttk.Label(header, text="Leike", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=1)
        ttk.Button(header, text="Open…", command=self.open_file).grid(
            row=0, column=2, padx=(12, 0))
        hint = "No file loaded — drag a video in or click Open…"
        self.file_label = ttk.Label(header, text=hint, foreground=MUTED,
                                    anchor="e")
        self.file_label.grid(row=0, column=3, sticky="e")
        ttk.Separator(self, orient="horizontal").grid(row=0, column=0,
                                                      sticky="sew")

        # ---- Body ----
        root = ttk.Frame(self, padding=10)
        root.grid(row=1, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=0)
        root.rowconfigure(0, weight=1)

        # Left: preview + scrub + filmstrip + trim + grab
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(left, width=PREVIEW_MAX_W, height=PREVIEW_MAX_H,
                                bg=CANVAS_BG, highlightthickness=1,
                                highlightbackground=CANVAS_BORDER)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._draw_drop_hint()

        scrub = ttk.Frame(left)
        scrub.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        scrub.columnconfigure(1, weight=1)
        ttk.Label(scrub, text="Preview").grid(row=0, column=0, padx=(0, 6))
        self.scrub_var = tk.DoubleVar(value=0.0)
        self.scrub = ttk.Scale(scrub, from_=0, to=1, variable=self.scrub_var,
                               command=self.on_scrub)
        self.scrub.grid(row=0, column=1, sticky="ew")
        self.playhead_label = ttk.Label(scrub, text="00:00.000", width=12)
        self.playhead_label.grid(row=0, column=2, padx=(6, 0))

        self.strip = tk.Canvas(left, height=52, bg=PANEL_BG,
                               highlightthickness=1, highlightbackground=BORDER)
        self.strip.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.strip.bind("<Button-1>", self._strip_seek)
        self.strip.bind("<B1-Motion>", self._strip_seek)
        self.strip.bind("<Configure>", self._on_strip_resize)

        self._build_trim_row(left, row=3)        # NEW compact trim row
        self.grab_btn = ttk.Button(left, text="Grab frame",
                                   command=self.grab_frame, state="disabled")
        self.grab_btn.grid(row=4, column=0, sticky="w", pady=(6, 0))

        if HAS_DND:
            for w in (self, self.canvas):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

        # Right: notebook + persistent footer
        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        right.rowconfigure(0, weight=1)
        nb = ttk.Notebook(right, width=330)
        nb.grid(row=0, column=0, sticky="nsew")
        tab_crop = ttk.Frame(nb, padding=8)
        tab_fx = ttk.Frame(nb, padding=8)
        tab_overlay = ttk.Frame(nb, padding=8)
        tab_audio = ttk.Frame(nb, padding=8)
        tab_export = ttk.Frame(nb, padding=8)
        for f in (tab_crop, tab_fx, tab_overlay, tab_audio, tab_export):
            f.columnconfigure(0, weight=1)
        nb.add(tab_crop, text="Crop")
        nb.add(tab_fx, text="Effects")
        nb.add(tab_overlay, text="Overlay")
        nb.add(tab_audio, text="Audio")
        nb.add(tab_export, text="Export")
        self.notebook = nb

        self._build_crop_panel(tab_crop)
        self._build_transform_panel(tab_fx)
        self._build_adjust_panel(tab_fx)
        self._build_overlay_panel(tab_overlay)
        self._build_audio_panel(tab_audio)
        self._build_export_panel(tab_export)

        self._build_footer(right, row=1)         # NEW persistent footer
```

- [ ] **Step 2: Add the new `_build_trim_row` and `_build_footer` helpers** (place them right after `_build_ui`):

```python
    def _build_trim_row(self, parent, row):
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(box, text="Trim", style="Section.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w")
        self.start_var = tk.StringVar(value="00:00.000")
        e1 = ttk.Entry(box, textvariable=self.start_var, width=11)
        e1.grid(row=1, column=0, padx=(0, 4), pady=(2, 0))
        e1.bind("<Return>", lambda _e: self.commit_times())
        e1.bind("<FocusOut>", lambda _e: self.commit_times())
        ttk.Button(box, text="Set start",
                   command=lambda: self.set_from_playhead("start")).grid(
            row=1, column=1, pady=(2, 0))
        ttk.Label(box, text="→").grid(row=1, column=2, padx=4)
        self.end_var = tk.StringVar(value="00:00.000")
        e2 = ttk.Entry(box, textvariable=self.end_var, width=11)
        e2.grid(row=1, column=3, padx=(0, 4), pady=(2, 0))
        e2.bind("<Return>", lambda _e: self.commit_times())
        e2.bind("<FocusOut>", lambda _e: self.commit_times())
        ttk.Button(box, text="Set end",
                   command=lambda: self.set_from_playhead("end")).grid(
            row=1, column=4, pady=(2, 0))
        self.trim_label = ttk.Label(box, text="Duration: 0.000 s",
                                    foreground=MUTED)
        self.trim_label.grid(row=2, column=0, columnspan=6, sticky="w",
                             pady=(3, 0))

    def _build_footer(self, parent, row):
        box = ttk.Frame(parent, padding=(0, 10, 0, 0))
        box.grid(row=row, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.export_btn = ttk.Button(box, text="⬇  Export video",
                                     style="Accent.TButton",
                                     command=self.export, state="disabled")
        self.export_btn.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ttk.Button(box, text="Cancel",
                                     command=self.cancel_export, state="disabled")
        self.cancel_btn.grid(row=0, column=1, padx=(6, 0))
        self.export_hint = ttk.Label(box, text="", foreground=GOLD)
        self.export_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                              pady=(6, 0))
        self.progress = ttk.Progressbar(box, mode="determinate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew",
                           pady=(4, 0))
        self.status_label = ttk.Label(box, text="", foreground=MUTED)
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w",
                               pady=(3, 0))
```

- [ ] **Step 3: Fold the old Trim, Export-buttons, and Encoding into their new homes.**
  - `_build_trim_panel` is now **dead** (replaced by `_build_trim_row`). Delete the `_build_trim_panel` method.
  - In `_build_export_panel`: delete the inner `btns`/`export_btn`/`cancel_btn`/`export_hint`/`progress`/`status_label` block (now in `_build_footer`). Keep the Format/Downscale/Quality/target-size rows. Change its top `box.grid(...)` to `box.grid(row=0, column=0, sticky="ew")` and have it grid into the passed `parent` (the export tab). Then **call `_build_encoding_panel(parent)`** at the end of `_build_export_panel` so fast-trim/GPU/target-size live on the Export tab too. Move the `_build_encoding_panel` call **out of** the old advanced block.
  - In `_build_crop_panel`, `_build_transform_panel`, `_build_adjust_panel`, `_build_overlay_panel`, `_build_audio_panel`, `_build_encoding_panel`: change each top `box.grid(row=N, ...)` to `box.grid(row=?, column=0, sticky="ew", pady=(0, 8))` where Effects-tab panels stack (transform `row=0`, adjust `row=1`) and single-panel tabs use `row=0`. Each `box` already takes `parent` — that now resolves to the tab frame.

- [ ] **Step 4: Verify.** `py_compile` clean; launch check OK; `pytest tests/ -q` → 42 passed. Manually confirm (launch) the five tabs appear and the Export button sits below them.

- [ ] **Step 5: Commit.**
```bash
git add leike.py
git commit -m "feat: tabbed control layout with header and persistent export footer"
```

---

### Task 3: Remove dead scaffolding (scroll column + More-options)

**Files:** Modify `leike.py`.

- [ ] **Step 1: Delete** the `_scrollable` method and the `_toggle_adv` method. Delete any remaining references to `self.adv_btn`, `self.adv_shown`, `self.advanced` (they were only created in the old `_build_ui`, already removed in Task 2 — grep to confirm none remain).

Run: `grep -n "_scrollable\|_toggle_adv\|self.advanced\|adv_btn\|adv_shown\|_build_trim_panel" leike.py`
Expected: no matches.

- [ ] **Step 2: Verify.** `py_compile` clean; launch OK; `pytest tests/ -q` → 42 passed.

- [ ] **Step 3: Commit.**
```bash
git add leike.py
git commit -m "refactor: drop the scroll column and More-options scaffolding"
```

---

### Task 4: Structural test

**Files:** Create `tests/test_ui_structure.py`.

- [ ] **Step 1: Write the test.**

```python
def test_tabs_and_widgets(leike):
    app = leike["App"]()
    try:
        tabs = [app.notebook.tab(i, "text") for i in app.notebook.tabs()]
        assert tabs == ["Crop", "Effects", "Overlay", "Audio", "Export"]
        # every variable _settings() reads must still exist
        for name in ("scale_var", "crf_var", "fmt_var", "fast_trim_var",
                     "hw_var", "gif_fps_var", "mute_var", "volume_var",
                     "audio_only_var", "speed_var", "fill_var", "effect_var",
                     "loop_var", "bright_var", "contrast_var", "satur_var",
                     "gray_var", "denoise_var", "sharpen_var", "stabilize_var",
                     "text_var", "wm_pos_var", "text_pos_var", "size_var"):
            assert hasattr(app, name), name
        # the move: trim + export footer present
        assert app.export_btn is not None and app.trim_label is not None
    finally:
        app.destroy()
```

- [ ] **Step 2: Run it.** `python -m pytest tests/test_ui_structure.py -q` → 1 passed. (If a name is missing, the move broke a variable — fix the re-home in Task 2.)

- [ ] **Step 3: Commit.**
```bash
git add tests/test_ui_structure.py
git commit -m "test: structural check for tabs and settings variables"
```

---

### Task 5: Polish pass

**Files:** Modify `leike.py`.

- [ ] **Step 1: Apply section labels and spacing.** In each tab panel, replace the plain `ttk.Label(... )` group headers with the `Section.TLabel` style and uppercase text (e.g., `ttk.Label(box, text="TRANSFORM", style="Section.TLabel")`). Ensure consistent `pady=(0, 8)` between stacked panels and `padx`/`pady=6` inside groups. Remove the now-unused `ttk.LabelFrame` titles where a Section label reads cleaner, or keep `LabelFrame` — pick one consistently (recommend: keep `LabelFrame` for grouping, it already draws a titled border).

- [ ] **Step 2: Verify.** Launch and confirm spacing looks even; `pytest tests/ -q` → all pass.

- [ ] **Step 3: Commit.**
```bash
git add leike.py
git commit -m "style: consistent section labels and spacing"
```

---

### Task 6: Build, visual check, and ship v2.0

**Files:** Modify `installer/Leike.iss` (version), build artifacts.

- [ ] **Step 1: Bump version** in `installer/Leike.iss`: `#define MyAppVersion "2.0"`.
- [ ] **Step 2: Build** exe + portable zip + installer (kill running instances first):
```powershell
python -m PyInstaller --noconfirm --onefile --windowed --name Leike --icon leike.ico --add-data "leike.ico;." --collect-all tkinterdnd2 leike.py
Copy-Item .\dist\Leike.exe .\portable\Leike -Force
Compress-Archive .\portable\Leike .\dist\Leike-portable-win64.zip -Force
cmd /c Build-installer.bat
```
- [ ] **Step 3: Visual confirmation** — launch `dist\Leike.exe`, load a video, click through all five tabs, run an export. Confirm output is correct and the UI matches the spec.
- [ ] **Step 4: Commit + release.**
```bash
git add installer/Leike.iss Leike.spec
git commit -m "build: bump to 2.0 (UI modernization)"
git push origin main
gh release create v2.0 .\dist\Leike-Setup.exe .\dist\Leike-portable-win64.zip .\dist\Leike.exe --title "v2.0 - modern tabbed UI"
```

---

## Self-review notes
- **Spec coverage:** header (Task 2), left preview+trim (Task 2 `_build_trim_row`), notebook + 5 tabs + persistent footer (Task 2), tab re-homing incl. Effects=Transform+Adjust and Encoding-in-Export (Task 2 Step 3), Notebook/Accent styles (Task 1), remove scroll/More-options (Task 3), flat-constraint honored (no rounded/shadow code anywhere). ✔
- **Variable continuity:** Task 4 asserts all `_settings()` variables survive the move — the one real risk of re-homing. ✔
- **No logic change:** `build_commands`/`_settings`/filtergraph untouched; 42 existing tests remain the regression guard. ✔
- **Risk:** Task 2 is large (one cohesive `_build_ui` rewrite — can't be half-done). Mitigation: the panel bodies are reused verbatim (only parent/grid change), and the structural + full suite + launch checks catch breakage immediately.
