"""Exercises the QEventLoop-driving glue in gaitapp/smoke_test.py itself.

Uses a monkeypatched fake detector in place of YoloPoseDetector so this
runs fast and offline -- verifying the smoke test's own success/failure/
timeout plumbing is correct is a different concern from verifying the real
model loads cleanly on a background thread (that real-model check happens
in CI, against the actual frozen build, with a real GPU/CPU model).
"""
import time

import cv2

import gaitapp.smoke_test as smoke_test_module
from gaitapp.analysis.landmarks import empty_pose_frame
from tests._helpers import FakeErrorDetector, FakePoseDetector, make_walking_sequence


def test_write_synthetic_video_creates_readable_clip(tmp_path):
    path = tmp_path / "clip.mp4"
    smoke_test_module._write_synthetic_video(path)
    assert path.exists()

    cap = cv2.VideoCapture(str(path))
    assert cap.isOpened()
    count = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        count += 1
    cap.release()
    assert count == smoke_test_module.SMOKE_TEST_FRAME_COUNT


def test_run_smoke_test_passes_with_working_detector(monkeypatch):
    frames = make_walking_sequence(
        duration_s=smoke_test_module.SMOKE_TEST_FRAME_COUNT / 30.0, fps=30.0, step_frequency_hz=1.0
    )
    monkeypatch.setattr(smoke_test_module, "YoloPoseDetector", lambda: FakePoseDetector(frames))

    assert smoke_test_module.run_smoke_test() == 0


def test_run_smoke_test_fails_when_detector_raises(monkeypatch):
    monkeypatch.setattr(smoke_test_module, "YoloPoseDetector", FakeErrorDetector)

    assert smoke_test_module.run_smoke_test() == 1


def test_run_smoke_test_fails_on_timeout(monkeypatch):
    class SlowDetector:
        def detect(self, frame, frame_index, timestamp):
            time.sleep(0.05)
            return empty_pose_frame(frame_index, timestamp)

    monkeypatch.setattr(smoke_test_module, "YoloPoseDetector", SlowDetector)
    monkeypatch.setattr(smoke_test_module, "SMOKE_TEST_TIMEOUT_S", 0.001)

    assert smoke_test_module.run_smoke_test() == 1
