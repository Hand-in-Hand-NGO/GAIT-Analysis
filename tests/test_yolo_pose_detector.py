"""Tests the detector's non-torch-dependent logic in isolation.

Deliberately never imports/constructs YoloPoseDetector itself (that needs
ultralytics+torch and a downloaded model) -- only the pure functions
(default_model_path, _best_subject_to_pose_frame) that don't touch torch,
using fake result objects that mimic the shape of ultralytics' output.
"""
import sys

import numpy as np
import pytest

from gaitapp.analysis.landmarks import NUM_KEYPOINTS
from gaitapp.analysis.yolo_pose_detector import (
    DEFAULT_MODEL_NAME,
    _best_subject_to_pose_frame,
    default_model_path,
)


def test_default_model_path_in_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert default_model_path() == DEFAULT_MODEL_NAME


def test_default_model_path_frozen_uses_meipass_bundle(monkeypatch, tmp_path):
    # PyInstaller >= 6.0 onedir builds put --add-data files in a separate
    # "_internal" dir, not next to the exe -- sys._MEIPASS is what actually
    # points at the right place in both onedir and onefile layouts.
    meipass_dir = tmp_path / "_internal"
    meipass_dir.mkdir()
    bundled = meipass_dir / DEFAULT_MODEL_NAME
    bundled.write_bytes(b"fake weights")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GaitAnalysis.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    assert default_model_path() == str(bundled)


def test_default_model_path_frozen_without_meipass_falls_back_to_exe_dir(monkeypatch, tmp_path):
    bundled = tmp_path / DEFAULT_MODEL_NAME
    bundled.write_bytes(b"fake weights")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GaitAnalysis.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert default_model_path() == str(bundled)


def test_default_model_path_frozen_without_bundle_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GaitAnalysis.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert default_model_path() == DEFAULT_MODEL_NAME


class _FakeTensor:
    """Mimics the small slice of the torch.Tensor API this module relies on."""

    def __init__(self, array):
        self._array = np.asarray(array)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeBoxes:
    def __init__(self, confidences):
        self.conf = _FakeTensor(confidences)

    def __len__(self):
        return len(self.conf.numpy())


class _FakeKeypoints:
    def __init__(self, xy, conf):
        self.xy = [_FakeTensor(row) for row in xy]
        self.conf = [_FakeTensor(row) for row in conf] if conf is not None else None


class _FakeResult:
    def __init__(self, boxes, keypoints):
        self.boxes = boxes
        self.keypoints = keypoints


def test_best_subject_picks_highest_confidence_box():
    xy = np.zeros((2, NUM_KEYPOINTS, 2))
    xy[1] = np.arange(NUM_KEYPOINTS * 2).reshape(NUM_KEYPOINTS, 2)
    conf = np.full((2, NUM_KEYPOINTS), 0.9)
    result = _FakeResult(boxes=_FakeBoxes([0.4, 0.8]), keypoints=_FakeKeypoints(xy, conf))

    pose_frame = _best_subject_to_pose_frame([result], frame_index=3, timestamp=0.1)

    assert pose_frame.frame_index == 3
    assert pose_frame.timestamp == pytest.approx(0.1)
    # detection index 1 (confidence 0.8) should win over index 0 (0.4)
    assert pose_frame.keypoints[0].x == pytest.approx(xy[1][0][0])
    assert pose_frame.keypoints[0].confidence == pytest.approx(0.9)


def test_no_detections_returns_empty_pose_frame():
    result = _FakeResult(
        boxes=_FakeBoxes([]),
        keypoints=_FakeKeypoints(np.zeros((0, NUM_KEYPOINTS, 2)), np.zeros((0, NUM_KEYPOINTS))),
    )
    pose_frame = _best_subject_to_pose_frame([result], frame_index=0, timestamp=0.0)
    assert all(kp.confidence == 0.0 for kp in pose_frame.keypoints)


def test_empty_results_list_returns_empty_pose_frame():
    pose_frame = _best_subject_to_pose_frame([], frame_index=5, timestamp=1.0)
    assert pose_frame.frame_index == 5
    assert all(kp.confidence == 0.0 for kp in pose_frame.keypoints)
