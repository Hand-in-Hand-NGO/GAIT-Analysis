"""Shared pose-landmark types used across the analysis pipeline.

YOLO11-pose (ultralytics) emits the standard COCO-17 keypoint layout. This
module wraps that raw output in typed, named structures so the rest of the
codebase never has to remember magic keypoint indices.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class KeypointName(IntEnum):
    """COCO-17 keypoint order, as produced by ultralytics YOLO pose models."""

    NOSE = 0
    LEFT_EYE = 1
    RIGHT_EYE = 2
    LEFT_EAR = 3
    RIGHT_EAR = 4
    LEFT_SHOULDER = 5
    RIGHT_SHOULDER = 6
    LEFT_ELBOW = 7
    RIGHT_ELBOW = 8
    LEFT_WRIST = 9
    RIGHT_WRIST = 10
    LEFT_HIP = 11
    RIGHT_HIP = 12
    LEFT_KNEE = 13
    RIGHT_KNEE = 14
    LEFT_ANKLE = 15
    RIGHT_ANKLE = 16


NUM_KEYPOINTS = len(KeypointName)


@dataclass(frozen=True)
class Keypoint:
    """A single 2D keypoint with detection confidence."""

    x: float
    y: float
    confidence: float

    def is_visible(self, min_confidence: float = 0.3) -> bool:
        return self.confidence >= min_confidence


@dataclass(frozen=True)
class PoseFrame:
    """The detected pose for one video frame (single primary subject)."""

    frame_index: int
    timestamp: float  # seconds
    keypoints: tuple[Keypoint, ...]  # length == NUM_KEYPOINTS

    def get(self, name: KeypointName) -> Keypoint:
        return self.keypoints[int(name)]

    def is_visible(self, name: KeypointName, min_confidence: float = 0.3) -> bool:
        return self.get(name).is_visible(min_confidence)

    @property
    def hip_midpoint(self) -> tuple[float, float]:
        left = self.get(KeypointName.LEFT_HIP)
        right = self.get(KeypointName.RIGHT_HIP)
        return (left.x + right.x) / 2.0, (left.y + right.y) / 2.0

    @property
    def shoulder_midpoint(self) -> tuple[float, float]:
        left = self.get(KeypointName.LEFT_SHOULDER)
        right = self.get(KeypointName.RIGHT_SHOULDER)
        return (left.x + right.x) / 2.0, (left.y + right.y) / 2.0

    @property
    def torso_height(self) -> float:
        """Pixel distance from hip midpoint to shoulder midpoint.

        Used throughout the pipeline as a scale reference so gait signals
        are comparable across subjects/cameras at different distances.
        """
        hx, hy = self.hip_midpoint
        sx, sy = self.shoulder_midpoint
        return ((hx - sx) ** 2 + (hy - sy) ** 2) ** 0.5

    @property
    def shoulder_width(self) -> float:
        left = self.get(KeypointName.LEFT_SHOULDER)
        right = self.get(KeypointName.RIGHT_SHOULDER)
        return ((left.x - right.x) ** 2 + (left.y - right.y) ** 2) ** 0.5


NoneKeypoint = Keypoint(x=0.0, y=0.0, confidence=0.0)


def empty_pose_frame(frame_index: int, timestamp: float) -> PoseFrame:
    """A PoseFrame representing "no subject detected" for this frame."""
    return PoseFrame(
        frame_index=frame_index,
        timestamp=timestamp,
        keypoints=tuple(NoneKeypoint for _ in range(NUM_KEYPOINTS)),
    )
