# About Dialog + Check for Updates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a themed **About** dialog (header button) showing version, links, ffmpeg version, and license info, with a manual **Check for updates** button that compares the running version against the latest GitHub release.

**Architecture:** A new `APP_VERSION` constant + three pure, unit-tested version helpers (`_parse_version`, `_is_newer`, `_latest_tag_from_json`); a thin `fetch_latest_tag()` network wrapper; a reusable module-level `_dark_titlebar(win)` (factored out of the App method) so the dialog gets the dark titlebar too; and App methods that build the modal dialog and run the threaded update check.

**Tech Stack:** Python 3 + tkinter (single file `leike.py`), `urllib` (GitHub API), `webbrowser` (links), pytest for the pure helpers.

**Spec:** `docs/superpowers/specs/2026-06-14-leike-about-updates-design.md`

---

## File structure

- `leike.py` — the app (single file). Gains: `import webbrowser`; the
  `APP_VERSION` / `GITHUB_REPO` / `SITE_URL` / `REPO_URL` / `RELEASES_URL` /
  `LATEST_API` constants; pure helpers `_parse_version` / `_is_newer` /
  `_latest_tag_from_json`; `fetch_latest_tag`; a module-level `_dark_titlebar`;
  and App methods `_show_about` / `_ffmpeg_version` / `_open_licenses` /
  `_open_path` / `_check_updates` / `_update_result`, plus the header **About**
  button.
- `tests/test_about.py` — NEW: unit tests for the three pure helpers.
- `installer/Leike.iss` — version bump to 2.5 (Task 4).
- `README.md` — a one-line feature note (Task 4).

Run tests from the repo root: `python -m pytest tests/ -q` (currently 88 passed).

---

## Task 1: Constants + pure version helpers (TDD)

**Files:**
- Modify: `leike.py` (top-level constants area, near `FORMATS`; helpers near the
  other module-level pure functions, e.g. after `_target_size_supported`)
- Create: `tests/test_about.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_about.py
def test_parse_version(leike):
    f = leike["_parse_version"]
    assert f("v2.4.1") == (2, 4, 1)
    assert f("2.5") == (2, 5)
    assert f("v3") == (3,)
    assert f("") == ()
    assert f("garbage") == ()
    assert f(None) == ()

def test_is_newer(leike):
    f = leike["_is_newer"]
    assert f("v2.5", "2.4.1") is True
    assert f("2.4.1", "2.4.1") is False
    assert f("2.4", "2.4.1") is False          # 2.4.0 < 2.4.1
    assert f("v2.10", "v2.9") is True           # numeric, not lexical
    assert f("2.5", "2.5.0") is False           # equal after padding

def test_latest_tag_from_json(leike):
    f = leike["_latest_tag_from_json"]
    assert f({"tag_name": "v2.5"}) == "v2.5"
    assert f({}) is None
    assert f({"tag_name": ""}) is None
    assert f([]) is None
```

- [ ] **Step 2: Run them — expect failure**

Run: `python -m pytest tests/test_about.py -q`
Expected: FAIL (`KeyError: '_parse_version'`).

- [ ] **Step 3: Add the constants**

In `leike.py`, near the top-level config constants (just after the `FORMATS`
list is a good spot), add:

```python
APP_VERSION = "2.5"          # keep in sync with installer/Leike.iss MyAppVersion
GITHUB_REPO = "Ville-Mattila/Leike"
SITE_URL = "https://ville-mattila.github.io/Leike/"
REPO_URL = f"https://github.com/{GITHUB_REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
```

- [ ] **Step 4: Add the pure helpers**

Add as module-level functions (place after `_target_size_supported`):

```python
def _parse_version(s):
    """'v2.4.1' / '2.5' -> (2, 4, 1) / (2, 5). Empty tuple on garbage/None."""
    s = (s or "").strip().lstrip("vV")
    parts = []
    for p in s.split("."):
        m = re.match(r"\d+", p)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def _is_newer(latest, current):
    """True if version string `latest` is strictly newer than `current`."""
    a, b = _parse_version(latest), _parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _latest_tag_from_json(data):
    """Extract tag_name from a parsed /releases/latest response, or None."""
    if isinstance(data, dict):
        tag = data.get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    return None
```

