def test_even(leike):
    assert leike["even"](721) == 720
    assert leike["even"](720) == 720
    assert leike["even"](0) == 0


def test_fmt_and_parse_roundtrip(leike):
    assert leike["parse_time"]("1:02:03.250") == 3723.25
    assert leike["fmt_time"](3723.25) == "1:02:03.250"


def test_parse_time_forms(leike):
    assert leike["parse_time"]("90.5") == 90.5
    assert leike["parse_time"]("01:15.250") == 75.25
    assert leike["parse_time"]("") is None
