from gaitapp.ui.main_window import MainWindow


def test_main_window_constructs(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Gait Analysis"
    assert window._analyze_button.isEnabled()


def test_analyze_without_side_video_shows_warning(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    warned = {}

    def fake_warning(parent, title, text):
        warned["title"] = title

    monkeypatch.setattr("gaitapp.ui.main_window.QMessageBox.warning", fake_warning)

    window._on_analyze_clicked()

    assert warned.get("title") == "Missing video"
    assert window._analyze_button.isEnabled()


def test_analyze_with_nonexistent_side_video_shows_warning(qtbot, monkeypatch, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window._side_video_edit.setText(str(tmp_path / "does_not_exist.mp4"))

    warned = {}
    monkeypatch.setattr(
        "gaitapp.ui.main_window.QMessageBox.warning",
        lambda parent, title, text: warned.setdefault("title", title),
    )

    window._on_analyze_clicked()

    assert warned.get("title") == "File not found"
