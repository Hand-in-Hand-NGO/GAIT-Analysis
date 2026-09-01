import pytest

from gaitapp.analysis.gait_metrics import compute_gait_metrics
from gaitapp.analysis.landmarks import KeypointName


def test_step_count_and_cadence_for_regular_gait(walking_sequence_factory):
    frames = walking_sequence_factory(duration_s=10.0, fps=30.0, step_frequency_hz=1.0)
    metrics = compute_gait_metrics(frames, fps=30.0)

    # ~1 step/sec/leg over 10s -> ~10 left + ~10 right = ~20 total.
    assert 16 <= metrics.step_count <= 22
    assert abs(metrics.left_step_count - metrics.right_step_count) <= 2
    assert metrics.cadence_steps_per_min is not None
    assert 90 <= metrics.cadence_steps_per_min <= 140
    assert metrics.symmetry_index_pct is not None
    assert metrics.symmetry_index_pct < 15


def test_faster_cadence_detected_as_more_steps(walking_sequence_factory):
    slow = walking_sequence_factory(duration_s=10.0, fps=30.0, step_frequency_hz=0.7)
    fast = walking_sequence_factory(duration_s=10.0, fps=30.0, step_frequency_hz=1.5)

    slow_metrics = compute_gait_metrics(slow, fps=30.0)
    fast_metrics = compute_gait_metrics(fast, fps=30.0)

    assert fast_metrics.step_count > slow_metrics.step_count
    assert fast_metrics.cadence_steps_per_min > slow_metrics.cadence_steps_per_min


def test_no_motion_yields_zero_steps(pose_frame_factory):
    frames = [pose_frame_factory(i, i / 30.0) for i in range(60)]
    metrics = compute_gait_metrics(frames, fps=30.0)
    assert metrics.step_count == 0
    assert metrics.cadence_steps_per_min is None
    assert metrics.mean_step_time_s is None


def test_duration_computed_from_timestamps(pose_frame_factory):
    frames = [pose_frame_factory(i, i * 0.5) for i in range(5)]
    metrics = compute_gait_metrics(frames, fps=30.0)
    assert metrics.duration_s == pytest.approx(2.0)


def test_single_frame_has_zero_duration(pose_frame_factory):
    frames = [pose_frame_factory(0, 0.0)]
    metrics = compute_gait_metrics(frames, fps=30.0)
    assert metrics.duration_s == 0.0
    assert metrics.step_count == 0


def test_rejects_non_positive_fps(pose_frame_factory):
    frames = [pose_frame_factory(0, 0.0)]
    with pytest.raises(ValueError):
        compute_gait_metrics(frames, fps=0)
    with pytest.raises(ValueError):
        compute_gait_metrics(frames, fps=-5)


def test_low_confidence_keypoints_are_ignored(pose_frame_factory, walking_sequence_factory):
    frames = walking_sequence_factory(duration_s=5.0, fps=30.0, step_frequency_hz=1.0)
    low_confidence_frames = [
        pose_frame_factory(
            f.frame_index,
            f.timestamp,
            left_ankle_y=f.get(KeypointName.LEFT_ANKLE).y,
            right_ankle_y=f.get(KeypointName.RIGHT_ANKLE).y,
            confidence=0.05,
        )
        for f in frames
    ]
    metrics = compute_gait_metrics(low_confidence_frames, fps=30.0)
    assert metrics.step_count == 0
