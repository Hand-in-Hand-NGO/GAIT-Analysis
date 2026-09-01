"""Drives the real background-thread analysis path against a synthetic clip.

This exists to close a specific testing blind spot: calling worker.run()
directly on the main thread does NOT reproduce a production run, because
production starts workers via .start() on a real OS thread, and
torch/YOLO's native-library initialization (BLAS/OpenMP) can behave
differently the first time it happens off the main thread. This smoke test
drives both workers exactly the way gaitapp/ui/main_window.py does -- via
.start(), pumping a real Qt event loop until either a result or an error
signal arrives (or a timeout, treated as failure).

Reachable two ways: `python -m gaitapp.main --smoke-test` (or the
scripts/smoke_test.py dev wrapper) in an unfrozen checkout, and
`GaitAnalysis.exe --smoke-test` against the PyInstaller build -- both paths
call run_smoke_test() below, so there is exactly one implementation to keep
correct.
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from gaitapp.analysis.video_processor import PoseAnalysisWorker, ViewClassificationWorker
from gaitapp.analysis.yolo_pose_detector import YoloPoseDetector

SMOKE_TEST_TIMEOUT_S = 120
SMOKE_TEST_FRAME_COUNT = 30
SMOKE_TEST_FRAME_HEIGHT = 480
SMOKE_TEST_FRAME_WIDTH = 640


def _write_synthetic_video(path: Path) -> None:
    """A short solid-color synthetic clip -- enough to exercise the full
    pipeline (video I/O, model init and inference, step-detection math)
    without depending on any real patient footage being available in CI."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(
        str(path), fourcc, 30.0, (SMOKE_TEST_FRAME_WIDTH, SMOKE_TEST_FRAME_HEIGHT)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open VideoWriter for {path}")
    try:
        for i in range(SMOKE_TEST_FRAME_COUNT):
            shade = (i * 8) % 256
            frame = np.full(
                (SMOKE_TEST_FRAME_HEIGHT, SMOKE_TEST_FRAME_WIDTH, 3),
                (shade, 128, 255 - shade),
                dtype=np.uint8,
            )
            writer.write(frame)
    finally:
        writer.release()


def run_smoke_test() -> int:
    print("[smoke-test] starting", flush=True)
    QCoreApplication.instance() or QCoreApplication(sys.argv[:1])

    with tempfile.TemporaryDirectory(prefix="gaitapp_smoke_") as tmp_dir:
        video_path = Path(tmp_dir) / "synthetic_clip.mp4"
        try:
            _write_synthetic_video(video_path)
        except Exception:
            print("[smoke-test] FAILED building synthetic clip:", flush=True)
            traceback.print_exc()
            return 1

        view_ok = _run_view_classification_worker(video_path)
        pose_ok = _run_pose_analysis_worker(video_path)

    ok = view_ok and pose_ok
    print("[smoke-test] PASSED" if ok else "[smoke-test] FAILED", flush=True)
    return 0 if ok else 1


def _run_view_classification_worker(video_path: Path) -> bool:
    print("[smoke-test] driving ViewClassificationWorker via .start()", flush=True)
    worker = ViewClassificationWorker(video_path, YoloPoseDetector)
    return _drive_worker(worker, success_signal="classified", label="ViewClassificationWorker")


def _run_pose_analysis_worker(video_path: Path) -> bool:
    print("[smoke-test] driving PoseAnalysisWorker via .start()", flush=True)
    worker = PoseAnalysisWorker(side_video_path=video_path, detector_factory=YoloPoseDetector)
    return _drive_worker(worker, success_signal="finished", label="PoseAnalysisWorker")


def _drive_worker(worker, success_signal: str, label: str) -> bool:
    loop = QEventLoop()
    outcome = {"succeeded": False, "error": None}

    def on_success(_result=None) -> None:
        outcome["succeeded"] = True
        loop.quit()

    def on_error(message: str) -> None:
        outcome["error"] = message
        loop.quit()

    getattr(worker, success_signal).connect(on_success)
    worker.error.connect(on_error)

    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.timeout.connect(loop.quit)
    timeout_timer.start(SMOKE_TEST_TIMEOUT_S * 1000)

    worker.start()
    loop.exec()
    timeout_timer.stop()
    worker.wait(5000)

    if outcome["error"] is not None:
        print(f"[smoke-test] {label} reported an error:\n{outcome['error']}", flush=True)
        return False
    if not outcome["succeeded"]:
        print(
            f"[smoke-test] {label} timed out after {SMOKE_TEST_TIMEOUT_S}s without finishing",
            flush=True,
        )
        return False
    print(f"[smoke-test] {label} OK", flush=True)
    return True


if __name__ == "__main__":
    sys.exit(run_smoke_test())