- [ ] **Step 5: Run them — expect pass**

Run: `python -m pytest tests/test_about.py -q`
Expected: all pass.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: 91 passed (88 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add leike.py tests/test_about.py
git commit -m "feat: app version + pure version-compare helpers for update check"
```

---

## Task 2: `fetch_latest_tag` + reusable `_dark_titlebar`

**Why:** The dialog needs a network fetch (run-verified, not unit-tested) and the
dark titlebar applied to a `Toplevel`. Factor the existing App titlebar logic into
a module helper so both the main window and the dialog use it.

**Files:**
- Modify: `leike.py` — add `import webbrowser`; add `fetch_latest_tag`; add
  module-level `_dark_titlebar(win)`; make `App._apply_dark_titlebar` delegate.

- [ ] **Step 1: Add the webbrowser import**

At the top of `leike.py`, with the other stdlib imports, add:

```python
import webbrowser
```

- [ ] **Step 2: Add `fetch_latest_tag`**

Add as a module-level function (near `_latest_tag_from_json`):

```python
def fetch_latest_tag(url=LATEST_API, timeout=8):
    """Return the latest release tag (e.g. 'v2.5') or None on any error
    (offline, timeout, rate-limit, malformed JSON)."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Leike"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _latest_tag_from_json(json.loads(r.read().decode("utf-8")))
    except Exception:
        return None
```

- [ ] **Step 3: Extract `_dark_titlebar(win)` and delegate**

Add a module-level function (place just above the `App` class):

```python
def _dark_titlebar(win):
    """Give a Tk window a dark Windows title bar (DWM immersive dark mode),
    painted to match BASE_BG. No-op off Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = (ctypes.windll.user32.GetParent(win.winfo_id())
                or win.winfo_id())
        for attr in (20, 19):   # 20 = Win10 1903+/Win11, 19 = older builds
            val = ctypes.c_int(1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
        r, g, b = (int(BASE_BG[i:i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_int(r | (g << 8) | (b << 16))   # 0x00BBGGRR
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
        win.withdraw()
        win.deiconify()
    except Exception:
        pass
```

Then replace the body of `App._apply_dark_titlebar` (currently the full DWM
implementation, ~lines 1345-1370) with a one-line delegate:

```python
    def _apply_dark_titlebar(self):
        _dark_titlebar(self)
```

- [ ] **Step 4: Verify the main window still gets a dark titlebar**

Run: `python leike.py` — the main window's title bar is still dark (unchanged
behavior). Also `python -c "import ast; ast.parse(open('leike.py',encoding='utf-8').read())"`
→ Syntax OK, and `python -m pytest tests/ -q` → 91 passed.

Optional live check of the fetch:
`PYTHONIOENCODING=utf-8 python -c "import leike; print(leike.fetch_latest_tag())"`
→ prints the current latest tag (e.g. `v2.4.1`) when online.

- [ ] **Step 5: Commit**

```bash
git add leike.py
git commit -m "feat: fetch_latest_tag + reusable _dark_titlebar helper"
```

---

## Task 3: About button + dialog + update check (UI)

**Files:**
- Modify: `leike.py` — header (`_build_ui`, ~line 1414); add `_show_about`,
  `_ffmpeg_version`, `_open_licenses`, `_open_path`, `_check_updates`,
  `_update_result`.

- [ ] **Step 1: Add the About button to the header**

In `_build_ui`, the header currently grids `Open…` (col 0) and `file_label`
(col 1, expanding). After the `self.file_label.grid(...)` line, add:

```python
        ttk.Button(header, text="About", command=self._show_about).grid(
            row=0, column=2, sticky="e", padx=(8, 0))
```

- [ ] **Step 2: Add the dialog builder + helpers**

Add these methods to `App`:

```python
    def _ffmpeg_version(self):
        try:
            r = run_capture([FFMPEG, "-version"])
            line = (r.stdout or "").splitlines()[0] if r.stdout else ""
            return line[:60] if line else "ffmpeg: version unknown"
        except OSError:
            return "ffmpeg not found"

    @staticmethod
    def _open_path(p):
        try:
            if os.name == "nt":
                os.startfile(p)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except OSError:
            pass

    def _open_licenses(self):
        base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))
        groups = [("LICENSE.txt", "LICENSE"),
                  ("THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.md")]
        opened = False
        for names in groups:
            for n in names:
                p = os.path.join(base, n)
                if os.path.exists(p):
                    self._open_path(p)
                    opened = True
                    break
        if not opened:
            webbrowser.open(f"{REPO_URL}/blob/main/LICENSE")

    def _check_updates(self):
        self._update_btn.config(state="disabled")
        self._update_status.config(text="Checking…", foreground=MUTED)
        self._download_btn.grid_remove()

        def work():
            tag = fetch_latest_tag()
            self.after(0, lambda: self._update_result(tag))

        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, tag):
        if getattr(self, "_update_btn", None) and self._update_btn.winfo_exists():
            self._update_btn.config(state="normal")
        if not (getattr(self, "_update_status", None)
                and self._update_status.winfo_exists()):
            return
        if not tag:
            self._update_status.config(
                text="Couldn't check for updates (no connection?)",
                foreground=MUTED)
        elif _is_newer(tag, APP_VERSION):
            self._update_status.config(
                text=f"Update available: {tag}", foreground=GOLD)
            self._download_btn.grid()
        else:
            self._update_status.config(
                text=f"You're on the latest version (v{APP_VERSION}).",
                foreground=MUTED)

    def _show_about(self):
        if getattr(self, "_about_win", None) and self._about_win.winfo_exists():
            self._about_win.lift()
            self._about_win.focus_force()
            return
        win = tk.Toplevel(self, bg=BASE_BG)
        self._about_win = win
        win.title("About Leike")
        win.resizable(False, False)
        try:
            if os.path.exists(ICON_FILE):
                win.iconbitmap(ICON_FILE)
        except Exception:
            pass
        win.transient(self)
        _dark_titlebar(win)

        pad = ttk.Frame(win, padding=20)
        pad.grid(sticky="nsew")
        ttk.Label(pad, text="Leike", font=("Segoe UI", 22, "bold"),
                  foreground=GOLD, background=BASE_BG).grid(
            row=0, column=0, sticky="w")
        ttk.Label(pad, text=f"version {APP_VERSION}", foreground=MUTED).grid(
            row=1, column=0, sticky="w")
        ttk.Label(pad, text="A small, quick front-end for ffmpeg.",
                  foreground=TEXT).grid(row=2, column=0, sticky="w", pady=(2, 12))

        links = ttk.Frame(pad)
        links.grid(row=3, column=0, sticky="w", pady=(0, 10))
        ttk.Button(links, text="GitHub",
                   command=lambda: webbrowser.open(REPO_URL)).grid(row=0, column=0)
        ttk.Button(links, text="Website",
                   command=lambda: webbrowser.open(SITE_URL)).grid(
            row=0, column=1, padx=(8, 0))

        ttk.Label(pad, text=self._ffmpeg_version(), foreground=MUTED).grid(
            row=4, column=0, sticky="w", pady=(0, 12))

        ttk.Label(pad, text="Leike is MIT-licensed; bundled ffmpeg is GPLv3.",
                  foreground=TEXT, wraplength=360, justify="left").grid(
            row=5, column=0, sticky="w")
        ttk.Button(pad, text="View licenses",
                   command=self._open_licenses).grid(
            row=6, column=0, sticky="w", pady=(4, 14))

        upd = ttk.Frame(pad)
        upd.grid(row=7, column=0, sticky="ew")
        self._update_btn = ttk.Button(upd, text="Check for updates",
                                      command=self._check_updates)
        self._update_btn.grid(row=0, column=0, sticky="w")
        self._update_status = ttk.Label(upd, text="", foreground=MUTED)
        self._update_status.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._download_btn = ttk.Button(
            upd, text="⬇  Download", style="Accent.TButton",
            command=lambda: webbrowser.open(RELEASES_URL))
        self._download_btn.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._download_btn.grid_remove()

        ttk.Button(pad, text="Close", command=win.destroy).grid(
            row=8, column=0, sticky="e", pady=(16, 0))

        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()
```

- [ ] **Step 3: Verify by running**

Run: `python leike.py`
Verify: an **About** button shows at the header's right. Clicking it opens a
themed modal dialog (dark titlebar) with the version, tagline, GitHub/Website
buttons (open in browser), the ffmpeg version line, the license summary +
**View licenses** (opens the license file(s) — in dev, repo `LICENSE` +
`THIRD_PARTY_NOTICES.md`), and **Check for updates** (shows "Checking…" then a
result; with `APP_VERSION="2.5"` and the latest release `v2.4.1`, it reports
"You're on the latest version"; temporarily set `APP_VERSION="2.3"` to confirm
the "Update available" + **Download** path, then restore `"2.5"`). Esc / Close
dismisses it; re-clicking About while open just refocuses.

Also: `python -c "import ast; ast.parse(open('leike.py',encoding='utf-8').read())"`
→ Syntax OK; `python -m pytest tests/ -q` → 91 passed.

- [ ] **Step 4: Commit**

```bash
git add leike.py
git commit -m "feat: About dialog with links, licenses, and Check for updates"
```

---

## Task 4: Docs, version bump, ship v2.5

**Files:**
- Modify: `README.md` (feature note), `installer/Leike.iss` (version).

- [ ] **Step 1: README feature note**

In `README.md`, under **## Features**, add:

```markdown
- **About dialog** (header button) with app/ffmpeg versions, license info, and a
  manual **Check for updates** that compares against the latest GitHub release.
```

- [ ] **Step 2: Bump the installer version to 2.5**

In `installer/Leike.iss` set `#define MyAppVersion "2.5"`. (`APP_VERSION` in
`leike.py` is already `"2.5"` from Task 1 — the two must match.)

Confirm both: `grep -n "MyAppVersion" installer/Leike.iss` and
`grep -n "^APP_VERSION" leike.py` both show 2.5.

- [ ] **Step 3: Commit**

```bash
git add README.md installer/Leike.iss
git commit -m "release: About dialog + update check — v2.5"
```

- [ ] **Step 4: Build + ship (with user go-ahead)**

Build `dist/Leike.exe` (PyInstaller line from the release recipe), the installer
(`Build-installer.bat`), and the portable zip (refresh `portable/Leike/Leike.exe`
then `Compress-Archive`). Push `main`, tag `v2.5`, push the tag (triggers the
mac/linux CI), and `gh release create v2.5 --verify-tag` with the three Windows
artifacts + notes; CI attaches mac/linux. (Outward-facing — only on explicit
go-ahead, per the project workflow.)

---

## Self-review notes

- **Spec coverage:** constants + `APP_VERSION` (T1); pure `_parse_version` /
  `_is_newer` / `_latest_tag_from_json` + tests (T1); `fetch_latest_tag` +
  `_dark_titlebar` (T2); header About button + themed dialog with version, links,
  ffmpeg line, license summary + View-licenses, Check-for-updates + Download, Esc/
  Close, single-instance guard (T3); manual-only check (no startup call — T3);
  ship v2.5 (T4). Every spec section maps to a task. ✔
- **Type consistency:** `_parse_version`/`_is_newer`/`_latest_tag_from_json`/
  `fetch_latest_tag`/`_dark_titlebar` names are defined once and reused verbatim;
  dialog handles `self._about_win`/`_update_btn`/`_update_status`/`_download_btn`
  are consistent across `_show_about`/`_check_updates`/`_update_result`. ✔
- **Out of scope (per spec):** auto-update/install, startup auto-check, native
  menu bar, in-app license text panel. Not added. ✔
- **Risk:** the `_apply_dark_titlebar` → `_dark_titlebar(self)` refactor touches
  the working main-window path; T2 Step 4 re-verifies the main window still gets a
  dark titlebar before building on it.
```
