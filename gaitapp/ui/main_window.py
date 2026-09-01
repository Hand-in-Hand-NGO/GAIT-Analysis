"""Main application window: pick a front+side video pair, run analysis, view results."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gaitapp.analysis.video_processor import GaitAnalysisResult, PoseAnalysisWorker
from gaitapp.analysis.view_classification import ViewType
from gaitapp.analysis.yolo_pose_detector import YoloPoseDetector

VIDEO_FILE_FILTER = "Video files (*.mp4 *.mov *.avi *.mkv);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gait Analysis")
        self.resize(760, 560)

        self._worker: PoseAnalysisWorker | None = None

        self._side_video_edit = QLineEdit()
        self._front_video_edit = QLineEdit()
        self._analyze_button = QPushButton("Run Gait Analysis")
        self._analyze_button.clicked.connect(self._on_analyze_clicked)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._status_label = QLabel("Select a side-view video (required) and a front-view video (optional).")
        self._results_view = QTextEdit()
        self._results_view.setReadOnly(True)

        self.setCentralWidget(self._build_central_widget())

    def _build_central_widget(self) -> QWidget:
        central = QWidget()
        layout = QVBoxLayout(central)

        grid = QGridLayout()
        grid.addWidget(QLabel("Side-view video:"), 0, 0)
        grid.addWidget(self._side_video_edit, 0, 1)
        grid.addWidget(self._make_browse_button(self._side_video_edit), 0, 2)

        grid.addWidget(QLabel("Front-view video (optional):"), 1, 0)
        grid.addWidget(self._front_video_edit, 1, 1)
        grid.addWidget(self._make_browse_button(self._front_video_edit), 1, 2)
        layout.addLayout(grid)

        button_row = QHBoxLayout()
        button_row.addWidget(self._analyze_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        layout.addWidget(self._progress_bar)
        layout.addWidget(self._status_label)
        layout.addWidget(self._results_view, stretch=1)
        return central

    def _make_browse_button(self, target_edit: QLineEdit) -> QPushButton:
        button = QPushButton("Browse...")

        def on_click() -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Select video", "", VIDEO_FILE_FILTER)
            if path:
                target_edit.setText(path)

        button.clicked.connect(on_click)
        return button

    def _on_analyze_clicked(self) -> None:
        side_path = self._side_video_edit.text().strip()
        if not side_path:
            QMessageBox.warning(self, "Missing video", "Please select a side-view video first.")
            return
        if not Path(side_path).exists():
            QMessageBox.warning(self, "File not found", f"Side-view video not found:\n{side_path}")
            return

        front_path = self._front_video_edit.text().strip() or None
        if front_path and not Path(front_path).exists():
            QMessageBox.warning(self, "File not found", f"Front-view video not found:\n{front_path}")
            return

        self._analyze_button.setEnabled(False)
        self._progress_bar.setValue(0)
        self._results_view.clear()
        self._status_label.setText("Running analysis... this can take a while on longer clips.")

        # Deliberately constructed on the worker thread inside PoseAnalysisWorker.run(),
        # not here -- see gaitapp/analysis/video_processor.py for why.
        detector_factory = YoloPoseDetector

        self._worker = PoseAnalysisWorker(
            side_video_path=side_path,
            detector_factory=detector_factory,
            front_video_path=front_path,
        )
        self._worker.progress.connect(self._progress_bar.setValue)
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_finished(self, result: GaitAnalysisResult) -> None:
        self._analyze_button.setEnabled(True)
        self._status_label.setText("Analysis complete.")
        self._results_view.setPlainText(_format_result(result))

    def _on_analysis_error(self, traceback_text: str) -> None:
        self._analyze_button.setEnabled(True)
        self._status_label.setText("Analysis failed.")
        self._results_view.setPlainText(traceback_text)
        QMessageBox.critical(
            self,
            "Analysis failed",
            "Gait analysis encountered an error. See details in the log panel below.",
        )


def _format_result(result: GaitAnalysisResult) -> str:
    m = result.side_metrics
    lines = [
        f"Total steps: {m.step_count} (left: {m.left_step_count}, right: {m.right_step_count})",
        f"Clip duration: {m.duration_s:.1f} s",
    ]
    if m.cadence_steps_per_min is not None:
        lines.append(f"Cadence: {m.cadence_steps_per_min:.1f} steps/min")
    if m.mean_step_time_s is not None:
        lines.append(f"Mean step time: {m.mean_step_time_s:.2f} s (std {m.step_time_std_s:.2f} s)")
    if m.symmetry_index_pct is not None:
        lines.append(f"Left/right symmetry index: {m.symmetry_index_pct:.1f}%")

    if result.side_view_result.view_type != ViewType.SIDE:
        lines.append(
            f"\nWarning: the 'side-view' video looks like a {result.side_view_result.view_type.value} view "
            f"(confidence {result.side_view_result.confidence:.0%}). Check the video assignment."
        )
    if result.front_view_result is not None and result.front_view_result.view_type != ViewType.FRONT:
        lines.append(
            f"\nWarning: the 'front-view' video looks like a {result.front_view_result.view_type.value} view "
            f"(confidence {result.front_view_result.confidence:.0%}). Check the video assignment."
        )
    return "\n".join(lines)
