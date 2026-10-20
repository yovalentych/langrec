"""Where settings and sessions are stored: normal or portable mode.

Portable mode is on when a file `portable.txt` lies next to the program (the portable
builds ship with it). Then:
  * settings go to  <program folder>/LangRec_data/settings.ini,
  * sessions go to  <program folder>/LangRec_data/sessions/ by default,
so the program can live on a USB stick and leaves nothing behind on the computer.

In normal mode the system locations are used (registry / ~/Library/Preferences /
~/.config), and sessions go to ~/Documents/LangRec_sessions.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings


def app_dir() -> Path:
    """Folder that contains the program (exe / .app / sources)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        # macOS: LangRec.app/Contents/MacOS/LangRec -> the folder that contains LangRec.app
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return (app_dir() / "portable.txt").exists()


def data_dir() -> Path:
    return app_dir() / "LangRec_data"


def make_settings() -> QSettings:
    override = os.environ.get("LANGREC_SETTINGS")     # used by the tests
    if override:
        return QSettings(override, QSettings.IniFormat)
    if is_portable():
        data_dir().mkdir(exist_ok=True)
        return QSettings(str(data_dir() / "settings.ini"), QSettings.IniFormat)
    return QSettings("LangRec", "LangRec")


def default_sessions_dir() -> Path:
    if is_portable():
        return data_dir() / "sessions"
    return Path.home() / "Documents" / "LangRec_sessions"
