import math
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sanlex.handwriting import HandwritingRecognizer, normalize, resample
from sanlex.handwriting_window import HandwritingCanvas, RecognitionWorker
from sanlex.strokes import StrokeStore


class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recognizer = HandwritingRecognizer()
        cls.store = StrokeStore()

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def handwriting(self, char, mode):
        record = self.store.record(char, mode)
        self.assertIsNotNone(record, (char, mode))
        # Simulate a smaller, offset, unevenly sampled drawing with different
        # proportions and a little hand tremor, rather than replay exact data.
        return [[(30 + x * .28 + 2 * math.sin(i * 2.1),
                  40 + (900 - y) * .32 + 2 * math.cos(i * 1.7))
                 for i, (x, y) in enumerate(resample(s, 11))]
                for s in record['graphics']['medians']]

    def test_script_modes_recognize_perturbed_shapes(self):
        for mode, chars in [('hans', '汉语学发龙'), ('hant', '學漢龍發'), ('ja', '働辺駅国漢')]:
            for char in chars:
                with self.subTest(mode=mode, char=char):
                    matches = self.recognizer.recognize(self.handwriting(char, mode), mode)
                    self.assertIn(char, [row['char'] for row in matches[:5]])
                    self.assertTrue(all(row['mode'] == mode for row in matches))

    def test_combined_results_deduplicate_and_tolerate_unusual_order(self):
        strokes = self.handwriting('木', 'ja')
        matches = self.recognizer.recognize([list(reversed(s)) for s in reversed(strokes)])
        self.assertIn('木', [row['char'] for row in matches[:5]])
        self.assertEqual(len(matches), len({row['char'] for row in matches}))
        for mode, char in [('hans', '汉'), ('hant', '學'), ('ja', '駅')]:
            matches = self.recognizer.recognize(self.handwriting(char, mode))
            self.assertIn(char, [row['char'] for row in matches[:5]])

    def test_empty_degenerate_cancellation_and_missing_pack(self):
        for strokes in ([], [[]], [[(1, 1)]], [[(1, 1), (1, 1)]]):
            self.assertEqual(self.recognizer.recognize(strokes), [])
        self.assertEqual(self.recognizer.recognize([[(0, 0), (1, 1)]], cancelled=lambda: True), [])
        with self.assertRaises(ValueError):
            self.recognizer.recognize([], 'unknown')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                HandwritingRecognizer(Path(directory) / 'absent.sqlite3')

    def test_independently_drawn_simple_characters(self):
        cases = {
            '木': [[(100, 120), (300, 120)], [(200, 50), (200, 330)],
                  [(195, 130), (160, 210), (70, 300)], [(205, 130), (250, 225), (340, 300)]],
            '人': [[(190, 65), (170, 190), (75, 320)], [(185, 110), (240, 240), (320, 320)]],
            '口': [[(80, 80), (80, 300)], [(80, 80), (300, 80), (300, 300)], [(80, 300), (300, 300)]],
        }
        for char, strokes in cases.items():
            with self.subTest(char=char):
                self.assertIn(char, [row['char'] for row in self.recognizer.recognize(strokes)[:5]])

    def test_normalization_preserves_aspect_and_resampling_handles_dots(self):
        self.assertEqual(resample([(3, 4)], 8), [(3, 4)] * 8)
        self.assertEqual(normalize([[(0, 0), (10, 0)]]), (((0, .5), (1, .5)),))
        self.assertEqual(normalize([[(50, 30), (70, 30)]]), normalize([[(0, 0), (10, 0)]]))


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mouse_drawing_undo_clear_and_resize(self):
        canvas = HandwritingCanvas()
        canvas.resize(330, 330)
        canvas.show()
        self.app.processEvents()
        changes = []
        canvas.changed.connect(lambda: changes.append(True))
        for y in (90, 210):
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, y))
            QTest.mouseMove(canvas, QPoint(150, y + 5))
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(260, y))
        self.assertEqual(len(canvas.strokes), 2)
        self.assertIsNone(canvas.current)
        self.assertGreaterEqual(len(changes), 4)
        before = [list(s) for s in canvas.strokes]
        canvas.resize(450, 380)
        self.assertEqual(canvas.strokes, before)
        self.assertTrue(all(0 <= v <= 1 for s in canvas.strokes for p in s for v in p))
        canvas.undo()
        self.assertEqual(len(canvas.strokes), 1)
        canvas.clear()
        self.assertEqual(canvas.strokes, [])
        canvas.close()

    def test_worker_shutdown_cancels_an_active_recognition(self):
        started = threading.Event()

        class SlowRecognizer:
            counts = {'all': 1, 'ja': 1, 'hans': 0, 'hant': 0}

            def recognize(self, strokes, mode, cancelled):
                started.set()
                while not cancelled():
                    threading.Event().wait(.001)
                return []

        with patch('sanlex.handwriting_window.HandwritingRecognizer', return_value=SlowRecognizer()):
            worker = RecognitionWorker()
            worker.start()
            try:
                worker.submit(1, [[(0, 0), (1, 1)]], 'all')
                self.assertTrue(started.wait(3))
            finally:
                worker.shutdown()
            self.assertFalse(worker.isRunning())
