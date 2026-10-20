import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# never touch the real user settings from tests
os.environ["LANGREC_SETTINGS"] = os.path.join(tempfile.mkdtemp(prefix="langrec-test-"), "settings.ini")
