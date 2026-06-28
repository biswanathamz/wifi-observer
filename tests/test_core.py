"""Unit tests for stats math, ping regex, and /proc/net/wireless parser."""

import math
import re
import time
import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import mock_open, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wifi_observer import (
    _stddev,
    Stats,
    Probe,
    _LAT_RE,
    read_wifi_signal,
    signal_label,
    stability_label,
)


def _make_probe(up: bool, latency: Optional[float] = None, signal: Optional[float] = None,
                ts: Optional[float] = None) -> Probe:
    return Probe(
        ts=ts if ts is not None else time.time(),
        time="2024-01-01T00:00:00",
        internet_up=up,
        latency_ms=latency,
        signal_dbm=signal,
        signal_quality=None,
        ssid="TestNet",
    )


# ---------------------------------------------------------------------------
# _stddev
# ---------------------------------------------------------------------------

class TestStddev(unittest.TestCase):
    def test_fewer_than_two_samples_returns_zero(self):
        self.assertEqual(_stddev(0, 0.0, 0.0), 0.0)
        self.assertEqual(_stddev(1, 5.0, 25.0), 0.0)

    def test_two_identical_values(self):
        # stddev of [10, 10] == 0
        self.assertAlmostEqual(_stddev(2, 20.0, 200.0), 0.0)

    def test_known_population_stddev(self):
        # values [2, 4, 4, 4, 5, 5, 7, 9] → pop-stddev = 2.0
        values = [2, 4, 4, 4, 5, 5, 7, 9]
        n = len(values)
        s = sum(values)
        ss = sum(v * v for v in values)
        self.assertAlmostEqual(_stddev(n, float(s), float(ss)), 2.0, places=10)

    def test_single_element_returns_zero(self):
        self.assertEqual(_stddev(1, 7.0, 49.0), 0.0)


# ---------------------------------------------------------------------------
# Stats math
# ---------------------------------------------------------------------------

class TestStatsUptime(unittest.TestCase):
    def test_uptime_pct_all_up(self):
        st = Stats()
        for _ in range(10):
            st.add(_make_probe(True, latency=20.0))
        self.assertAlmostEqual(st.uptime_pct, 100.0)
        self.assertAlmostEqual(st.loss_pct, 0.0)

    def test_uptime_pct_half(self):
        st = Stats()
        for _ in range(5):
            st.add(_make_probe(True, latency=10.0))
        for _ in range(5):
            st.add(_make_probe(False))
        self.assertAlmostEqual(st.uptime_pct, 50.0)
        self.assertAlmostEqual(st.loss_pct, 50.0)

    def test_uptime_pct_no_probes(self):
        st = Stats()
        self.assertEqual(st.uptime_pct, 0.0)
        self.assertEqual(st.loss_pct, 0.0)


class TestStatsLatency(unittest.TestCase):
    def test_lat_avg(self):
        st = Stats()
        st.add(_make_probe(True, latency=10.0))
        st.add(_make_probe(True, latency=30.0))
        self.assertAlmostEqual(st.lat_avg, 20.0)

    def test_lat_min_max(self):
        st = Stats()
        for ms in [5.0, 15.0, 10.0]:
            st.add(_make_probe(True, latency=ms))
        self.assertEqual(st.lat_min, 5.0)
        self.assertEqual(st.lat_max, 15.0)

    def test_lat_avg_none_when_no_probes(self):
        self.assertIsNone(Stats().lat_avg)

    def test_lat_jitter(self):
        # Two values [10, 30]: pop-stddev = 10
        st = Stats()
        st.add(_make_probe(True, latency=10.0))
        st.add(_make_probe(True, latency=30.0))
        self.assertAlmostEqual(st.lat_jitter, 10.0)


class TestStatsOutages(unittest.TestCase):
    def test_outage_count(self):
        st = Stats()
        t = 0.0
        st.add(_make_probe(True, ts=t)); t += 1
        st.add(_make_probe(False, ts=t)); t += 1   # outage 1 starts
        st.add(_make_probe(False, ts=t)); t += 1
        st.add(_make_probe(True, ts=t)); t += 1    # outage 1 ends
        st.add(_make_probe(False, ts=t)); t += 1   # outage 2 starts
        self.assertEqual(st.outages, 2)

    def test_downtime_tracked(self):
        st = Stats()
        t = 0.0
        st.add(_make_probe(False, ts=t)); t += 5
        st.add(_make_probe(False, ts=t))
        self.assertGreater(st.longest_outage_s, 0)


