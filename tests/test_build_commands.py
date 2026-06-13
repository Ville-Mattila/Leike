def make(leike, **kw):
    S = leike["ExportSettings"]
    base = dict(input_path="in.mp4", output_path="out.mp4",
                src_w=1920, src_h=1080, start=1.0, end=4.0)
    base.update(kw)
    return S(**base)


def test_baseline_single_pass(leike):
    cmds = leike["build_commands"](make(leike))
    assert len(cmds) == 1
    c = cmds[0]
    j = " ".join(c)
    assert "-ss 1.000" in j and "-t 3.000" in j      # dur = end - start
    assert "format=yuv420p" in j
    assert "libx264" in j and "-crf 20" in j
    assert "+faststart" in j and "aac" in j
    assert c[-1] == "out.mp4"


def test_crop_no_extra_scale(leike):
    # crop 1280x720 with a 1280 cap: longest side already at the cap -> no scale
    cmds = leike["build_commands"](make(leike, crop=(10, 20, 1280, 720), scale_cap=1280))
    j = " ".join(cmds[0])
    assert "crop=1280:720:10:20" in j
    assert "scale=" not in j


def test_scale_when_capped(leike):
    # no crop, 1920x1080 source, cap 1280 -> downscale to 1280x720
    cmds = leike["build_commands"](make(leike, scale_cap=1280))
    assert "scale=1280:720" in " ".join(cmds[0])


def test_crf_passthrough(leike):
    cmds = leike["build_commands"](make(leike, crf=18))
    assert "-crf 18" in " ".join(cmds[0])


def test_odd_dims_snapped_even(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 641, 361)))
    assert "crop=640:360:0:0" in " ".join(cmds[0])
