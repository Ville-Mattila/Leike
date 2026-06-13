"""Headless tests for the responsive-preview coordinate mapping."""


def test_coordinate_roundtrip(leike):
    app = leike["App"]()
    try:
        app.src_w, app.src_h = 1920, 1080
        app.scale, app.off_x, app.off_y = 0.5, 30, 10
        app.disp_w, app.disp_h = 960, 540
        cx, cy = app._s2c(100, 200)
        assert (cx, cy) == (80, 110)            # 30+50, 10+100
        sx, sy = app._c2s(cx, cy)
        assert abs(sx - 100) < 1e-6 and abs(sy - 200) < 1e-6
        # out-of-frame canvas points clamp to the source bounds
        assert app._c2s(-1000, -1000) == (0, 0)
        assert app._c2s(99999, 99999) == (1920, 1080)
    finally:
        app.destroy()


def test_recompute_letterbox(leike):
    app = leike["App"]()
    try:
        app.src_w, app.src_h = 1920, 1080

        class StubCanvas:
            def winfo_width(self):
                return 800

            def winfo_height(self):
                return 800

        app.canvas = StubCanvas()
        app._recompute_display()
        # 16:9 into an 800x800 canvas is width-limited
        assert abs(app.scale - 800 / 1920) < 1e-9
        assert app.disp_w == 800
        assert app.disp_h == int(1080 * 800 / 1920)   # 450
        assert app.off_x == 0
        assert app.off_y == (800 - 450) // 2          # vertical letterbox
    finally:
        app.destroy()
