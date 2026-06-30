#!/usr/bin/env python3
"""wifi_observer_plot.py — render graphs from WiFi Observer data using matplotlib.

The live program (wifi_observer.py) imports `build_figure` from here when you
press [g], so you normally never run this script by hand. It also works
standalone:

    python3 wifi_observer_plot.py [LOGFILE] [-o OUTPUT.png] [--show]

If LOGFILE is omitted, the newest logs/wifi-*.jsonl is used. Produces two
stacked charts sharing a time axis:
    1. Internet latency over time (outages marked in red).
    2. WiFi signal strength (dBm) over time, with quality reference lines.

Requires matplotlib:  pip install matplotlib
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys


def load(path: str) -> list[dict]:
    """Read a JSON-lines log into a list of dicts."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def newest_log() -> str | None:
    # Search both logs/wifi-*.jsonl and logs/<date>/wifi-*.jsonl.
    found = set(glob.glob(os.path.join("logs", "wifi-*.jsonl")))
    found |= set(glob.glob(os.path.join("logs", "**", "wifi-*.jsonl"), recursive=True))
    files = sorted(found, key=os.path.getmtime)
    return files[-1] if files else None


def build_figure(rows: list[dict], out_path: str, show: bool = False) -> str:
    """Render `rows` to an image at `out_path`. Returns the path.

    Raises ImportError if matplotlib is unavailable (handled by callers).
    """
    import matplotlib
    if not show:
        matplotlib.use("Agg")               # headless: save without a display
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    times = [dt.datetime.fromtimestamp(r["ts"]) for r in rows]
    lat = [r.get("latency_ms") if r.get("internet_up") else None for r in rows]
    lat_y = [v if v is not None else float("nan") for v in lat]
    out_t = [t for t, r in zip(times, rows) if not r.get("internet_up")]
    sig = [r.get("signal_dbm") for r in rows]
    sig_t = [t for t, v in zip(times, sig) if v is not None]
    sig_y = [v for v in sig if v is not None]
    ssid = next((r.get("ssid") for r in rows if r.get("ssid")), "?")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    fig.suptitle(f"WiFi Observer — {ssid}   ({len(rows)} samples)", fontweight="bold")

    # --- Internet latency ---
    ax1.plot(times, lat_y, color="#1f77b4", linewidth=1.2, label="latency (ms)")
    if out_t:
        ymax = max((v for v in lat if v is not None), default=1.0)
        ax1.scatter(out_t, [ymax] * len(out_t), color="red", marker="v", s=28,
                    zorder=5, label=f"outage ({len(out_t)})")
    ax1.set_ylabel("Internet latency (ms)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper right", fontsize=8)

    # --- WiFi signal ---
    if sig_y:
        ax2.plot(sig_t, sig_y, color="#2ca02c", linewidth=1.2, label="signal (dBm)")
        for lvl, col in [(-50, "#2ca02c"), (-67, "#ff7f0e"), (-75, "#d62728")]:
            ax2.axhline(lvl, color=col, linestyle="--", linewidth=0.7, alpha=0.5)
        ax2.legend(loc="upper right", fontsize=8)
    else:
        ax2.text(0.5, 0.5, "no WiFi signal data\n(/proc/net/wireless unavailable)",
                 ha="center", va="center", transform=ax2.transAxes, color="gray")
    ax2.set_ylabel("WiFi signal (dBm)")
    ax2.set_xlabel("Time")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    fig.savefig(out_path, dpi=120)
    if show:
        plt.show()
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Plot a WiFi Observer log with matplotlib.")
    ap.add_argument("logfile", nargs="?", help="JSON-lines log (default: newest in logs/)")
    ap.add_argument("-o", "--output", help="Output image path (default: <logfile>.png)")
    ap.add_argument("--show", action="store_true", help="Open an interactive window too")
    args = ap.parse_args(argv)

    path = args.logfile or newest_log()
    if not path:
        print("error: no log file given and none found in logs/", file=sys.stderr)
        return 1
    if not os.path.isfile(path):
        print(f"error: log file not found: {path}", file=sys.stderr)
        return 1

    rows = load(path)
    if not rows:
        print(f"error: no samples found in {path}", file=sys.stderr)
        return 1

    out = args.output or (os.path.splitext(path)[0] + ".png")
    try:
        build_figure(rows, out, show=args.show)
    except ImportError:
        print("error: matplotlib is required.  Install it with:\n    pip install matplotlib",
              file=sys.stderr)
        return 2
    print(f"saved graph → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
