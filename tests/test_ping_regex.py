from wifi_observer import _LAT_RE


def test_ping_time_equals():
    m = _LAT_RE.search("64 bytes from 8.8.8.8: time=23.4 ms")

    assert m is not None
    assert float(m.group(1)) == 23.4


def test_ping_time_less_than():
    m = _LAT_RE.search("64 bytes from 8.8.8.8: time<1 ms")

    assert m is not None
    assert float(m.group(1)) == 1.0


def test_ping_integer():
    m = _LAT_RE.search("time=10 ms")

    assert m is not None
    assert float(m.group(1)) == 10.0


def test_invalid_ping():
    assert _LAT_RE.search("Destination Host Unreachable") is None