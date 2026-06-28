<div align="center">

# 📶 WiFi Observer

**A terminal tool that tells you — every second — whether your problem is the _internet_ or your _WiFi_.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](#requirements)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)
[![Made with: Python & Bash](https://img.shields.io/badge/made%20with-Python%20%26%20Bash-1f425f.svg)](#how-it-works)

</div>

WiFi Observer continuously monitors two **independent** things — internet
reachability (via ping) and WiFi signal strength (in dBm) — so you can tell *why*
your connection is bad, not just *that* it is. It runs entirely in your terminal,
keeps a live history in memory, logs every sample to JSON, and draws a graph of
the session. Built with the Python standard library + Bash; the only optional
dependency is matplotlib (for graphs), installed automatically on first run.

---

## 📑 Table of contents

- [Why](#why)
- [Demo](#demo)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Output & file formats](#output--file-formats)
- [Reading the numbers](#reading-the-numbers)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why

A plain ping test lumps two different failures together. WiFi Observer separates
them:

| WiFi signal | Internet | Likely culprit |
|-------------|----------|----------------|
| Strong & stable | Down / lossy | **ISP / router** — not your WiFi |
| Weak / unstable | Down / lossy | **Your WiFi** — distance, walls, interference |
| Strong & stable | Fine | All good ✅ |

So instead of "the internet is slow," you get an answer you can act on.

---

## Demo

```
┌─ WiFi Observer ───────────────────────────────────────────┐
 SSID: HomeNet-5G   iface: wlan0
 elapsed: 00:04:12   remaining: 00:05:48
 log → logs/2026-06-28/wifi-215205.jsonl

 INTERNET   ● UP     target 8.8.8.8
   latency : last 23.4 ms   avg 26.1   min 18.0   max 142.0 ms
   quality : packet loss  0.8%  (2/250)   jitter 5.2 ms
   outages : 2   downtime 00:04   longest 00:03

 WIFI SIGNAL   -47 dBm (Excellent)
   stability : STABLE  (±1.8 dBm)   min -52   max -44   avg -47.3 dBm

 latency  ▁▂▃█▂▂▃▃▂·▂▃▂▂   (· = a probe with no reply / outage)
 signal   ▅▅▆▆▅▅▄▅▅▆▆▅▄▅
└────────────────────────────────────────────────────────────┘
 [g] save graph    [q] quit    (Ctrl+C also quits)
```

The exported graph stacks **internet latency** (outages marked in red) over
**WiFi signal strength** (with quality reference lines), sharing a time axis.

> 💡 Tip: drop a real screenshot/GIF here (e.g. `docs/demo.png`) before publishing.

---

## Features

- 📡 **Two metrics at once** — internet reachability *and* WiFi signal, sampled every second.
- 🖥️ **Live terminal UI** — single self-refreshing screen with two labelled sections and sparklines.
- ⏱️ **Pick a duration on start** — 1 min / 10 min / 1 hr / until you close it, with a live countdown.
- ⌨️ **Interactive keys** — `g` saves a graph instantly, `q` quits.
- 📝 **JSON logging** — every sample appended (JSON-lines), crash-safe.
- 📊 **Graphs ("maps")** — matplotlib charts generated from inside the app and on exit.
- 🗂️ **Date-organised output** — logs, summary, and graph grouped under `logs/YYYY-MM-DD/`.
- 🔧 **Near-zero setup** — monitor is stdlib-only; matplotlib is auto-installed into a local `.venv`.
- 🛟 **Degrades gracefully** — no colours? no matplotlib? not a TTY? It still runs and tells you.

---

## Installation

```bash
# 1. Clone
git clone https://github.com/biswanathamz/wifi-observer.git
cd wifi-observer

# 2. Run — that's it.
./run.sh
```

There is **no build step**. The monitor uses only the Python 3 standard library
and the system `ping`. The first run bootstraps a local `.venv` and installs
`matplotlib` so graphs work (skip with `./run.sh --no-graph-setup`).

> Prefer to manage deps yourself? `pip install matplotlib` and run
> `python3 wifi_observer.py` directly.

---

## Usage

```bash
./run.sh                      # ping 8.8.8.8 every 1s
./run.sh -H 1.1.1.1 -i 2      # ping Cloudflare, every 2 seconds
./run.sh -H 192.168.1.1       # ping your router (tests the LAN link only)
./run.sh --no-color           # plain text
./run.sh --help               # full option list
```

**On start**, choose how long to run:

```
WiFi Observer — how long should it run?
   [1] 1 minute
   [2] 10 minutes
   [3] 1 hour
   [4] Until I close it
Select 1-4 (default 4):
```

**While running**, the UI is interactive:

| Key | Action |
|-----|--------|
| `g` | Generate & save a graph (PNG) right now |
| `q` | Quit and print the session summary |
| `Ctrl+C` | Also quits cleanly |

A graph is **also saved automatically on exit**, and everything lands under
`logs/<today>/`.

---

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `-H, --host` | `8.8.8.8` | Host/IP to ping (an IP avoids DNS; a hostname is resolved by `ping`). |
| `-i, --interval` | `1.0` | Seconds between samples. |
| `-t, --timeout` | `1.0` | Per-ping timeout (s) → a slow/no reply counts as DOWN. |
| `-n, --history` | `3600` | Samples kept in memory for the live UI / sparklines. |
| `--log PATH` | auto | Custom JSON-lines log path (default `logs/<date>/wifi-<time>.jsonl`). |
| `--no-log` | off | Disable JSON logging. |
| `--no-color` | off | Plain text, no ANSI colours. |
| `--no-graph-setup` | off | *(run.sh)* Skip the matplotlib `.venv` bootstrap. |

---

## How it works

### Architecture

| File | Language | Role |
|------|----------|------|
| [run.sh](run.sh) | Bash | Checks deps, bootstraps matplotlib into `.venv`, launches the app. |
| [wifi_observer.py](wifi_observer.py) | Python | Monitor loop, measurements, statistics, interactive UI, JSON logging. |
| [plot.py](plot.py) | Python | Builds the matplotlib figure; used by the app and standalone. |

### The per-second cycle

1. **Ping** the host once → reachable? + latency.
2. **Read WiFi signal** from `/proc/net/wireless` → dBm + link quality.
3. Build a sample record and append it to the **in-memory history** and the **JSON log**.
4. Update **running statistics** incrementally (counts, sums, sums-of-squares).
5. **Redraw** the UI.
6. Wait out the interval while **polling the keyboard** for `g`/`q`.

### How the ping works

No hand-rolled ICMP — it runs the system `ping`:

```
ping -c 1 -W <timeout> <host>
```

`-c 1` sends one echo request; `-W` is the reply timeout. UP/DOWN is decided from
ping's **exit code** (0 = reply); latency is parsed from the output (`time=23.4 ms`)
with a regex. Because the OS `ping` already holds the ICMP privilege, **no `sudo`
is needed**. The call is wrapped so a hang or failure can never crash the loop — it
just records a DOWN sample.

### How the WiFi signal is read

The kernel exposes live wireless stats as text in `/proc/net/wireless`. The program
parses the active interface's row for **link quality** (≈ out of 70 → a 0–100 %
figure) and **signal level in dBm**. No external command, no privileges.

### Statistics

Aggregates are maintained incrementally so each tick is O(1) no matter how long
you run: uptime %, packet loss %, latency avg/min/max, **jitter** (latency
std-dev), outage count/total/longest, and signal avg/min/max with **std-dev**
(which drives the stability verdict).

History is a bounded `deque` (default last **3600** samples ≈ 1 h), so memory stays
capped — while the **JSON log keeps the full session** on disk, and graphs are
built from that log.

---

## Output & file formats

Each run writes into a **date folder**, all artifacts sharing one basename:

```
logs/
└── 2026-06-28/
    ├── wifi-215205.jsonl         # one JSON object per sample
    ├── wifi-215205.summary.json  # session aggregates
    └── wifi-215205.png           # the graph ("map")
```

**Per-sample log line** (`.jsonl`):

```json
{"ts": 1782662252.80, "time": "2026-06-28T21:27:32.802", "internet_up": true,
 "latency_ms": 47.8, "signal_dbm": -63.0, "signal_quality": 67.1, "ssid": "HomeNet-5G"}
```

**Summary** (`.summary.json`) — start/end/duration, config, plus `internet` and
`wifi_signal` blocks (uptime %, packet loss, latency stats, outages, signal
avg/min/max/stddev/stability).

Re-plot any old log standalone:

```bash
python3 plot.py                                   # newest log → <log>.png
python3 plot.py logs/2026-06-28/wifi-215205.jsonl -o report.png --show
```

---

## Reading the numbers

**WiFi signal (dBm)** — higher (closer to 0) is better:

| dBm | Label | Meaning |
|-----|-------|---------|
| ≥ -50 | Excellent | Right next to the router |
| -50 to -60 | Good | Solid, reliable |
| -60 to -67 | Fair | Usable; HD video fine |
| -67 to -75 | Weak | Drops/slowdowns likely |
| < -75 | Very weak | Often unusable |

**Stability** (from signal std-dev): `STABLE` < 3 dBm, `FLUCTUATING` < 6 dBm,
`UNSTABLE` ≥ 6 dBm. **Latency / jitter / packet loss** — lower is better; high
jitter hurts calls/gaming even when average latency looks fine.

---

## Project structure

```
wifi-observer/
├── doc/
│   └── SPEC.md              # full specification
├── run.sh                   # Bash launcher (+ matplotlib venv bootstrap)
├── wifi_observer.py         # Python monitor, UI, logging
├── plot.py                  # matplotlib figure builder (UI + standalone)
├── LICENSE                  # MIT
├── README.md
├── .venv/                   # auto-created on first run        [git-ignored]
└── logs/                    # date folders of output           [git-ignored]
```

---

## Requirements

- **Linux** with `python3` (3.8+) and `ping` on `PATH`. The monitor itself is
  **standard-library only**.
- **WiFi signal** needs `/proc/net/wireless` (standard on Linux WiFi). SSID/
  interface detection uses `iwgetid`/`nmcli` when present; otherwise it shows `?`.
- **matplotlib** — only for graphs; `run.sh` installs it into a local `.venv` on
  first run (needs `python3-venv` + network once). Skip with `--no-graph-setup`.

> **Platform note:** Linux-focused. The `ping` flags and signal reading target
> Linux; macOS/Windows support would need contributions (see the roadmap).

---

## Roadmap

Ideas and good first contributions:

- [ ] macOS / Windows support (`ping` flags + signal reading)
- [ ] Optional gateway probe to pinpoint LAN-vs-WAN faults
- [ ] DNS-resolution check (distinguish "internet down" from "DNS down")
- [ ] Desktop notification on outage start / recovery
- [ ] CSV export and a `--summary-only` headless mode
- [ ] Configurable thresholds (signal labels, stability bands)

Found a bug or want a feature? Please [open an issue](../../issues).

---

## Contributing

Contributions are welcome! 🎉

1. **Fork** the repo and create a branch: `git checkout -b feature/my-change`.
2. **Make your change.** Keep the monitor **standard-library only** (matplotlib is
   fine to import *lazily* inside `plot.py`). Match the existing style.
3. **Test it** — run `./run.sh` and verify the live UI, logging, and a generated
   graph. For unreachable-host behaviour, try `./run.sh -H 192.0.2.1` (TEST-NET).
4. **Commit** with a clear message and **open a Pull Request** describing what and
   why.

Please keep changes focused, document new flags in the README, and be kind in
code review. By contributing, you agree your work is licensed under the project's
MIT license.

---

## License

Released under the [MIT License](LICENSE) — free to use, modify, and distribute
with attribution. © 2026 biswanathamz.

<div align="center">

⭐ If this saved you a frustrating "is it me or the internet?" moment, consider starring the repo.

</div>
