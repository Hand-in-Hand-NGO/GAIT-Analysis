import os
import tempfile
from pathlib import Path

import gaitapp.main as main_module
import gaitapp.smoke_test as smoke_test_module


def test_kmp_duplicate_lib_ok_is_set():
    # Set at import time, before any torch/numpy import -- see the module
    # docstring for why this matters (silent OpenMP-init crash otherwise).
    assert os.environ.get("KMP_DUPLICATE_LIB_OK") == "TRUE"


def test_crash_log_path_is_under_system_temp_dir():
    assert main_module.CRASH_LOG_PATH.parent == Path(tempfile.gettempdir())
    assert main_module.CRASH_LOG_PATH.name == "gaitapp_crash.log"


def test_faulthandler_is_enabled():
    import faulthandler

    assert faulthandler.is_enabled()


def test_main_routes_smoke_test_flag_without_launching_gui(monkeypatch):
    called = {}

    def fake_run_smoke_test():
        called["ran"] = True
        return 0

    monkeypatch.setattr(smoke_test_module, "run_smoke_test", fake_run_smoke_test)

    exit_code = main_module.main(["--smoke-test"])

    assert exit_code == 0
    assert called.get("ran") is True


def test_main_propagates_smoke_test_failure_code(monkeypatch):
    monkeypatch.setattr(smoke_test_module, "run_smoke_test", lambda: 1)

    assert main_module.main(["--smoke-test"]) == 1