class TestStatsSignal(unittest.TestCase):
    def test_sig_avg(self):
        st = Stats()
        st.add(_make_probe(True, signal=-60.0))
        st.add(_make_probe(True, signal=-40.0))
        self.assertAlmostEqual(st.sig_avg, -50.0)

    def test_sig_avg_none_when_no_signal(self):
        st = Stats()
        st.add(_make_probe(True, latency=10.0))
        self.assertIsNone(st.sig_avg)

    def test_sig_std(self):
        st = Stats()
        st.add(_make_probe(True, signal=-60.0))
        st.add(_make_probe(True, signal=-40.0))
        # pop-stddev of [-60, -40] = 10
        self.assertAlmostEqual(st.sig_std, 10.0)


# ---------------------------------------------------------------------------
# Ping latency regex
# ---------------------------------------------------------------------------

class TestLatencyRegex(unittest.TestCase):
    def test_time_equals(self):
        line = "64 bytes from 8.8.8.8: icmp_seq=1 ttl=55 time=23.4 ms"
        m = _LAT_RE.search(line)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)), 23.4)

    def test_time_less_than(self):
        line = "64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time<1 ms"
        m = _LAT_RE.search(line)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)), 1.0)

    def test_no_match_on_timeout(self):
        line = "Request timeout for icmp_seq 1"
        self.assertIsNone(_LAT_RE.search(line))

    def test_fractional_ms(self):
        line = "64 bytes from x: time=0.123 ms"
        m = _LAT_RE.search(line)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)), 0.123)

    def test_space_after_equals(self):
        line = "time= 5.6 ms"
        m = _LAT_RE.search(line)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)), 5.6)


# ---------------------------------------------------------------------------
# /proc/net/wireless parser
# ---------------------------------------------------------------------------

PROC_NET_WIRELESS_SAMPLE = """\
Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   65.  -45.  -256.        0      0      0      0      0        0
"""

PROC_NET_WIRELESS_MULTI = """\
Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   65.  -45.  -256.        0      0      0      0      0        0
wlan1: 0000   50.  -60.  -256.        0      0      0      0      0        0
"""


class TestReadWifiSignal(unittest.TestCase):
    def test_parses_signal_and_quality(self):
        with patch("builtins.open", mock_open(read_data=PROC_NET_WIRELESS_SAMPLE)):
            level, quality = read_wifi_signal("wlan0")
        self.assertAlmostEqual(level, -45.0)
        # 65/70*100 ≈ 92.857…, clamped to 100 max
        self.assertAlmostEqual(quality, 65.0 / 70.0 * 100.0, places=3)

    def test_filters_by_iface(self):
        with patch("builtins.open", mock_open(read_data=PROC_NET_WIRELESS_MULTI)):
            level, quality = read_wifi_signal("wlan1")
        self.assertAlmostEqual(level, -60.0)

    def test_returns_none_on_oserror(self):
        with patch("builtins.open", side_effect=OSError("no file")):
            level, quality = read_wifi_signal("wlan0")
        self.assertIsNone(level)
        self.assertIsNone(quality)

    def test_wildcard_iface_returns_first(self):
        with patch("builtins.open", mock_open(read_data=PROC_NET_WIRELESS_MULTI)):
            level, quality = read_wifi_signal("?")
        self.assertAlmostEqual(level, -45.0)

    def test_quality_clamped_to_100(self):
        # quality raw value > 70 should clamp at 100%
        data = """\
Inter-|
 face |
wlan0: 0000   80.  -50.  -256.        0      0
"""
        with patch("builtins.open", mock_open(read_data=data)):
            level, quality = read_wifi_signal("wlan0")
        self.assertEqual(quality, 100.0)


# ---------------------------------------------------------------------------
# signal_label / stability_label
# ---------------------------------------------------------------------------

class TestSignalLabel(unittest.TestCase):
    def test_excellent(self):
        self.assertEqual(signal_label(-45.0), "Excellent")

    def test_good(self):
        self.assertEqual(signal_label(-55.0), "Good")

    def test_fair(self):
        self.assertEqual(signal_label(-63.0), "Fair")

    def test_weak(self):
        self.assertEqual(signal_label(-70.0), "Weak")

    def test_very_weak(self):
        self.assertEqual(signal_label(-85.0), "Very weak")

    def test_none(self):
        self.assertEqual(signal_label(None), "n/a")


if __name__ == "__main__":
    unittest.main()
