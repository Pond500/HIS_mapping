"""
The scenario suite (scenarios/) as one test, so an ordinary `pytest tests` run covers
every situation the system can be in, end to end: upload -> agent graph -> store ->
review -> conflict -> export.

It runs in a subprocess because it must set DATABASE_URL to its own scratch database
BEFORE the app is imported, and this process has already imported the app. On failure
the output names each failing case and what it saw.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_scenario_passes():
    run = subprocess.run([sys.executable, "-m", "scenarios.run"], cwd=ROOT,
                         capture_output=True, text=True, timeout=600)
    lines = [ln for ln in run.stdout.splitlines() if ln.strip() and not ln.startswith("INFO")]
    failed = [ln for ln in lines if "FAIL" in ln]
    assert run.returncode == 0, "\n".join(lines[-40:] + run.stderr.splitlines()[-15:])
    assert not failed and lines[-1].split()[1] == "passed,", lines[-3:]
