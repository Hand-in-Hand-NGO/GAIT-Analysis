"""Tests the workers' thread-start path -- via .start(), not .run().

This is the exact gap the crash-debugging history (see repo commit
history / handoff notes) identified as a real testing blind spot: calling
.run() directly on the main thread never exercises what happens when the
detector is constructed on a genuine background OS thread. Every worker
test here drives the worker with qtbot.waitSignal(...) after worker.start(),
matching exactly how gaitapp/ui/main_window.py uses these workers.
"""
import cv2
import numpy as np
import pytest

from gaitapp.analysis.landmarks import empty_pose_frame
from gaitapp.analysis.video_processor import (
    GaitAnalysisResult,
    PoseAnalysisWorker,
    VideoOpenError,
    ViewClassificationWorker,
    get_video_fps,
    iter_video_frames,
    run_pose_detection,
)
from tests._helpers import FakeErrorDetector, FakePoseDetector, make_walking_sequence

TINY_VIDEO_FPS = 10.0
TINY_VIDEO_FRAME_COUNT = 8


@pytest.fixture
def tiny_video(tmp_path):
    path = tmp_path / "clip.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, TINY_VIDEO_FPS, (64, 48))
    for i in range(TINY_VIDEO_FRAME_COUNT):
        frame = np.full((48, 64, 3), i * 10, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_iter_video_frames_reads_all_frames(tiny_video):
    frames = list(iter_video_frames(tiny_video))
    assert len(frames) == TINY_VIDEO_FRAME_COUNT
    assert [f[0] for f in frames] == list(range(TINY_VIDEO_FRAME_COUNT))


def test_iter_video_frames_missing_file_raises(tmp_path):
    with pytest.raises(VideoOpenError):
        list(iter_video_frames(tmp_path / "does_not_exist.mp4"))


def test_get_video_fps_missing_file_raises(tmp_path):
    with pytest.raises(VideoOpenError):
        get_video_fps(tmp_path / "does_not_exist.mp4")


def test_get_video_fps(tiny_video):
    assert get_video_fps(tiny_video) == pytest.approx(TINY_VIDEO_FPS, abs=1.0)


def test_run_pose_detection_calls_detector_once_per_frame(tiny_video):
    calls = []

    class CountingDetector:
        def detect(self, frame, frame_index, timestamp):
            calls.append(frame_index)
            return empty_pose_frame(frame_index, timestamp)

    frames = run_pose_detection(tiny_video, CountingDetector())
    assert calls == list(range(TINY_VIDEO_FRAME_COUNT))
    assert len(frames) == TINY_VIDEO_FRAME_COUNT


def test_pose_analysis_worker_start_emits_finished(qtbot, tiny_video):
    walking_frames = make_walking_sequence(
        duration_s=TINY_VIDEO_FRAME_COUNT / TINY_VIDEO_FPS, fps=TINY_VIDEO_FPS, step_frequency_hz=2.0
    )
    worker = PoseAnalysisWorker(
        side_video_path=tiny_video,
        detector_factory=lambda: FakePoseDetector(walking_frames),
    )

    with qtbot.waitSignal(worker.finished, timeout=5000, raising=True) as blocker:
        worker.start()

    result = blocker.args[0]
    assert isinstance(result, GaitAnalysisResult)
    assert result.side_metrics.step_count >= 0
    assert worker.wait(2000)


def test_pose_analysis_worker_emits_error_on_detector_failure(qtbot, tiny_video):
    worker = PoseAnalysisWorker(side_video_path=tiny_video, detector_factory=FakeErrorDetector)

    with qtbot.waitSignal(worker.error, timeout=5000, raising=True) as blocker:
        worker.start()

    assert "boom" in blocker.args[0]
    assert worker.wait(2000)


def test_pose_analysis_worker_missing_video_emits_error(qtbot, tmp_path):
    worker = PoseAnalysisWorker(
        side_video_path=tmp_path / "missing.mp4",
        detector_factory=lambda: FakePoseDetector([]),
    )

    with qtbot.waitSignal(worker.error, timeout=5000, raising=True) as blocker:
        worker.start()

    assert "Could not open video file" in blocker.args[0]


def test_view_classification_worker_start_emits_classified(qtbot, tiny_video):
    walking_frames = make_walking_sequence(
        duration_s=TINY_VIDEO_FRAME_COUNT / TINY_VIDEO_FPS, fps=TINY_VIDEO_FPS, step_frequency_hz=1.0
    )
    worker = ViewClassificationWorker(tiny_video, lambda: FakePoseDetector(walking_frames))

    with qtbot.waitSignal(worker.classified, timeout=5000, raising=True) as blocker:
        worker.start()

    result = blocker.args[0]
    assert result.frames_considered == TINY_VIDEO_FRAME_COUNT
    assert worker.wait(2000)


def test_view_classification_worker_emits_error_on_detector_failure(qtbot, tiny_video):
    worker = ViewClassificationWorker(tiny_video, FakeErrorDetector)

    with qtbot.waitSignal(worker.error, timeout=5000, raising=True) as blocker:
        worker.start()

    assert "boom" in blocker.args[0]
