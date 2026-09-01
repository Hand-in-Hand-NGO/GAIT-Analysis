# GAIT-Analysis

Desktop app (PySide6 + YOLO11-pose) that analyzes patient walking videos
(front + side view pairs) and reports step counts and gait metrics
(cadence, step time, left/right symmetry).

## Running from source

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m gaitapp.main
```

Pick a side-view video (required) and, optionally, a front-view video, then
click "Run Gait Analysis".

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite mocks out the YOLO detector (`tests/_helpers.py`) so it runs fast
and offline. It specifically drives the background workers
(`PoseAnalysisWorker`, `ViewClassificationWorker`) via `.start()` rather
than calling `.run()` directly, since only `.start()` exercises the real
background-OS-thread path that production uses.

To verify against the real model (downloads `yolo11n-pose.pt` on first
run):

```bash
python scripts/smoke_test.py
```

## Building the Windows executable

```bash
python scripts/build_windows.py
```

Produces a `--onedir` PyInstaller build at `dist/GaitAnalysis/`. Windows-only
(hardcodes `;` as the PyInstaller `--add-data` separator); to test a frozen
build locally on Linux/Mac, invoke `pyinstaller` directly with `:` instead.

`.github/workflows/build-windows.yml` runs the test suite, builds the
frozen executable, smoke-tests it directly (`GaitAnalysis.exe --smoke-test`)
via a real Qt event loop, and on success publishes a rolling GitHub Release
(tag `windows-build-latest`).

## Project layout

- `gaitapp/analysis/` -- pose landmark types, the YOLO detector wrapper,
  step-detection/gait-metric math, and front/side view classification.
- `gaitapp/analysis/video_processor.py` -- `PoseAnalysisWorker` and
  `ViewClassificationWorker`, the `QThread`s that run the above against
  video files in the background.
- `gaitapp/ui/main_window.py` -- the main application window.
- `gaitapp/main.py` -- entry point; sets `KMP_DUPLICATE_LIB_OK` and enables
  `faulthandler` (logging to `%TEMP%/gaitapp_crash.log`) before anything
  else, to catch native-level crashes that a plain `try/except` can't.
- `gaitapp/smoke_test.py` -- the smoke test itself, reachable both via
  `GaitAnalysis.exe --smoke-test` (frozen) and `scripts/smoke_test.py` (dev).
