import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pytest

from tests._helpers import make_pose_frame, make_walking_sequence


@pytest.fixture
def pose_frame_factory():
    return make_pose_frame


@pytest.fixture
def walking_sequence_factory():
    return make_walking_sequence
