"""Background QThread workers that run pose detection against video files.

Both workers construct their PoseDetector *inside run()*, i.e. on the
worker's own OS thread rather than the Qt main thread. This is deliberate:
torch/ultralytics model initialization has native-library behavior (BLAS,
OpenMP) that differs the first time it happens on a background thread, so
constructing the detector here is what actually exercises that path in
production, and is exactly what scripts/smoke_test.py needs to replicate
via .start() rather than a same-thread .run() call.

Every public entry point here catches Exception and emits it as a full
traceback over the `error` signal, so a caught Python exception always
surfaces to the UI as a dialog. It cannot catch a native crash (segfault /
access violation / abort) -- that terminates the process before any Qt
signal can be emitted, which is why gaitapp/main.py separately installs
faulthandler as a last-resort diagnostic.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
from PySide6.QtCore import QThread, Signal

from gaitapp.analysis.gait_metrics import GaitMetrics, compute_gait_metrics
from gaitapp.analysis.landmarks import PoseFrame
from gaitapp.analysis.view_classification import ViewClassificationResult, classify_view
from gaitapp.analysis.yolo_pose_detector import PoseDetector

DetectorFactory = Callable[[], PoseDetector]


class VideoOpenError(RuntimeError):
    """Raised when OpenCV can't open a given video file."""


def get_video_fps(video_path: str | Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoOpenError(f"Could not open video file: {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        return fps if fps and fps > 0 else 30.0
    finally:
        cap.release()


def _get_frame_count(video_path: str | Path) -> int | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        return int(count) if count and count > 0 else None
    finally:
        cap.release()


def iter_video_frames(video_path: str | Path):
    """Yields (frame_index, timestamp_seconds, frame_bgr) for a video file."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoOpenError(f"Could not open video file: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    try:
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame_index, frame_index / fps, frame
            frame_index += 1
    finally:
        cap.release()


def run_pose_detection(
    video_path: str | Path,
    detector: PoseDetector,
    progress_callback: Callable[[float], None] | None = None,
    max_frames: int | None = None,
) -> list[PoseFrame]:
    total = _get_frame_count(video_path)
    frames: list[PoseFrame] = []
    for frame_index, timestamp, frame in iter_video_frames(video_path):
        if max_frames is not None and frame_index >= max_frames:
            break
        frames.append(detector.detect(frame, frame_index, timestamp))
        if progress_callback is not None and total:
            progress_callback(min(99.0, frame_index / total * 100.0))
    return frames


@dataclass(frozen=True)
class GaitAnalysisResult:
    side_metrics: GaitMetrics
    side_view_result: ViewClassificationResult
    front_view_result: ViewClassificationResult | None


class ViewClassificationWorker(QThread):
    """Classifies a single video as front-view or side-view."""

    classified = Signal(object)  # ViewClassificationResult
    error = Signal(str)

    def __init__(
        self,
        video_path: str | Path,
        detector_factory: DetectorFactory,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._detector_factory = detector_factory

    def run(self) -> None:
        try:
            detector = self._detector_factory()
            frames = run_pose_detection(self._video_path, detector)
            result = classify_view(frames)
        except Exception:
            self.error.emit(traceback.format_exc())
            return
        self.classified.emit(result)


class PoseAnalysisWorker(QThread):
    """Runs full gait analysis on a side-view video (plus optional front view)."""

    progress = Signal(int)
    finished = Signal(object)  # GaitAnalysisResult
    error = Signal(str)

    def __init__(
        self,
        side_video_path: str | Path,
        detector_factory: DetectorFactory,
        front_video_path: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._side_video_path = side_video_path
        self._front_video_path = front_video_path
        self._detector_factory = detector_factory

    def run(self) -> None:
        try:
            detector = self._detector_factory()
            fps = get_video_fps(self._side_video_path)

            self.progress.emit(0)
            side_weight = 0.7 if self._front_video_path else 1.0
            side_frames = run_pose_detection(
                self._side_video_path,
                detector,
                progress_callback=lambda p: self.progress.emit(int(p * side_weight)),
            )
            side_view_result = classify_view(side_frames)

            front_view_result = None
            if self._front_video_path:
                base = int(100 * side_weight)
                front_frames = run_pose_detection(
                    self._front_video_path,
                    detector,
                    progress_callback=lambda p: self.progress.emit(base + int(p * (1 - side_weight))),
                )
                front_view_result = classify_view(front_frames)

            metrics = compute_gait_metrics(side_frames, fps=fps)
        except Exception:
            self.error.emit(traceback.format_exc())
            return

        self.progress.emit(100)
        self.finished.emit(
            GaitAnalysisResult(
                side_metrics=metrics,
                side_view_result=side_view_result,
                front_view_result=front_view_result,
            )
        )
