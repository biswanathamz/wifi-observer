"""Unit tests for WiFi Observer's pure helpers and statistics.

These are network-free and import-only (no live pings / no /proc reads), so they
run anywhere in CI. The broader suite is tracked in issue #9.
"""
import time

import wifi_observer as wo


def test_fmt_duration():
    assert wo.fmt_duration(0) == "00:00"
    assert wo.fmt_duration(65) == "01:05"
    assert wo.fmt_duration(3661) == "01:01:01"


def test_stddev():
    assert wo._stddev(0, 0.0, 0.0) == 0.0          # no samples
    assert wo._stddev(1, 5.0, 25.0) == 0.0         # one sample
    # values {2, 4}: mean 3, population variance 1 -> stddev 1
    assert abs(wo._stddev(2, 6.0, 20.0) - 1.0) < 1e-9


def test_fmt_ms_and_dbm():
    assert wo.fmt_ms(None) == "--"
    assert wo.fmt_ms(23.4) == "23.4"
    assert wo.fmt_dbm(None) == "--"
    assert wo.fmt_dbm(-47.6) == "-48"


def test_signal_label():
    assert wo.signal_label(None) == "n/a"
    assert wo.signal_label(-40) == "Excellent"
    assert wo.signal_label(-55) == "Good"
    assert wo.signal_label(-65) == "Fair"
    assert wo.signal_label(-72) == "Weak"
    assert wo.signal_label(-90) == "Very weak"


def test_stability_label():
    assert wo.stability_label(0.0, 1) == "…"        # too few samples
    assert wo.stability_label(1.0, 10) == "STABLE"
    assert wo.stability_label(4.0, 10) == "FLUCTUATING"
    assert wo.stability_label(9.0, 10) == "UNSTABLE"


def test_latency_regex():
    line = "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=23.4 ms"
    assert wo._LAT_RE.search(line).group(1) == "23.4"
    assert wo._LAT_RE.search("time<1 ms").group(1) == "1"
    assert wo._LAT_RE.search("no latency here") is None


def test_spark_series():
    assert wo.spark_series([], 10) == ""
    rendered = wo.spark_series([1.0, 2.0, None, 3.0], 10)
    assert len(rendered) == 4
    assert rendered[2] == "·"                        # missing value marker


def _probe(ts, up, latency, dbm):
    return wo.Probe(ts=ts, time="", internet_up=up, latency_ms=latency,
                    signal_dbm=dbm, signal_quality=None, ssid="test")


def test_stats_internet_and_signal():
    st = wo.Stats()
    t = time.time()
    st.add(_probe(t, True, 10.0, -50.0))
    st.add(_probe(t + 1, False, None, -60.0))
    st.add(_probe(t + 2, True, 30.0, -40.0))

    assert st.total == 3
    assert st.up_count == 2
    assert st.down_count == 1
    assert abs(st.uptime_pct - (2 / 3 * 100)) < 1e-9
    assert abs(st.loss_pct - (1 / 3 * 100)) < 1e-9
    assert st.lat_avg == 20.0
    assert st.lat_min == 10.0
    assert st.lat_max == 30.0
    assert st.outages == 1                            # one down stretch
    assert st.sig_min == -60.0
    assert st.sig_max == -40.0
    assert st.sig_avg == -50.0
