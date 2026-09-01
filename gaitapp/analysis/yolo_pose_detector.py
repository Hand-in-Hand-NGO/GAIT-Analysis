"""Thin wrapper around ultralytics YOLO11-pose.

Kept separate from video_processor.py so the heavy torch/ultralytics import
and the actual model call are isolated behind a small interface
(PoseDetector) that tests can substitute with a fake implementation without
downloading model weights or importing torch at all.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

import numpy as np

from gaitapp.analysis.landmarks import (
    Keypoint,
    NUM_KEYPOINTS,
    PoseFrame,
    empty_pose_frame,
)

DEFAULT_MODEL_NAME = "yolo11n-pose.pt"
DEFAULT_MIN_BOX_CONFIDENCE = 0.4


class PoseDetector(Protocol):
    """Interface implemented by YoloPoseDetector and by test fakes."""

    def detect(self, frame: np.ndarray, frame_index: int, timestamp: float) -> PoseFrame:
        ...


class YoloPoseDetector:
    """Runs ultralytics YOLO11-pose on individual video frames.

    The ultralytics/torch import happens lazily inside __init__ so that
    importing this module (e.g. for type checking or for building the UI)
    never requires torch to be installed.
    """

    def __init__(
        self,
        model_name: str | None = None,
        min_box_confidence: float = DEFAULT_MIN_BOX_CONFIDENCE,
        device: str | None = None,
    ) -> None:
        from ultralytics import YOLO  # local import, see docstring

        self._model = YOLO(model_name or default_model_path())
        self._min_box_confidence = min_box_confidence
        self._device = device

    def detect(self, frame: np.ndarray, frame_index: int, timestamp: float) -> PoseFrame:
        results = self._model.predict(
            source=frame,
            device=self._device,
            verbose=False,
            conf=self._min_box_confidence,
        )
        return _best_subject_to_pose_frame(results, frame_index, timestamp)


def _best_subject_to_pose_frame(results, frame_index: int, timestamp: float) -> PoseFrame:
    """Picks the highest-confidence detected person and converts to PoseFrame.

    A gait video is expected to contain a single walking subject; if YOLO
    finds several boxes (e.g. a clinician standing nearby) we keep the one
    with the highest detection confidence rather than guessing further.
    """
    if not results:
        return empty_pose_frame(frame_index, timestamp)

    result = results[0]
    if result.keypoints is None or result.boxes is None or len(result.boxes) == 0:
        return empty_pose_frame(frame_index, timestamp)

    confidences = result.boxes.conf.cpu().numpy()
    best_idx = int(np.argmax(confidences))

    xy = result.keypoints.xy[best_idx].cpu().numpy()  # (NUM_KEYPOINTS, 2)
    kp_conf = (
        result.keypoints.conf[best_idx].cpu().numpy()
        if result.keypoints.conf is not None
        else np.ones(len(xy))
    )

    if len(xy) != NUM_KEYPOINTS:
        return empty_pose_frame(frame_index, timestamp)

    keypoints = tuple(
        Keypoint(x=float(xy[i][0]), y=float(xy[i][1]), confidence=float(kp_conf[i]))
        for i in range(NUM_KEYPOINTS)
    )
    return PoseFrame(frame_index=frame_index, timestamp=timestamp, keypoints=keypoints)


def default_model_path() -> str:
    """Resolves the pose model to load.

    In a PyInstaller --onedir build there is no guarantee the frozen
    executable can reach the network to let ultralytics auto-download
    weights, so scripts/build_windows.py bundles the weights file via
    --add-data. Bundled data does NOT land next to the executable itself --
    PyInstaller >= 6.0 puts onedir data files in a separate "_internal"
    directory, and that detail is exactly what sys._MEIPASS is for: it's
    set to the right resource directory in either onedir or onefile mode,
    so use that instead of guessing the layout by hand. Falls back to the
    bare model name (which ultralytics resolves itself, downloading to its
    local cache on first use) when unfrozen, or if the bundle is missing.
    """
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled = bundle_dir / DEFAULT_MODEL_NAME
        if bundled.exists():
            return str(bundled)
    return DEFAULT_MODEL_NAME
