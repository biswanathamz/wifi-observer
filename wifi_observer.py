#!/usr/bin/env python3
"""WiFi Observer — terminal-based connectivity & signal monitor.

Each interval it measures two independent things:

  1. INTERNET  — pings a reliable host (default 8.8.8.8, Google DNS) to tell
     whether the internet is reachable, and how fast (latency, packet loss).
  2. WIFI SIGNAL — reads the radio signal strength in dBm from the adapter
     (/proc/net/wireless) to tell whether the WiFi link is strong and stable.

Every sample is appended to a JSON-lines log, and a summary JSON is written on
exit. Use plot.py to render graphs from the log with matplotlib.

Core uses the Python 3 stdlib + system `ping` only. See doc/SPEC.md.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Probe:
    ts: float                       # epoch seconds
    time: str                       # ISO-8601 local timestamp (for the log)
    internet_up: bool               # internet host reachable?
    latency_ms: float | None        # round-trip ms (None when down)
    signal_dbm: float | None        # WiFi signal level in dBm (None if unknown)
    signal_quality: float | None    # link quality 0-100% (None if unknown)
    ssid: str                       # network name at sample time


def _stddev(n: int, s: float, ss: float) -> float:
    """Population standard deviation from count, sum, sum-of-squares."""
    if n < 2:
        return 0.0
    var = (ss - s * s / n) / n
    return math.sqrt(var) if var > 0 else 0.0


class Stats:
    """Incrementally-maintained session aggregates for both metrics."""

    def __init__(self) -> None:
        # --- internet ---
        self.total = 0
        self.up_count = 0
        self.down_count = 0
        self.outages = 0
        self.downtime_s = 0.0
        self.longest_outage_s = 0.0
        self.lat_last: float | None = None
        self.lat_min: float | None = None
        self.lat_max: float | None = None
        self._lat_n = 0
        self._lat_s = 0.0
        self._lat_ss = 0.0
        # streak / outage bookkeeping
        self.current_up: bool | None = None
        self.streak_start = time.time()
        self._cur_outage_start: float | None = None

        # --- wifi signal (dBm) ---
        self.sig_last: float | None = None
        self.sig_min: float | None = None
        self.sig_max: float | None = None
        self._sig_n = 0
        self._sig_s = 0.0
        self._sig_ss = 0.0

    # ---- internet derived ----
    @property
    def lat_avg(self) -> float | None:
        return self._lat_s / self._lat_n if self._lat_n else None

    @property
    def lat_jitter(self) -> float:
        return _stddev(self._lat_n, self._lat_s, self._lat_ss)

    @property
    def uptime_pct(self) -> float:
        return 100.0 * self.up_count / self.total if self.total else 0.0

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.down_count / self.total if self.total else 0.0

    # ---- signal derived ----
    @property
    def sig_avg(self) -> float | None:
        return self._sig_s / self._sig_n if self._sig_n else None

    @property
    def sig_std(self) -> float:
        return _stddev(self._sig_n, self._sig_s, self._sig_ss)

    def add(self, p: Probe) -> None:
        self.total += 1

        # --- internet ---
        if p.internet_up:
            self.up_count += 1
            self.lat_last = p.latency_ms
            if p.latency_ms is not None:
                self._lat_n += 1
                self._lat_s += p.latency_ms
                self._lat_ss += p.latency_ms * p.latency_ms
                self.lat_min = p.latency_ms if self.lat_min is None else min(self.lat_min, p.latency_ms)
                self.lat_max = p.latency_ms if self.lat_max is None else max(self.lat_max, p.latency_ms)
        else:
            self.down_count += 1
            self.lat_last = None

        if self.current_up is None:
            self.current_up = p.internet_up
            self.streak_start = p.ts
            if not p.internet_up:
                self.outages += 1
                self._cur_outage_start = p.ts
        elif p.internet_up != self.current_up:
            self.current_up = p.internet_up
            self.streak_start = p.ts
            if not p.internet_up:
                self.outages += 1
                self._cur_outage_start = p.ts
            else:
                self._cur_outage_start = None

        if not p.internet_up and self._cur_outage_start is not None:
            self.longest_outage_s = max(self.longest_outage_s, p.ts - self._cur_outage_start)

        # --- signal ---
        if p.signal_dbm is not None:
            self.sig_last = p.signal_dbm
            self._sig_n += 1
            self._sig_s += p.signal_dbm
            self._sig_ss += p.signal_dbm * p.signal_dbm
            self.sig_min = p.signal_dbm if self.sig_min is None else min(self.sig_min, p.signal_dbm)
            self.sig_max = p.signal_dbm if self.sig_max is None else max(self.sig_max, p.signal_dbm)


# --------------------------------------------------------------------------- #
# Measurements
# --------------------------------------------------------------------------- #
_LAT_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms")


def ping_once(host: str, timeout: float) -> tuple[bool, float | None]:
    """Single ping. Returns (reachable, latency_ms)."""
    timeout_s = max(1, int(round(timeout)))
    cmd = ["ping", "-c", "1", "-W", str(timeout_s), host]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout + 2.0, text=True)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, None
    if proc.returncode != 0:
        return False, None
    m = _LAT_RE.search(proc.stdout)
    return True, (float(m.group(1)) if m else None)


def read_wifi_signal(iface: str) -> tuple[float | None, float | None]:
    """Read (signal_dbm, quality_pct) from /proc/net/wireless. No root needed."""
    try:
        with open("/proc/net/wireless", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None, None
    for line in lines[2:]:                      # skip the two header rows
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        if iface not in ("?", "") and name != iface:
            continue
        parts = rest.split()
        if len(parts) < 3:
            continue
        try:
            quality = float(parts[1].rstrip("."))   # link quality (often /70)
            level = float(parts[2].rstrip("."))      # signal level in dBm
        except ValueError:
            continue
        quality_pct = max(0.0, min(100.0, quality / 70.0 * 100.0))
        return level, quality_pct
    return None, None


def signal_label(dbm: float | None) -> str:
    if dbm is None:
        return "n/a"
    if dbm >= -50: return "Excellent"
    if dbm >= -60: return "Good"
    if dbm >= -67: return "Fair"
    if dbm >= -75: return "Weak"
    return "Very weak"


def stability_label(std: float, samples: int) -> str:
    if samples < 3:
        return "…"
    if std < 3.0:  return "STABLE"
    if std < 6.0:  return "FLUCTUATING"
    return "UNSTABLE"


# --------------------------------------------------------------------------- #
# Environment discovery (best-effort, non-fatal)
# --------------------------------------------------------------------------- #
def detect_ssid() -> str:
    for cmd in (["iwgetid", "-r"], ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]):
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, timeout=2.0).stdout.strip()
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if not out:
            continue
        if cmd[0] == "nmcli":
            for line in out.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1] or "?"
            continue
        return out
    return "?"


def detect_iface() -> str:
    try:
        out = subprocess.run(["iwgetid"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, timeout=2.0).stdout
        if out:
            return out.split()[0]
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired, IndexError):
        pass
    # Fall back to the first wireless interface present.
    try:
        with open("/proc/net/wireless", encoding="utf-8") as f:
            for line in f.readlines()[2:]:
                if ":" in line:
                    return line.split(":", 1)[0].strip()
    except OSError:
        pass
    return "?"


# --------------------------------------------------------------------------- #
# UI helpers
# --------------------------------------------------------------------------- #
class Colors:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.enabled else s

    def green(self, s):  return self._w("32", s)
    def red(self, s):    return self._w("31", s)
    def yellow(self, s): return self._w("33", s)
    def cyan(self, s):   return self._w("36", s)
    def dim(self, s):    return self._w("2", s)
    def bold(self, s):   return self._w("1", s)


_SPARKS = "▁▂▃▄▅▆▇█"


def spark_series(values: list, width: int, miss: str = "·") -> str:
    """Render numeric series as blocks; None entries become `miss`."""
    items = values[-width:]
    nums = [v for v in items if v is not None]
    if not nums:
        return miss * len(items)
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    out = []
    for v in items:
        if v is None:
            out.append(miss)
        else:
            idx = int((v - lo) / span * (len(_SPARKS) - 1))
            out.append(_SPARKS[min(max(idx, 0), len(_SPARKS) - 1)])
    return "".join(out)


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_ms(v: float | None) -> str:
    return f"{v:.1f}" if v is not None else "--"


def fmt_dbm(v: float | None) -> str:
    return f"{v:.0f}" if v is not None else "--"


HIDE_CURSOR, SHOW_CURSOR, CLEAR_HOME = "\033[?25l", "\033[?25h", "\033[H\033[J"


# --------------------------------------------------------------------------- #
# Interactive input
# --------------------------------------------------------------------------- #
DURATION_CHOICES = [
    ("1", "1 minute", 60),
    ("2", "10 minutes", 600),
    ("3", "1 hour", 3600),
    ("4", "Until I close it", None),
]


def choose_duration(c: "Colors"):
    """Prompt the user for how long to run. Returns seconds, or None for forever."""
    if not sys.stdin.isatty():
        return None                          # non-interactive: run until stopped
    print(c.bold("WiFi Observer") + " — how long should it run?")
    for key, label, _ in DURATION_CHOICES:
        print(f"   [{key}] {label}")
    while True:
        try:
            choice = input(c.cyan("Select 1-4 ") + "(default 4): ").strip() or "4"
        except EOFError:
            return None
        for key, _, dur in DURATION_CHOICES:
            if choice == key:
                return dur
        print("   Please enter 1, 2, 3, or 4.")


class KeyReader:
    """Context manager for non-blocking single-key reads from the terminal."""

    def __init__(self) -> None:
        self.enabled = sys.stdin.isatty()
        self._fd = None
        self._old = None

    def __enter__(self) -> "KeyReader":
        if self.enabled:
            import termios
            import tty
            try:
                self._fd = sys.stdin.fileno()
                self._old = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
            except (termios.error, OSError):
                self.enabled = False
        return self

    def __exit__(self, *exc) -> None:
        if self._old is not None:
            import termios
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except (termios.error, OSError):
                pass

    def poll(self, timeout: float):
        """Wait up to `timeout`s for a keypress; return the char or None."""
        if not self.enabled:
            if timeout > 0:
                time.sleep(timeout)
            return None
        import select
        try:
            ready, _, _ = select.select([sys.stdin], [], [], max(0.0, timeout))
        except (OSError, ValueError):
            return None
        return sys.stdin.read(1) if ready else None


def generate_graph(history, log_path, graph_path):
    """Render a graph from the full log (or in-memory history). Returns (ok, msg)."""
    import wifi_observer_plot as plot
    if log_path and os.path.isfile(log_path):
        rows = plot.load(log_path)           # full session, even beyond memory cap
    else:
        rows = [asdict(p) for p in history]
    if not rows:
        return False, "no data to plot yet"
    os.makedirs(os.path.dirname(graph_path) or ".", exist_ok=True)
    try:
        plot.build_figure(rows, graph_path)
    except ImportError:
        return False, "matplotlib not installed — run: pip install matplotlib"
    except Exception as exc:                  # never let plotting crash the monitor
        return False, f"graph error: {exc}"
    return True, f"graph saved → {graph_path}"


def render(cfg, stats: Stats, history, ssid, iface, started, log_path,
           duration_s, status, c: Colors) -> str:
    now = time.time()
    cols = shutil.get_terminal_size((80, 24)).columns
    inner = max(48, min(cols, 76))
    spark_w = max(20, inner - 14)

    if duration_s is None:
        time_left = c.dim("mode: until closed")
    else:
        time_left = "remaining: " + fmt_duration(max(0.0, duration_s - (now - started)))

    # Internet status
    if stats.current_up is None:
        net = c.dim("… starting")
    elif stats.current_up:
        net = c.green("● UP  ")
    else:
        net = c.red("● DOWN")
    lat = stats.lat_last
    lat_str = c.red("--") if lat is None else (c.yellow(fmt_ms(lat)) if lat > 150 else fmt_ms(lat))

    # Signal status
    dbm = stats.sig_last
    lab = signal_label(dbm)
    if dbm is None:
        sig_str = c.dim("-- dBm (n/a)")
    elif dbm >= -60:
        sig_str = c.green(f"{fmt_dbm(dbm)} dBm ({lab})")
    elif dbm >= -75:
        sig_str = c.yellow(f"{fmt_dbm(dbm)} dBm ({lab})")
    else:
        sig_str = c.red(f"{fmt_dbm(dbm)} dBm ({lab})")

    stab = stability_label(stats.sig_std, stats._sig_n)
    stab_str = {"STABLE": c.green, "FLUCTUATING": c.yellow, "UNSTABLE": c.red}.get(
        stab, c.dim)(stab)

    lat_spark = spark_series([p.latency_ms if p.internet_up else None for p in history], spark_w)
    sig_spark = spark_series([p.signal_dbm for p in history], spark_w)
    if c.enabled:
        lat_spark = "".join(c.red("·") if ch == "·" else ch for ch in lat_spark)

    bar = "─" * (inner - 2)
    lines = [
        c.cyan("┌─ WiFi Observer " + bar[15:] + "┐"),
        f" SSID: {c.bold(ssid)}   iface: {iface}",
        f" elapsed: {fmt_duration(now - started)}   {time_left}",
        c.dim(f" log → {log_path}"),
        "",
        c.bold(" INTERNET") + f"   {net}   target {cfg.host}",
        f"   latency : last {lat_str} ms   avg {fmt_ms(stats.lat_avg)}"
        f"   min {fmt_ms(stats.lat_min)}   max {fmt_ms(stats.lat_max)} ms",
        f"   quality : packet loss {stats.loss_pct:4.1f}%  ({stats.down_count}/{stats.total})"
        f"   jitter {stats.lat_jitter:.1f} ms",
        f"   outages : {stats.outages}   downtime {fmt_duration(stats.downtime_s)}"
        f"   longest {fmt_duration(stats.longest_outage_s)}",
        "",
        c.bold(" WIFI SIGNAL") + f"   {sig_str}",
        f"   stability : {stab_str}  (±{stats.sig_std:.1f} dBm)"
        f"   min {fmt_dbm(stats.sig_min)}   max {fmt_dbm(stats.sig_max)}   avg {fmt_dbm(stats.sig_avg)} dBm",
        "",
        f" latency  {lat_spark}",
        f" signal   {sig_spark}",
        c.cyan("└" + "─" * (inner - 2) + "┘"),
        " " + c.bold("[g]") + c.dim(" save graph    ") + c.bold("[q]") + c.dim(" quit    ")
        + c.dim("(Ctrl+C also quits)"),
        (" " + c.yellow(status)) if status else "",
    ]
    return CLEAR_HOME + "\n".join(lines) + "\n"


def print_summary(stats: Stats, started, log_path, summary_path, graph_msg, c: Colors) -> None:
    now = time.time()
    if c.enabled:
        sys.stdout.write(SHOW_CURSOR)
    print()
    print(c.bold("── Session summary ─────────────────────────────"))
    print(f" duration     : {fmt_duration(now - started)}")
    print(" INTERNET")
    print(f"   uptime     : {stats.uptime_pct:.1f}%   packet loss {stats.loss_pct:.1f}%   ({stats.up_count}/{stats.total})")
    print(f"   latency    : avg {fmt_ms(stats.lat_avg)}  min {fmt_ms(stats.lat_min)}  max {fmt_ms(stats.lat_max)}  jitter {stats.lat_jitter:.1f} ms")
    print(f"   outages    : {stats.outages}   downtime {fmt_duration(stats.downtime_s)}   longest {fmt_duration(stats.longest_outage_s)}")
    print(" WIFI SIGNAL")
    print(f"   signal     : avg {fmt_dbm(stats.sig_avg)}  min {fmt_dbm(stats.sig_min)}  max {fmt_dbm(stats.sig_max)} dBm  ({signal_label(stats.sig_avg)})")
    print(f"   stability  : {stability_label(stats.sig_std, stats._sig_n)}  (±{stats.sig_std:.1f} dBm)")
    print("─────────────────────────────────────────────────")
    print(c.dim(f" log     : {log_path}"))
    print(c.dim(f" summary : {summary_path}"))
    print(c.dim(f" graph   : {graph_msg}"))


def write_summary_json(path, stats: Stats, started, cfg, ssid, iface) -> None:
    now = time.time()
    data = {
        "started": dt.datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "ended": dt.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "duration_s": round(now - started, 1),
        "host": cfg.host, "interval_s": cfg.interval, "ssid": ssid, "iface": iface,
        "internet": {
            "samples": stats.total, "up": stats.up_count, "down": stats.down_count,
            "uptime_pct": round(stats.uptime_pct, 2), "packet_loss_pct": round(stats.loss_pct, 2),
            "latency_avg_ms": round(stats.lat_avg, 2) if stats.lat_avg is not None else None,
            "latency_min_ms": stats.lat_min, "latency_max_ms": stats.lat_max,
            "latency_jitter_ms": round(stats.lat_jitter, 2),
            "outages": stats.outages, "downtime_s": round(stats.downtime_s, 1),
            "longest_outage_s": round(stats.longest_outage_s, 1),
        },
        "wifi_signal": {
            "samples": stats._sig_n,
            "avg_dbm": round(stats.sig_avg, 1) if stats.sig_avg is not None else None,
            "min_dbm": stats.sig_min, "max_dbm": stats.sig_max,
            "stddev_dbm": round(stats.sig_std, 2),
            "stability": stability_label(stats.sig_std, stats._sig_n),
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="wifi_observer",
                                description="Observe internet reachability and WiFi signal stability.")
    p.add_argument("-H", "--host", default="8.8.8.8",
                   help="Internet host to ping (default: 8.8.8.8, Google DNS)")
    p.add_argument("-i", "--interval", type=float, default=1.0, help="Seconds between samples (default: 1.0)")
    p.add_argument("-t", "--timeout", type=float, default=1.0, help="Per-ping timeout seconds (default: 1.0)")
    p.add_argument("-n", "--history", type=int, default=3600, help="Samples kept in memory for the UI (default: 3600)")
    p.add_argument("--log", metavar="PATH", default=None,
                   help="JSON-lines log path (default: logs/wifi-<timestamp>.jsonl)")
    p.add_argument("--no-log", action="store_true", help="Disable JSON logging")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    return p.parse_args(argv)


def main(argv=None) -> int:
    cfg = parse_args(argv)
    color = (not cfg.no_color) and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    c = Colors(color)

    if shutil.which("ping") is None:
        print("error: 'ping' not found in PATH", file=sys.stderr)
        return 1

    # 1) Interactive startup prompt: how long to run.
    duration_s = choose_duration(c)

    ssid = detect_ssid()
    iface = detect_iface()
    started = time.time()
    started_dt = dt.datetime.fromtimestamp(started)
    stamp = started_dt.strftime("%H%M%S")
    out_dir = os.path.join("logs", started_dt.strftime("%Y-%m-%d"))   # logs/<date>/

    # Logging + graph output paths, grouped under logs/<date>/.
    log_fh = None
    log_path = summary_path = "(disabled)"
    if not cfg.no_log:
        if cfg.log:
            log_path = cfg.log
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        else:
            os.makedirs(out_dir, exist_ok=True)
            log_path = os.path.join(out_dir, f"wifi-{stamp}.jsonl")
        summary_path = os.path.splitext(log_path)[0] + ".summary.json"
        log_fh = open(log_path, "a", buffering=1, encoding="utf-8")
    graph_path = (os.path.splitext(log_path)[0] + ".png") if log_fh is not None \
        else os.path.join(out_dir, f"wifi-{stamp}.png")

    history = collections.deque(maxlen=cfg.history)
    stats = Stats()

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))

    def draw(status=""):
        sys.stdout.write(render(cfg, stats, history, ssid, iface, started,
                                log_path, duration_s, status, c))
        sys.stdout.flush()

    def time_up():
        return duration_s is not None and (time.time() - started) >= duration_s

    # 2) Interactive monitor loop with live keys ([g] graph, [q] quit).
    with KeyReader() as keys:
        if color:
            sys.stdout.write(HIDE_CURSOR)
        prev_tick = started
        try:
            while not stop["flag"] and not time_up():
                tick = time.time()
                up, latency = ping_once(cfg.host, cfg.timeout)
                sdbm, squal = read_wifi_signal(iface)
                ts = time.time()
                p = Probe(ts=ts, time=dt.datetime.fromtimestamp(ts).isoformat(timespec="milliseconds"),
                          internet_up=up, latency_ms=latency, signal_dbm=sdbm,
                          signal_quality=squal, ssid=ssid)

                if stats.current_up is False:      # accumulate downtime per tick while down
                    stats.downtime_s += ts - prev_tick
                prev_tick = ts

                history.append(p)
                stats.add(p)
                if log_fh is not None:
                    log_fh.write(json.dumps(asdict(p)) + "\n")

                draw()

                # Wait out the interval, staying responsive to keypresses.
                deadline = tick + cfg.interval
                while not stop["flag"] and not time_up():
                    wait = deadline - time.time()
                    if wait <= 0:
                        break
                    key = keys.poll(min(0.2, wait))
                    if not key:
                        continue
                    if key in ("q", "Q"):
                        stop["flag"] = True
                    elif key in ("g", "G"):
                        draw(status="generating graph…")
                        _, msg = generate_graph(history, log_path, graph_path)
                        draw(status=msg)
        finally:
            if color:
                sys.stdout.write(SHOW_CURSOR)
                sys.stdout.flush()
            if log_fh is not None:
                log_fh.close()
                write_summary_json(summary_path, stats, started, cfg, ssid, iface)

    # 3) Always leave the user with a graph (no need to run plot.py by hand).
    _, graph_msg = generate_graph(history, log_path, graph_path)
    print_summary(stats, started, log_path, summary_path, graph_msg, c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
