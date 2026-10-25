"""Exercise the drawing-to-lookup flow and save native Qt layout previews."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from sanlex.db import Dictionary
from sanlex.ui import MainWindow
from sample_data import populate

app = QApplication([])
# Qt's offscreen plugin on Windows does not discover system fonts itself.
if sys.platform == 'win32' and not QFontDatabase.families():
    for name in ('segoeui.ttf', 'msyh.ttc'):
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
output = ROOT / 'test-output'
output.mkdir(exist_ok=True)


def wait_until(condition, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        QTest.qWait(10)
    raise AssertionError('Timed out waiting for handwriting UI')


with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network')):
    path = Path(directory) / 'dictionary.sqlite3'
    db = Dictionary(path)
    db.initialize()
    populate(db)
    db.close()
    window = MainWindow(path)
    window.show()
    wait_until(lambda: not window.workers)
    window.grab().save(str(output / 'handwriting-entrypoint.png'))
    start = time.perf_counter()
    window.open_handwriting()
    pad = window.handwriting_window
    wait_until(lambda: pad.counts is not None)
    loaded = time.perf_counter() - start
    strokes = [[(.25, .35), (.8, .35)], [(.5, .12), (.5, .88)],
               [(.49, .36), (.36, .59), (.15, .84)], [(.51, .36), (.7, .65), (.9, .84)]]
    rect = pad.canvas.drawing_rect()
    for stroke in strokes:
        points = [QPoint(round(rect.x() + x * rect.width()), round(rect.y() + y * rect.height())) for x, y in stroke]
        QTest.mousePress(pad.canvas, Qt.MouseButton.LeftButton, pos=points[0])
        for point in points[1:-1]:
            QTest.mouseMove(pad.canvas, point)
        QTest.mouseRelease(pad.canvas, Qt.MouseButton.LeftButton, pos=points[-1])
    start = time.perf_counter()
    wait_until(lambda: pad.candidates.count() > 0)
    recognition = time.perf_counter() - start
    matches = [pad.candidates.item(i).text() for i in range(pad.candidates.count())]
    assert '木' in matches[:5], matches
    pad.candidates.setCurrentRow(matches.index('木'))
    pad.grab().save(str(output / 'handwriting.png'))
    pad.resize(660, 530)
    app.processEvents()
    pad.grab().save(str(output / 'handwriting-minimum.png'))
    pad.lookup()
    assert window.analysis_window.root_char == '木'
    wait_until(lambda: not window.workers)
    report = {'offline': True, 'template_load_seconds': round(loaded, 3),
              'recognition_seconds_including_debounce': round(recognition, 3),
              'coverage': pad.counts, 'candidates': matches, 'lookup': window.analysis_window.root_char,
              'minimum_size': [pad.width(), pad.height()]}
    window.close()
    assert not pad.worker.isRunning()
    app.processEvents()
    print(json.dumps(report, ensure_ascii=False, indent=2))
