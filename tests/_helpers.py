"""Shared test fixtures: synthetic pose data and fake detectors.

Kept detector-independent (no torch/ultralytics import) so the bulk of the
test suite runs fast, offline, and without a GPU. Only a small handful of
tests in test_video_processor_integration.py (not part of the default
suite) would exercise the real YoloPoseDetector.
"""
from __future__ import annotations

import math

from gaitapp.analysis.landmarks import Keypoint, KeypointName, NUM_KEYPOINTS, PoseFrame


def make_pose_frame(
    frame_index: int,
    timestamp: float,
    *,
    hip_y: float = 300.0,
    shoulder_y: float = 100.0,
    torso_center_x: float = 100.0,
    shoulder_half_width: float = 10.0,
    left_ankle_y: float = 450.0,
    right_ankle_y: float = 450.0,
    confidence: float = 0.9,
) -> PoseFrame:
    keypoints = [Keypoint(0.0, 0.0, 0.0) for _ in range(NUM_KEYPOINTS)]

    def set_kp(name: KeypointName, x: float, y: float) -> None:
        keypoints[int(name)] = Keypoint(x=x, y=y, confidence=confidence)

    set_kp(KeypointName.LEFT_SHOULDER, torso_center_x - shoulder_half_width, shoulder_y)
    set_kp(KeypointName.RIGHT_SHOULDER, torso_center_x + shoulder_half_width, shoulder_y)
    set_kp(KeypointName.LEFT_HIP, torso_center_x - shoulder_half_width, hip_y)
    set_kp(KeypointName.RIGHT_HIP, torso_center_x + shoulder_half_width, hip_y)
    set_kp(KeypointName.LEFT_ANKLE, torso_center_x - shoulder_half_width, left_ankle_y)
    set_kp(KeypointName.RIGHT_ANKLE, torso_center_x + shoulder_half_width, right_ankle_y)

    return PoseFrame(frame_index=frame_index, timestamp=timestamp, keypoints=tuple(keypoints))


def make_walking_sequence(
    duration_s: float = 10.0,
    fps: float = 30.0,
    step_frequency_hz: float = 1.0,
    swing_amplitude_px: float = 40.0,
    hip_y: float = 300.0,
    shoulder_y: float = 100.0,
) -> list[PoseFrame]:
    """Synthetic side-view walking clip: ankles swing out of phase.

    Each leg's ankle traces a rectified sine (zero while planted, one bump
    per step while swinging), the two legs offset by half a cycle -- a
    deliberately simple stand-in for real gait, just enough to exercise
    the peak-finding step-detection math end to end.
    """
    n_frames = max(1, int(duration_s * fps))
    frames = []
    for i in range(n_frames):
        t = i / fps
        left_lift = max(0.0, math.sin(2 * math.pi * step_frequency_hz * t))
        right_lift = max(0.0, math.sin(2 * math.pi * step_frequency_hz * t + math.pi))
        left_ankle_y = hip_y + 150 - swing_amplitude_px * left_lift
        right_ankle_y = hip_y + 150 - swing_amplitude_px * right_lift
        frames.append(
            make_pose_frame(
                i,
                t,
                hip_y=hip_y,
                shoulder_y=shoulder_y,
                left_ankle_y=left_ankle_y,
                right_ankle_y=right_ankle_y,
            )
        )
    return frames


class FakePoseDetector:
    """Deterministic PoseDetector: replays a precomputed list of frames.

    Standing in for YoloPoseDetector so worker/thread-start tests never
    need torch, ultralytics, or a downloaded model.
    """

    def __init__(self, frames: list[PoseFrame]) -> None:
        self._frames = frames

    def detect(self, frame, frame_index: int, timestamp: float) -> PoseFrame:
        base = self._frames[frame_index] if frame_index < len(self._frames) else self._frames[-1]
        return PoseFrame(frame_index=frame_index, timestamp=timestamp, keypoints=base.keypoints)


class FakeErrorDetector:
    """A PoseDetector that always raises, for exercising error paths."""

    def detect(self, frame, frame_index: int, timestamp: float) -> PoseFrame:
        raise RuntimeError("boom: fake detector failure")
