"""Build a stand-alone program that runs without a terminal or Python installed.

    python build_app.py

Output in dist/:
  * macOS:   dist/LangRec-macOS-portable/LangRec.app (+ portable.txt) and a zip
  * Windows: dist/LangRec-Windows-portable/LangRec.exe (+ _internal/, portable.txt) and a zip
  * Linux:   dist/LangRec-Linux-portable/LangRec (+ _internal/, portable.txt) and a zip

PyInstaller only builds for the system it runs on, so the Windows build must be made on
Windows and the Linux build on Linux — or automatically by GitHub Actions
(.github/workflows/build.yml).

portable.txt switches on portable mode: settings and sessions are kept next to the
program in LangRec_data/ (see langrec/paths.py).
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from langrec import __version__

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# Qt modules the program does not use: leaving them out makes the build much smaller.
EXCLUDE = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation", "PySide6.QtPositioning",
    "matplotlib", "pandas", "IPython", "pytest",
]

README_PORTABLE = """LangRec {ver} — portable ({os}) / портабельна версія

EN  Run: {how_en}. Nothing to install, not even Python.
    Settings and recorded sessions are kept next to the program, in LangRec_data/.
    Delete portable.txt to use the system locations instead
    (sessions then go to Documents/LangRec_sessions).

UA  Запуск: {how_uk}. Нічого встановлювати не потрібно, навіть Python.
    Налаштування й записані сеанси зберігаються поруч, у папці LangRec_data/.
    Якщо видалити portable.txt, програма використовуватиме стандартні місця системи
    (сеанси — у Документи/LangRec_sessions).
"""


def make_icon_file(system: str) -> Path:
    """PNG icon from langrec/gui/icon.py; PyInstaller (with Pillow) converts it to .icns / .ico."""
    from PySide6.QtGui import QGuiApplication

    from langrec.gui.icon import save_icon_png
    _app = QGuiApplication.instance() or QGuiApplication(["build"])
    png = ROOT / "build" / "icon.png"
    png.parent.mkdir(exist_ok=True)
    save_icon_png(str(png))
    return png


def zip_folder(folder: Path, archive: Path) -> Path:
    """Zip archive. On macOS via ditto, which keeps the symlinks inside the .app
    (shutil.make_archive follows them and the archive nearly doubles in size)."""
    archive.unlink(missing_ok=True)
    if platform.system() == "Darwin":
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(folder), str(archive)], check=True)
        return archive
    return Path(shutil.make_archive(str(archive.with_suffix("")), "zip", folder.parent, folder.name))


def main():
    system = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}[platform.system()]
    name = f"LangRec-{system}-portable"
    out = DIST / name
    shutil.rmtree(out, ignore_errors=True)

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", "LangRec", "--distpath", str(DIST / "_pyinstaller"),
           "--workpath", str(ROOT / "build" / "_work"), "--specpath", str(ROOT / "build")]
    cmd += ["--icon", str(make_icon_file(system))]
    if system == "macOS":
        cmd += ["--osx-bundle-identifier", "ua.langrec.app"]
    for m in EXCLUDE:
        cmd += ["--exclude-module", m]
    cmd.append(str(ROOT / "run_langrec.py"))
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)

    built = DIST / "_pyinstaller"
    if system == "macOS":
        out.mkdir(parents=True)
        shutil.copytree(built / "LangRec.app", out / "LangRec.app", symlinks=True)
        how_en = "double-click LangRec.app (first time: right-click → Open)"
        how_uk = "подвійний клік на LangRec.app (уперше: правий клік → Відкрити)"
    else:
        # LangRec.exe (or LangRec) + _internal/ directly in the portable folder,
        # so that portable.txt sits next to the executable
        shutil.copytree(built / "LangRec", out, symlinks=True)
        how_en = how_uk = "LangRec.exe" if system == "Windows" else "./LangRec"
    (out / "portable.txt").write_text("LangRec portable mode. Keep this file.\n", encoding="utf-8")
    (out / "README.txt").write_text(
        README_PORTABLE.format(ver=__version__, os=system, how_en=how_en, how_uk=how_uk),
        encoding="utf-8")

    archive = zip_folder(out, DIST / f"{name}-{__version__}.zip")
    print(f"\nDone:\n  {out}\n  {archive}")


if __name__ == "__main__":
    main()
