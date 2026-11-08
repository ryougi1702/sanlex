"""Headless adapter for the unchanged, bundled KanjiCanvas JavaScript engine.

Upstream: https://github.com/asdfjkl/kanjicanvas
Copyright (c) 2019 Dominik Klein; see assets/kanjicanvas/LICENSE.TXT.
"""
import json
import math
from pathlib import Path
import zlib

from PySide6.QtQml import QJSEngine, QJSValue

from .db import resource_path
from .handwriting import normalize, resample
from .text import is_han


class KanjiCanvasRecognizer:
    def __init__(self, path=None):
        path = Path(path) if path else resource_path('assets/kanjicanvas')
        code = (path / 'kanji-canvas.js').read_text(encoding='utf-8')
        patterns = zlib.decompress((path / 'patterns.json.zlib').read_bytes()).decode('utf-8')
        self.chars = {p[0] for p in json.loads(patterns) if is_han(p[0])}
        self.engine = QJSEngine()
        self.evaluate('var window=this; var document={addEventListener:function(){}}; '
                      'var console={log:function(){}};')
        self.evaluate(code)
        value = self.engine.evaluate('JSON.parse').call([QJSValue(patterns)])
        if value.isError():
            raise ValueError('Cannot read KanjiCanvas reference patterns: ' + value.toString())
        self.engine.globalObject().setProperty('sanlexPatterns', value)
        self.evaluate('''
            KanjiCanvas.refPatterns = sanlexPatterns;
            function sanlexRecognize(strokes) {
                KanjiCanvas.recordedPattern_sanlex = strokes;
                var normalized = KanjiCanvas.momentNormalize('sanlex');
                var features = KanjiCanvas.extractFeatures(normalized, 20);
                var coarse = KanjiCanvas.coarseClassification(features);
                return KanjiCanvas.fineClassification(features, coarse);
            }
        ''')

    def evaluate(self, code):
        value = self.engine.evaluate(code)
        if value.isError():
            raise ValueError('KanjiCanvas: ' + value.toString())
        return value

    def recognize(self, strokes, mode='ja', limit=24, cancelled=lambda: False):
        if mode != 'ja':
            raise ValueError('KanjiCanvas supports Japanese mode')
        if cancelled() or limit <= 0:
            return []
        strokes = normalize(strokes)
        if not strokes:
            return []
        # Densify sparse pen segments before upstream moment normalization,
        # whose moments are calculated over input points rather than ink length.
        dense = [resample(s, max(2, math.ceil(sum(math.dist(a, b) for a, b in zip(s, s[1:])) * 70)))
                 for s in strokes]
        points = [[[x * 255, y * 255] for x, y in stroke] for stroke in dense]
        if cancelled():
            return []
        result = self.engine.evaluate('sanlexRecognize(' + json.dumps(points, allow_nan=False) + ')')
        if cancelled() or self.engine.isInterrupted():
            return []
        if result.isError():
            raise ValueError('KanjiCanvas: ' + result.toString())
        chars = list(dict.fromkeys(c for c in result.toString().split() if c in self.chars))
        return [{'char': c, 'mode': 'ja', 'engine': 'KanjiCanvas', 'rank': i + 1}
                for i, c in enumerate(chars[:limit])]
