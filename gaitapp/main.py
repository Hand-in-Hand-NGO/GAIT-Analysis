"""Application entry point.

Two things happen here, before anything else is imported, specifically to
guard against a class of crash that is otherwise silent (no Python
exception, no dialog, the window just disappears):

1. KMP_DUPLICATE_LIB_OK=TRUE -- torch and numpy can each bundle their own
   Intel OpenMP runtime (libiomp5md.dll on Windows). If a frozen PyInstaller
   build ends up loading two copies of it in one process, the second init
   aborts the process outright. This must be set before torch or numpy are
   imported anywhere, which is why it happens at the very top of this file
   rather than nearer where those libraries are actually used.
2. faulthandler, enabled to a persistent log file rather than stderr, since
   a frozen --windowed build has no visible console to catch stderr on.
   faulthandler can dump a partial Python stack for genuine native crashes
   (segfault/abort), which a plain try/except never sees.
"""
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import faulthandler
import sys
import tempfile
from pathlib import Path

CRASH_LOG_PATH = Path(tempfile.gettempdir()) / "gaitapp_crash.log"


def _enable_crash_logging() -> None:
    try:
        log_file = open(CRASH_LOG_PATH, "a", buffering=1, encoding="utf-8")
    except OSError:
        # Falling back to stderr keeps faulthandler useful in dev/CI even
        # if the temp dir isn't writable; production installs always have
        # a writable %TEMP%.
        faulthandler.enable()
        return
    faulthandler.enable(file=log_file)


_enable_crash_logging()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if "--smoke-test" in argv:
        from gaitapp.smoke_test import run_smoke_test

        return run_smoke_test()

    from PySide6.QtWidgets import QApplication

    from gaitapp.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
