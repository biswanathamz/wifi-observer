"""Pytest bootstrap: make the repo root importable so tests can
`import wifi_observer` / `import plot` regardless of where pytest is invoked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
