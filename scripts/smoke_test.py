"""Dev/CI convenience entry point for the smoke test.

Equivalent to `python -m gaitapp.main --smoke-test`, and to what the
PyInstaller-frozen `GaitAnalysis.exe --smoke-test` runs. The actual test
logic lives in gaitapp/smoke_test.py (part of the bundled package, so it's
reachable both here and from the frozen exe) -- kept in exactly one place
so the two invocation paths can't drift apart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gaitapp.smoke_test import run_smoke_test  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_smoke_test())
