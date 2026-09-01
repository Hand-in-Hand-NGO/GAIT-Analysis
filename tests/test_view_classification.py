import pytest

from gaitapp.analysis.landmarks import empty_pose_frame
from gaitapp.analysis.view_classification import ViewType, classify_view


def test_wide_shoulders_classified_as_front(pose_frame_factory):
    frames = [
        pose_frame_factory(i, i / 30.0, shoulder_half_width=60.0, hip_y=200.0, shoulder_y=100.0)
        for i in range(20)
    ]
    result = classify_view(frames)
    assert result.view_type == ViewType.FRONT
    assert result.confidence == pytest.approx(1.0)
    assert result.frames_classified == 20


def test_narrow_shoulders_classified_as_side(pose_frame_factory):
    frames = [
        pose_frame_factory(i, i / 30.0, shoulder_half_width=20.0, hip_y=200.0, shoulder_y=100.0)
        for i in range(20)
    ]
    result = classify_view(frames)
    assert result.view_type == ViewType.SIDE
    assert result.confidence == pytest.approx(1.0)


def test_no_visible_landmarks_is_unknown():
    frames = [empty_pose_frame(i, i / 30.0) for i in range(10)]
    result = classify_view(frames)
    assert result.view_type == ViewType.UNKNOWN
    assert result.confidence == 0.0
    assert result.frames_classified == 0


def test_mixed_ambiguous_frames_are_excluded_from_vote(pose_frame_factory):
    # ratio 0.85 sits strictly between SIDE_VIEW_MAX_RATIO (0.7) and
    # FRONT_VIEW_MIN_RATIO (1.0), so these frames should not sway the vote.
    ambiguous = [
        pose_frame_factory(i, i / 30.0, shoulder_half_width=42.5, hip_y=200.0, shoulder_y=100.0)
        for i in range(5)
    ]
    clear_side = [
        pose_frame_factory(i, i / 30.0, shoulder_half_width=20.0, hip_y=200.0, shoulder_y=100.0)
        for i in range(5, 10)
    ]
    result = classify_view(ambiguous + clear_side)
    assert result.view_type == ViewType.SIDE
    assert result.frames_classified == 5
