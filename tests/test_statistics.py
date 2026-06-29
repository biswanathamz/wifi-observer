from wifi_observer import Stats, Probe, stability_label


def probe(up=True, latency=20.0, signal=-50.0):
    return Probe(
        ts=1.0,
        time="2025-01-01T00:00:00",
        internet_up=up,
        latency_ms=latency if up else None,
        signal_dbm=signal,
        signal_quality=100.0,
        ssid="wifi",
    )


def test_uptime_and_loss():
    stats = Stats()

    stats.add(probe(True))
    stats.add(probe(True))
    stats.add(probe(False))

    assert round(stats.uptime_pct, 2) == round((2 / 3) * 100, 2)
    assert round(stats.loss_pct, 2) == round((1 / 3) * 100, 2)


def test_zero_jitter():
    stats = Stats()

    for _ in range(3):
        stats.add(probe(True, latency=20))

    assert stats.lat_jitter == 0


def test_signal_std():
    stats = Stats()

    for _ in range(3):
        stats.add(probe(signal=-50))

    assert stats.sig_std == 0


def test_stability_labels():
    assert stability_label(2.0, 5) == "STABLE"
    assert stability_label(4.0, 5) == "FLUCTUATING"
    assert stability_label(7.0, 5) == "UNSTABLE"