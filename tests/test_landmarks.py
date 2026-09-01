import pytest

from gaitapp.analysis.landmarks import Keypoint, KeypointName, NUM_KEYPOINTS, empty_pose_frame


def test_keypoint_visibility_threshold():
    kp = Keypoint(x=1.0, y=2.0, confidence=0.5)
    assert kp.is_visible(0.3)
    assert not kp.is_visible(0.6)


def test_empty_pose_frame_has_zero_confidence_everywhere():
    pf = empty_pose_frame(frame_index=0, timestamp=0.0)
    assert len(pf.keypoints) == NUM_KEYPOINTS
    assert all(kp.confidence == 0.0 for kp in pf.keypoints)
    assert not pf.is_visible(KeypointName.LEFT_ANKLE)


def test_hip_and_shoulder_midpoints_and_scale(pose_frame_factory):
    pf = pose_frame_factory(
        0, 0.0, torso_center_x=100.0, hip_y=300.0, shoulder_y=100.0, shoulder_half_width=10.0
    )
    assert pf.hip_midpoint == pytest.approx((100.0, 300.0))
    assert pf.shoulder_midpoint == pytest.approx((100.0, 100.0))
    assert pf.torso_height == pytest.approx(200.0)
    assert pf.shoulder_width == pytest.approx(20.0)


def test_get_returns_keypoint_by_name(pose_frame_factory):
    pf = pose_frame_factory(0, 0.0, left_ankle_y=444.0)
    assert pf.get(KeypointName.LEFT_ANKLE).y == pytest.approx(444.0)
