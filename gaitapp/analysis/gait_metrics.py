"""Step detection and gait-metric computation from a pose-frame sequence.

Algorithm summary
------------------
For a side-view walking video, each ankle rises during its leg's swing
phase and returns to (roughly) its lowest point at ground contact. We
track the vertical position of each ankle relative to the hip midpoint,
scale-normalize by torso height (so pixel distance is comparable across
subjects/camera distances), and smooth the resulting signal. A step is
counted at each local maximum of "foot lift" for a given leg -- i.e. the
apex of that leg's swing phase, which happens once per gait cycle step.

This is a deliberately simple, explainable heuristic (not a learned
model) so it stays debuggable against real footage; scipy.signal.find_peaks
does the actual peak finding.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from gaitapp.analysis.landmarks import KeypointName, PoseFrame

MIN_TORSO_HEIGHT_PX = 1e-3


@dataclass(frozen=True)
class StepEvent:
    leg: str  # "left" or "right"
    frame_index: int
    timestamp: float


@dataclass(frozen=True)
class GaitMetrics:
    step_count: int
    left_step_count: int
    right_step_count: int
    cadence_steps_per_min: float | None
    mean_step_time_s: float | None
    step_time_std_s: float | None
    symmetry_index_pct: float | None
    duration_s: float
    steps: tuple[StepEvent, ...]


def _foot_lift_signal(frames: list[PoseFrame], ankle: KeypointName, min_confidence: float) -> np.ndarray:
    """Torso-height-normalized vertical distance of an ankle above the hip.

    NaN where the ankle or hip midpoint isn't confidently detected; the
    caller is responsible for handling gaps before peak-finding.
    """
    values = np.full(len(frames), np.nan, dtype=float)
    for i, pf in enumerate(frames):
        if not pf.is_visible(ankle, min_confidence):
            continue
        if not (
            pf.is_visible(KeypointName.LEFT_HIP, min_confidence)
            and pf.is_visible(KeypointName.RIGHT_HIP, min_confidence)
        ):
            continue
        torso = pf.torso_height
        if torso < MIN_TORSO_HEIGHT_PX:
            continue
        _, hip_y = pf.hip_midpoint
        ankle_y = pf.get(ankle).y
        # Image y grows downward, so "lift above hip" is (hip_y - ankle_y);
        # this is negative while the foot is below the hip, which is fine --
        # only the shape of the oscillation matters for peak-finding.
        values[i] = (hip_y - ankle_y) / torso
    return values


def _interpolate_gaps(values: np.ndarray) -> np.ndarray:
    """Linearly fills NaN gaps so find_peaks sees a continuous signal."""
    values = values.copy()
    nan_mask = np.isnan(values)
    if nan_mask.all():
        return np.zeros_like(values)
    if not nan_mask.any():
        return values
    indices = np.arange(len(values))
    values[nan_mask] = np.interp(indices[nan_mask], indices[~nan_mask], values[~nan_mask])
    return values


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(values) < window:
        return values
    kernel = np.ones(window) / window
    return np.convolve(values, kernel, mode="same")


def _detect_leg_steps(
    frames: list[PoseFrame],
    ankle: KeypointName,
    leg_name: str,
    fps: float,
    min_confidence: float,
    smoothing_window: int,
) -> list[StepEvent]:
    raw = _foot_lift_signal(frames, ankle, min_confidence)
    filled = _interpolate_gaps(raw)
    smoothed = _smooth(filled, smoothing_window)

    if len(smoothed) < 3:
        return []

    # A step (swing apex) can't repeat faster than ~1.5 Hz per leg for a
    # clinical/prosthetic gait video; this distance guard suppresses
    # spurious double-counting from tracking jitter.
    min_distance_frames = max(1, int(fps * 0.35))
    peak_indices, _ = find_peaks(
        smoothed,
        distance=min_distance_frames,
        prominence=np.nanstd(smoothed) * 0.25 if np.nanstd(smoothed) > 0 else None,
    )

    return [
        StepEvent(leg=leg_name, frame_index=frames[i].frame_index, timestamp=frames[i].timestamp)
        for i in peak_indices
    ]


def compute_gait_metrics(
    frames: list[PoseFrame],
    fps: float,
    min_confidence: float = 0.3,
    smoothing_window_s: float = 0.1,
) -> GaitMetrics:
    """Computes step count and timing metrics from a sequence of pose frames.

    `frames` must be ordered by increasing frame_index/timestamp and come
    from a single continuous side-view walking clip.
    """
    if fps <= 0:
        raise ValueError("fps must be positive")

    duration_s = frames[-1].timestamp - frames[0].timestamp if len(frames) >= 2 else 0.0
    smoothing_window = max(1, int(round(smoothing_window_s * fps)))

    left_steps = _detect_leg_steps(
        frames, KeypointName.LEFT_ANKLE, "left", fps, min_confidence, smoothing_window
    )
    right_steps = _detect_leg_steps(
        frames, KeypointName.RIGHT_ANKLE, "right", fps, min_confidence, smoothing_window
    )

    all_steps = sorted(left_steps + right_steps, key=lambda s: s.timestamp)
    step_count = len(all_steps)

    cadence = None
    mean_step_time = None
    step_time_std = None
    if step_count >= 2:
        inter_step_times = np.diff([s.timestamp for s in all_steps])
        inter_step_times = inter_step_times[inter_step_times > 0]
        if len(inter_step_times) > 0:
            mean_step_time = float(np.mean(inter_step_times))
            step_time_std = float(np.std(inter_step_times))
    if duration_s > 0 and step_count > 0:
        cadence = step_count / duration_s * 60.0

    symmetry_index = None
    if left_steps and right_steps:
        left_mean = float(np.mean(np.diff([s.timestamp for s in left_steps]))) if len(left_steps) >= 2 else None
        right_mean = float(np.mean(np.diff([s.timestamp for s in right_steps]))) if len(right_steps) >= 2 else None
        if left_mean and right_mean and (left_mean + right_mean) > 0:
            symmetry_index = abs(left_mean - right_mean) / ((left_mean + right_mean) / 2) * 100.0

    return GaitMetrics(
        step_count=step_count,
        left_step_count=len(left_steps),
        right_step_count=len(right_steps),
        cadence_steps_per_min=cadence,
        mean_step_time_s=mean_step_time,
        step_time_std_s=step_time_std,
        symmetry_index_pct=symmetry_index,
        duration_s=duration_s,
        steps=tuple(all_steps),
    )
