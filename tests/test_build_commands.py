def make(leike, **kw):
    S = leike["ExportSettings"]
    base = dict(input_path="in.mp4", output_path="out.mp4",
                src_w=1920, src_h=1080, start=1.0, end=4.0)
    base.update(kw)
    return S(**base)


def test_trim_only_is_lossless_copy(leike):
    cmds = leike["build_commands"](make(leike))      # no crop/scale -> passthrough
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "-c copy" in j
    assert "-vf" not in cmds[0]
    assert "-ss 1.000" in j and "-t 3.000" in j      # dur = end - start
    assert "+faststart" in j


def test_fast_trim_off_reencodes(leike):
    cmds = leike["build_commands"](make(leike, fast_trim=False))
    j = " ".join(cmds[0])
    assert "libx264" in j and "-crf 20" in j and "format=yuv420p" in j
    assert "-c copy" not in j


def test_crop_reencodes_with_crop_filter(leike):
    cmds = leike["build_commands"](make(leike, crop=(10, 20, 1280, 720), scale_cap=1280))
    j = " ".join(cmds[0])
    assert "crop=1280:720:10:20" in j     # cropped 1280 already at the 1280 cap
    assert "scale=" not in j
    assert "-c copy" not in j


def test_scale_when_capped(leike):
    cmds = leike["build_commands"](make(leike, scale_cap=1280))
    assert "scale=1280:720" in " ".join(cmds[0])


def test_crf_propagates(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), crf=18))
    assert "-crf 18" in " ".join(cmds[0])


def test_odd_dims_snapped_even(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 641, 361)))
    assert "crop=640:360:0:0" in " ".join(cmds[0])


def test_hw_encoder_nvenc(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), hw=True))
    j = " ".join(cmds[0])
    assert "h264_nvenc" in j and "-cq 20" in j
    assert "libx264" not in j


def test_sw_encoder_default(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), hw=False))
    j = " ".join(cmds[0])
    assert "libx264" in j and "-crf 20" in j


def test_gif_two_pass(leike):
    cmds = leike["build_commands"](make(leike, fmt="gif", output_path="out.gif"))
    assert len(cmds) == 2
    assert "palettegen" in " ".join(cmds[0])
    assert "paletteuse" in " ".join(cmds[1])
    assert "fps=15" in " ".join(cmds[0])
    assert "-c:a" not in " ".join(cmds[1])        # GIF has no audio


def test_gif_fps_setting(leike):
    cmds = leike["build_commands"](make(leike, fmt="gif", gif_fps=24))
    assert "fps=24" in " ".join(cmds[0])


def test_webm_vp9_opus(leike):
    cmds = leike["build_commands"](make(leike, fmt="webm", output_path="out.webm"))
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "libvpx-vp9" in j and "libopus" in j
    assert "-c copy" not in j        # webm always re-encodes, even trim-only


def test_size_target_two_pass(leike):
    cmds = leike["build_commands"](make(leike, target_size_mb=10.0))   # 3.0s clip
    assert len(cmds) == 2
    j0, j1 = " ".join(cmds[0]), " ".join(cmds[1])
    assert "-pass 1" in j0 and "-pass 2" in j1
    expected = int(((10.0 * 8192) / 3.0 - 128) * 0.97)
    assert f"-b:v {expected}k" in j1


def test_size_target_overrides_passthrough(leike):
    # no crop would normally be a -c copy passthrough; a size target forces 2-pass
    cmds = leike["build_commands"](make(leike, target_size_mb=5.0))
    assert len(cmds) == 2
    assert "-c copy" not in " ".join(cmds[0])


def test_mute_drops_audio(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), mute=True))
    j = " ".join(cmds[0])
    assert "-an" in j and "aac" not in j


def test_volume_filter(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), volume=1.5))
    assert "volume=1.500" in " ".join(cmds[0])


def test_mute_disables_passthrough(leike):
    # mute on a trim-only job can't stream-copy; must re-encode with -an
    cmds = leike["build_commands"](make(leike, mute=True))
    j = " ".join(cmds[0])
    assert "-c copy" not in j and "-an" in j


def test_audio_only_mp3(leike):
    cmds = leike["build_commands"](make(leike, audio_only=True, output_path="out.mp3"))
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "-vn" in j and "libmp3lame" in j


def test_rotate_and_flip(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), rotate=90, flip_h=True))[0])
    assert "transpose=1" in j and "hflip" in j


def test_speed_video_and_audio(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), speed=2.0))[0])
    assert "setpts=0.5000*PTS" in j and "atempo=2.0000" in j


def test_speed_slow_needs_two_atempo(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), speed=0.25))[0])
    assert "setpts=4.0000*PTS" in j and j.count("atempo=0.5") == 2


def test_fade_in_out(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), fade_in=0.5, fade_out=1.0))[0])
    assert "fade=t=in:st=0:d=0.50" in j
    assert "fade=t=out:st=2.00:d=1.00" in j   # dur 3.0 -> out starts at 2.0


def test_reverse_is_linear(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), reverse=True))
    assert "-vf" in cmds[0]
    j = " ".join(cmds[0])
    assert "reverse" in j and "areverse" in j


def test_blur_pad_uses_filter_complex(leike):
    cmds = leike["build_commands"](make(leike, fill_mode="blur_pad",
                                        target_aspect=9 / 16))
    assert "-filter_complex" in cmds[0]
    j = " ".join(cmds[0])
    assert "gblur" in j and "overlay" in j and "-map" in j


def test_boomerang_concat(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), boomerang=True))[0])
    assert "concat=n=2" in j


def test_loop_concat(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), loop=3))[0])
    assert "split=3" in j and "concat=n=3" in j


def test_transform_disables_passthrough(leike):
    j = " ".join(leike["build_commands"](make(leike, rotate=90))[0])
    assert "-c copy" not in j and "transpose=1" in j


def test_color_eq(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720),
             brightness=0.1, contrast=1.2, saturation=1.5))[0])
    assert "eq=brightness=0.100:contrast=1.200:saturation=1.500" in j


def test_grayscale_denoise_sharpen(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720),
             grayscale=True, denoise=True, sharpen=True))[0])
    assert "hue=s=0" in j and "hqdn3d" in j and "unsharp" in j


def test_adjust_disables_passthrough(leike):
    j = " ".join(leike["build_commands"](make(leike, grayscale=True))[0])
    assert "-c copy" not in j and "hue=s=0" in j


def test_text_drawtext(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), text="Hello"))[0])
    assert "drawtext" in j and "textfile" in j


def test_subtitles_filter(leike):
    j = " ".join(leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720), subtitles_path="C:/x/sub.srt"))[0])
    assert "subtitles=" in j


def test_watermark_overlay(leike):
    cmds = leike["build_commands"](
        make(leike, crop=(0, 0, 1280, 720),
             watermark_path="C:/x/logo.png", watermark_pos="br"))
    assert "-filter_complex" in cmds[0]
    assert cmds[0].count("-i") == 2          # main input + watermark
    assert "overlay=" in " ".join(cmds[0])


def test_overlay_disables_passthrough(leike):
    j = " ".join(leike["build_commands"](make(leike, text="Hi"))[0])
    assert "-c copy" not in j
