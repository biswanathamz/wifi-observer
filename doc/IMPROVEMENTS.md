# WiFi Observer — Missing Features & Improvement Plan

This document captures gaps and proposed enhancements for the project, in
priority order. It's a living planning doc — move items into the README roadmap
or close them as they ship.

Current state (already implemented): per-second internet ping (latency, jitter,
packet loss, outages), WiFi signal in dBm + stability, interactive duration
prompt, live UI with `g`/`q` keys, JSON logging + summary, matplotlib graphs,
date-organised output.

---

## 🎯 Priority 0 — The gap that undercuts the pitch

### P0.1 — Gateway / router probe (LAN vs WAN distinction)

**Why it matters:** The project's headline is *"is it the **ISP** or your
**WiFi**?"* and the README has a diagnosis table for it — but the code can only
**infer** the cause from signal + internet. It cannot yet *prove* it. Adding a
third probe (ping the default gateway each tick) makes the diagnosis definitive:

| Gateway | Internet | Verdict (now provable) |
|---------|----------|------------------------|
| ✅ reachable | ❌ down | **ISP / WAN problem** — the LAN is fine |
| ❌ unreachable | ❌ down | **Local / WiFi problem** — can't even reach the router |

**Scope:** auto-detect the gateway (`ip route show default`), ping it alongside
the internet host, add a `gateway_up` / `gateway_latency_ms` field to each sample
and a small line in the UI. Cheap (one extra ping per tick).

**Effort:** Low–Medium. **Impact:** Highest — directly fulfils the tool's reason
for existing. **Recommendation: promote from roadmap to core before publishing.**

---

## ⭐ Priority 1 — High value, low effort

### P1.1 — `--duration` CLI flag
Duration is currently **interactive-only** (the startup prompt). There's no way to
run a fixed-length session non-interactively (cron, scripts, CI). Add a
`--duration {1m|10m|1h|forever|<seconds>}` flag that, when present, skips the
prompt. Keep the prompt as the default when no flag is given and stdin is a TTY.

### P1.2 — DNS-resolution check
A large share of real "internet is down" events are actually **DNS** failures.
Resolve a hostname each tick (separately from the IP ping) and report
`dns_ok` so the UI can distinguish "internet down" from "DNS down." This also
completes the story behind pinging `8.8.8.8` ("no DNS needed").

### P1.3 — Latency percentiles (p50 / p95 / p99)
`avg` + `max` hide the real experience. p95/p99 is what reflects a bad call or
laggy game. Compute percentiles (exact over the retained window, or a streaming
estimate) and show them in the summary at minimum.

### P1.4 — Richer WiFi link detail (bitrate / channel / band)
Read negotiated **bitrate**, **channel**, and **band (2.4 vs 5 GHz)** from
`iw dev <iface> link`. Cheap context that often *explains* a weak/unstable signal
(congestion, wrong band). Degrade gracefully when `iw` is absent.

---

## 🔸 Priority 2 — Worth considering (not blockers)

### P2.1 — Desktop notification on outage start / recovery
Fire `notify-send` (when available) when an outage begins and when it recovers, so
the tool is useful left running in the background.

### P2.2 — Explicit event log
A separate, human-readable timeline of state changes — "outage started /
recovered / signal dropped below X dBm" — distinct from the per-second sample log.

### P2.3 — CSV export
A `--csv` option (or a `plot.py`/exporter mode) for users who want to open the
data in a spreadsheet.

---

## 🧰 Priority 3 — Open-source health (since we're publishing)

### P3.1 — Automated test suite
Biggest **credibility** gap for contributors. Unit tests for:
- the statistics math (uptime %, jitter, downtime, stability bands),
- the ping latency regex (`time=23.4 ms`, `time<1 ms`),
- the `/proc/net/wireless` parser.
Everything is currently hand-verified, which doesn't scale to PRs.

### P3.2 — Packaging
Add `pyproject.toml` with a console entry point so `pip install` provides a
`wifi-observer` command. Improves adoption and distribution.

### P3.3 — CI (GitHub Actions)
Run lint + the test suite on push/PR. Pairs with P3.1.

---

## 🚫 Explicitly out of scope (avoid scope creep)

- **Built-in speed tests / throughput benchmarking.** Heavy, needs a server, and
  turns a lightweight *passive* monitor into something else. Leave out, or keep as
  a clearly-separate optional mode at most.

---

## Recommended order before going public

1. **P0.1 Gateway probe** — makes the tool live up to its pitch.
2. **P1.1 `--duration` flag** — makes it usable in automation.
3. **P3.1 Test suite** — makes it credible to contributors.

Everything else can remain roadmap items in the README.
