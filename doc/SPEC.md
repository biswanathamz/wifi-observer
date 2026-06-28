# WiFi Observer — Specification

## 1. Overview

**WiFi Observer** is a lightweight terminal application that continuously monitors
two **independent** aspects of connection health, once per second:

1. **Internet reachability** — pings a reliable host (default `8.8.8.8`, Google
   DNS) to determine whether the internet is up, and how good it is (latency,
   jitter, packet loss, outages).
2. **WiFi signal stability** — reads radio signal strength in **dBm** from the
   adapter (`/proc/net/wireless`) to determine whether the WiFi link is strong
   and steady (min/max/avg dBm, fluctuation / stability verdict).

Measuring both separates *internet* problems from *WiFi* problems: strong signal
but no internet ⇒ likely the ISP; weak/unstable signal ⇒ likely the WiFi link.

The tool answers questions like:

- "Is my internet dropping intermittently, and for how long?"
- "What is my current / average / worst latency and jitter?"
- "Is my WiFi signal strong, and does it fluctuate?"

It keeps a rolling history **in memory** for the live UI, **logs every sample to
JSON** (JSON-lines), writes a **summary JSON** on exit, and can **export graphs**
via matplotlib (`plot.py`).

---

## 2. Goals & Non-Goals

### Goals
- Probe connectivity every **1 second** (configurable).
- Measure **latency (ms)** and **up/down** status for each probe.
- Keep a rolling history of results **in memory**.
- Show a **simple, readable live UI** in the terminal.
- Run entirely from the **terminal**, no GUI toolkit required.
- Be implemented with **Python** (core logic + UI) and **Bash** (launcher / helper).

### Non-Goals
- No packet capture or deep network diagnostics.
- No long-term persistent storage (optional only).
- No remote dashboards, web UI, or alerting integrations (optional only).
- No root/sudo requirement for normal operation.

---

## 3. Components & Languages

| Component        | Language | Responsibility                                            |
|------------------|----------|-----------------------------------------------------------|
| `run.sh`         | Bash     | Entry point: checks deps, parses args, launches Python.   |
| `wifi_observer.py` | Python | Monitor loop, data store, terminal UI, JSON logging.      |
| `plot.py`        | Python   | Read a JSON log and export matplotlib graphs (PNG).       |

> `matplotlib` is the only non-stdlib dependency, and only `plot.py` needs it.
> The monitor itself runs on the Python 3 stdlib + system `ping`.

**Why both languages**
- **Bash** handles the environment: verifies `python3` and `ping` exist, reads
  the active SSID (via `iwgetid`/`nmcli` where available), and starts the app.
- **Python** handles timing, data structures, statistics, and the live UI.

---

## 4. How It Works (High Level)

```
run.sh
  └─ validates deps + gathers SSID/interface info
        └─ launches wifi_observer.py with config
              └─ prompt: run for 1m / 10m / 1h / until closed
              └─ loop every 1s (until duration elapses or quit):
                    1. ping target host (internet up? latency?)
                    2. read /proc/net/wireless (signal dBm, quality)
                    3. append sample to in-memory store + JSON log
                    4. recompute live statistics
                    5. redraw terminal UI (with remaining countdown)
                    6. poll keys:  g = save graph,  q = quit
              └─ on exit: write summary JSON, save graph, print summary
```

---

## 5. Functional Requirements

### 5.1 Probing
- **FR-1**: Send one ICMP echo (ping) to a configurable target (default `8.8.8.8`)
  every `interval` seconds (default `1.0`).
- **FR-2**: Each probe has a timeout (default `1.0s`). A timeout counts as **DOWN**.
- **FR-3**: Record per probe: timestamp, status (`UP`/`DOWN`), latency in ms
  (`None` when down).
- **FR-4**: Optionally capture the current **SSID** at startup (and refresh
  periodically) to label the session.

### 5.2 In-Memory Data Store
- **FR-5**: Maintain an in-memory list/deque of probe records.
- **FR-6**: Cap history to the last `N` records (default `3600`, i.e. ~1 hour at
  1s interval) to bound memory; older entries are discarded.
- **FR-7**: Maintain running aggregates so stats are O(1) per tick where practical:
  total probes, total up, total down, current up/down streak, min/max/avg latency.

### 5.3 Statistics
- **FR-8**: Compute and expose:
  - Uptime % (up / total)
  - Current status (UP/DOWN) and current streak duration
  - Latency: last, min, max, average (over retained window)
  - Outage count and total downtime (seconds)
  - Longest outage duration

### 5.4 Interactive Startup Prompt
- **FR-DUR-1**: Before monitoring, prompt the user to choose a run duration:
  **1 minute / 10 minutes / 1 hour / until closed**. Default = until closed.
- **FR-DUR-2**: For a fixed duration, the UI shows a live `remaining:` countdown
  and the monitor stops automatically (clean exit + summary) at zero.
- **FR-DUR-3**: When stdin is not a TTY (piped/automation), skip the prompt and
  default to "until closed".

### 5.5 Terminal UI
- **FR-9**: Render a single-screen, self-refreshing UI (redraw in place, not
  scrolling) updated each tick.
- **FR-10**: Display two clearly-labelled sections:
  - Header: SSID, interface, elapsed time, remaining/until-closed.
  - **INTERNET**: UP/DOWN, latency last/avg/min/max, jitter, packet loss, outages.
  - **WIFI SIGNAL**: dBm + quality label, stability verdict, min/max/avg dBm.
  - Two **sparklines**: latency and signal, over the retained window.
  - A footer with the interactive key controls.
