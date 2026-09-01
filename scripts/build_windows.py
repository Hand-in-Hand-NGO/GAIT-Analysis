"""Builds the Windows frozen executable via PyInstaller.

--onedir, not --onefile: torch's DLL loading is unreliable when run from
--onefile's self-extracting temp directory, so onedir (a directory of
loose files next to the exe) is the reliable choice here.

Windows-only: hardcodes ';' as the --add-data path separator, which is
what PyInstaller expects on Windows (it uses the host OS's own PATH
separator for that flag -- ':' on Linux/Mac). If you need to test a frozen
build locally on Linux/Mac, invoke `pyinstaller` directly with ':' instead
of running this script.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "GaitAnalysis"
ENTRY_POINT = REPO_ROOT / "gaitapp" / "main.py"
MODEL_FILE = REPO_ROOT / "yolo11n-pose.pt"


def main() -> int:
    if not ENTRY_POINT.exists():
        print(f"Entry point not found: {ENTRY_POINT}", file=sys.stderr)
        return 1

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        APP_NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
    ]

    if MODEL_FILE.exists():
        # Bundles the pre-downloaded weights next to the exe so the frozen
        # app works without network access; see
        # gaitapp/analysis/yolo_pose_detector.py:default_model_path().
        args += ["--add-data", f"{MODEL_FILE};."]
    else:
        print(
            f"Warning: {MODEL_FILE} not found -- building without bundled model "
            "weights. The frozen app will try to download them on first run, "
            "which requires network access.",
            file=sys.stderr,
        )

    args.append(str(ENTRY_POINT))

    print("Running:", " ".join(args))
    result = subprocess.run(args, cwd=REPO_ROOT)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
