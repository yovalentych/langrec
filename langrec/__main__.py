"""Entry point: `python -m langrec`, or the built LangRec.exe / LangRec.app.

Optional arguments (mostly for testing and screenshots):
  --replay FOLDER      open a folder with old recordings and load every file
  --simulator          start the training simulator
  --speed N            playback speed (1, 2, 5, 10, 30, 60)
  --autostart          start playback at once
  --theme light|dark   interface theme
  --lang uk|en         interface language
  --screenshot FILE    after --after seconds save a screenshot to FILE and quit
  --after S            (default 5)
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="langrec")
    ap.add_argument("--replay")
    ap.add_argument("--speed", type=int)
    ap.add_argument("--autostart", action="store_true")
    ap.add_argument("--screenshot")
    ap.add_argument("--after", type=float, default=5.0)
    ap.add_argument("--theme", choices=["light", "dark"])
    ap.add_argument("--lang", choices=["uk", "en"])
    ap.add_argument("--simulator", action="store_true")
    # macOS may pass its own -psn_... argument to an .app; unknown arguments are ignored
    args, _ = ap.parse_known_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("LangRec")
    app.setOrganizationName("LangRec")
    app.setStyle("Fusion")      # the same look on Windows, macOS and Linux
    win = MainWindow()
    if args.lang:
        win.set_ui_language(args.lang)
    if args.theme:
        win._set_theme(args.theme)
    win.show()

    if args.speed:
        win.set_speed(args.speed)
    if args.replay:
        win.open_folder(args.replay)
        win._load_selected()
        if args.autostart:
            win._start()
    if args.simulator:
        win._start_simulator_default()
    if args.screenshot:
        def shot():
            win.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(int(args.after * 1000), shot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