- **FR-11**: Use color when supported (green=good, red=down/weak, yellow=marginal).
  Degrade gracefully to plain text otherwise.

### 5.6 Interactive Controls (while running)
- **FR-KEY-1**: Read single keypresses without blocking the monitor loop
  (cbreak mode; disabled automatically when stdin is not a TTY).
- **FR-KEY-2**: `g` → generate/save a graph **from inside the UI** (PNG via
  matplotlib), sourced from the full JSON log; show an inline status message.
- **FR-KEY-3**: `q` → quit gracefully (same path as SIGINT).

### 5.7 Graphing
- **FR-GRAPH-1**: The user never has to run a separate plot command; graphs are
  produced on `g` and automatically on exit.
- **FR-GRAPH-2**: If matplotlib is absent, report it inline without crashing.
- **FR-GRAPH-3**: Graph = internet latency (outages marked) over WiFi signal
  (dBm) with quality reference lines, sharing a time axis.

### 5.8 Lifecycle
- **FR-12**: Handle `Ctrl+C` (SIGINT) gracefully: stop the loop, restore the
  terminal (cursor + cbreak), print a final session summary, exit `0`.
- **FR-13**: Always start even if the first probes fail (show DOWN) rather than
  aborting.

---

## 6. Non-Functional Requirements

- **NFR-1 (Portability)**: Run on Linux with stdlib Python 3.8+; no third-party
  packages required for the core. (Optional `rich` enhancement — see §9.)
- **NFR-2 (Footprint)**: Memory bounded by the history cap; CPU near-idle between
  ticks.
- **NFR-3 (Robustness)**: A failed/garbled ping never crashes the loop; parse
  errors are treated as DOWN.
- **NFR-4 (Usability)**: Readable on an 80×24 terminal.

---

## 7. Configuration

Configurable via CLI flags (parsed in Bash, forwarded to Python) with sane
defaults:

| Flag              | Default     | Description                                  |
|-------------------|-------------|----------------------------------------------|
| `-H, --host`      | `8.8.8.8`   | Ping target.                                 |
| `-i, --interval`  | `1.0`       | Seconds between probes.                       |
| `-t, --timeout`   | `1.0`       | Per-ping timeout (seconds).                   |
| `-n, --history`   | `3600`      | Max records kept in memory.                   |
| `--no-color`      | `false`     | Disable ANSI colors.                          |
| `-h, --help`      | —           | Show usage.                                   |

---

## 8. Data Model

```python
@dataclass
class Probe:
    ts: float          # epoch seconds
    up: bool           # reachable?
    latency_ms: float | None  # None when down

# Session aggregates (kept incrementally)
class Stats:
    total: int
    up_count: int
    down_count: int
    outages: int
    downtime_s: float
    longest_outage_s: float
    latency_min/max/avg/last: float
    current_streak_status: bool
    current_streak_start: float
```

---

## 9. Optional / Future Extensions (out of core scope)

- `--log FILE` to append CSV/JSON records to disk.
- `rich`-based fancier UI (tables, live charts).
- Desktop notification on outage start/recovery.
- Multi-target monitoring (gateway vs. internet) to distinguish LAN vs. WAN faults.
- Export session summary to a file on exit.

---

## 10. Example UI (mock)

```
┌─ WiFi Observer ─────────────────────────────────────────────┐
 SSID: HomeNet-5G   iface: wlan0   target: 8.8.8.8   every 1.0s
 elapsed: 00:04:12

   STATUS:  ● UP        latency: 23.4 ms

 uptime    : 99.2%   (248/250)
 latency   : avg 26.1  min 18.0  max 142.0 ms
 outages   : 2        downtime: 4s   longest: 3s

 last 60s  : ......X.....................X...............
└─────────────────────────────────────────────────────────────┘
 Ctrl+C to stop
```

---

## 11. Project Layout & Output

```
wifi-observer/
├── doc/
│   └── SPEC.md              # this document
├── run.sh                   # bash launcher (also bootstraps matplotlib venv)
├── wifi_observer.py         # python monitor + interactive UI + JSON logging
├── plot.py                  # matplotlib figure builder (used by the UI & CLI)
├── .venv/                   # auto-created on first run (matplotlib)
└── logs/
    └── YYYY-MM-DD/          # one date folder per day
        ├── wifi-HHMMSS.jsonl
        ├── wifi-HHMMSS.summary.json
        └── wifi-HHMMSS.png  # the graph ("map")
```

All artifacts for a session (log, summary, graph) share the same basename and
live together under the run's **date folder**, `logs/<date>/`.

---

## 12. Acceptance Criteria

1. On start, the user is prompted for run duration (1m / 10m / 1h / until closed).
2. `./run.sh` shows a live, in-place UI with INTERNET and WIFI SIGNAL sections,
   updating about once per second.
3. Losing internet flips status to DOWN within `timeout` and counts the outage;
   weak/unstable signal is reflected in the WIFI SIGNAL section.
4. Pressing `g` saves a graph from inside the UI; a graph is also saved on exit.
5. `q` / `Ctrl+C` / a finished duration all exit cleanly (code 0) with a summary.
6. Logs, summary, and graph are written together under `logs/<date>/`.
7. The monitor runs on the Python 3 stdlib + `ping`; only graphing needs
   matplotlib, which `run.sh` provisions automatically.
