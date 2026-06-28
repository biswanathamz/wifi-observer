#!/usr/bin/env bash
#
# run.sh — launcher for WiFi Observer.
#
# Validates dependencies, makes sure matplotlib is available (so the in-app
# graph works), then starts the Python monitor. All arguments are forwarded
# straight through to wifi_observer.py.
#
#   ./run.sh                     # defaults (ping 8.8.8.8 every 1s)
#   ./run.sh -H 1.1.1.1 -i 2     # custom host / interval
#   ./run.sh --no-graph-setup    # skip the matplotlib venv bootstrap
#   ./run.sh --help              # full option list
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_APP="${SCRIPT_DIR}/wifi_observer.py"
VENV_DIR="${SCRIPT_DIR}/.venv"

die()  { printf 'error: %s\n' "$1" >&2; exit 1; }
warn() { printf 'warning: %s\n' "$1" >&2; }

# --- Optional flag: skip graph/venv bootstrap ------------------------------ #
SETUP_GRAPH=1
ARGS=()
for a in "$@"; do
    if [ "$a" = "--no-graph-setup" ]; then
        SETUP_GRAPH=0
    else
        ARGS+=("$a")
    fi
done

# --- Base dependency checks ------------------------------------------------ #
PYTHON_BIN=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PYTHON_BIN="$cand"; break; fi
done
[ -n "$PYTHON_BIN" ] || die "python3 is required but was not found in PATH"
command -v ping >/dev/null 2>&1 || die "'ping' is required but was not found in PATH"
[ -f "$PY_APP" ] || die "cannot find wifi_observer.py next to run.sh ($PY_APP)"

# --- Ensure matplotlib so the graph ("map") can be generated --------------- #
# Strategy: if the system Python already has matplotlib, use it. Otherwise set
# up a local .venv once and install matplotlib there. Falls back gracefully:
# the monitor still runs (graphs just won't render) if setup fails.
if [ "$SETUP_GRAPH" -eq 1 ]; then
    if "$PYTHON_BIN" -c 'import matplotlib' >/dev/null 2>&1; then
        :   # system python can already plot
    elif [ -x "${VENV_DIR}/bin/python" ] && "${VENV_DIR}/bin/python" -c 'import matplotlib' >/dev/null 2>&1; then
        PYTHON_BIN="${VENV_DIR}/bin/python"
    else
        echo "Setting up graphing support (matplotlib) — first run only…"
        if [ ! -x "${VENV_DIR}/bin/python" ]; then
            "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null \
                || warn "could not create venv (is python3-venv installed?); graphs may be disabled"
        fi
        if [ -x "${VENV_DIR}/bin/python" ]; then
            "${VENV_DIR}/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
            if "${VENV_DIR}/bin/python" -m pip install -q matplotlib; then
                PYTHON_BIN="${VENV_DIR}/bin/python"
            else
                warn "matplotlib install failed; running without graphs"
            fi
        fi
    fi
fi

# --- Hand off to the Python app -------------------------------------------- #
exec "$PYTHON_BIN" "$PY_APP" "${ARGS[@]+"${ARGS[@]}"}"
