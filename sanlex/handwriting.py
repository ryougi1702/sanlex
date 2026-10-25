"""Offline, template-based handwriting lookup using the bundled AnimCJK medians.

Shape matching is intentionally approximate, not a trained handwriting model.
Coordinates are screen coordinates (positive y down). No network is involved.
"""
from dataclasses import dataclass
import heapq
import json
import math
from pathlib import Path
import sqlite3
import zlib

from .db import resource_path


def resample(points, count):
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if not total:
        return [points[0]] * count
    result, index, passed = [], 0, 0.0
    for i in range(count):
        distance = total * i / (count - 1)
        while index < len(lengths) - 1 and passed + lengths[index] < distance:
            passed += lengths[index]
            index += 1
        fraction = (distance - passed) / lengths[index] if lengths[index] else 0
        a, b = points[index:index + 2]
        result.append((a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction))
    return result


def normalize(strokes):
    strokes = [stroke for stroke in strokes if stroke]
    points = [p for stroke in strokes for p in stroke]
    if not points:
        return ()
    left, top = min(p[0] for p in points), min(p[1] for p in points)
    width = max(p[0] for p in points) - left
    height = max(p[1] for p in points) - top
    scale = max(width, height)
    if scale < 1e-6:
        return ()
    return tuple(tuple(((x - left - width / 2) / scale + .5,
                        (y - top - height / 2) / scale + .5) for x, y in stroke)
                 for stroke in strokes)


def features(strokes):
    # Sample ink by distance, without drawing imaginary pen-up connecting lines.
    dense = [p for stroke in strokes for p in resample(
        stroke, max(2, math.ceil(sum(math.dist(a, b) for a, b in zip(stroke, stroke[1:])) * 70)))]
    cloud = tuple(dense[round(i * (len(dense) - 1) / 47)] for i in range(48))
    grid = [0.0] * 64
    for x, y in dense:
        gx, gy = max(0, min(6.9999, x * 7)), max(0, min(6.9999, y * 7))
        ix, iy = int(gx), int(gy)
        fx, fy = gx - ix, gy - iy
        for dx, wx in ((0, 1 - fx), (1, fx)):
            for dy, wy in ((0, 1 - fy), (1, fy)):
                grid[(iy + dy) * 8 + ix + dx] += wx * wy
    # Blur ink before coarse matching so straight handwriting can still find a
    # tapered or slanted font template (e.g. a square handwritten 口).
    for _ in range(2):
        horizontal = [2 * grid[y * 8 + x] + (grid[y * 8 + x - 1] if x else 0) +
                      (grid[y * 8 + x + 1] if x < 7 else 0) for y in range(8) for x in range(8)]
        grid = [2 * horizontal[y * 8 + x] + (horizontal[(y - 1) * 8 + x] if y else 0) +
                (horizontal[(y + 1) * 8 + x] if y < 7 else 0) for y in range(8) for x in range(8)]
    magnitude = math.sqrt(sum(v * v for v in grid)) or 1
    return cloud, tuple(v / magnitude for v in grid)


def cloud_distance(a, b):
    def distance(source, target):
        return sum(min((x - u) ** 2 + (y - v) ** 2 for u, v in target)
                   for x, y in source) / len(source)
    return (distance(a, b) + distance(b, a)) / 2


def stroke_distance(a, b):
    """Match individual strokes without requiring their order or direction."""
    costs = []
    for i, stroke in enumerate(a):
        for j, other in enumerate(b):
            forward = sum((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for p, q in zip(stroke, other))
            backward = sum((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for p, q in zip(stroke, reversed(other)))
            costs.append((min(forward, backward) / len(stroke), i, j))
    used_a, used_b, total = set(), set(), 0.0
    for cost, i, j in sorted(costs):
        if i not in used_a and j not in used_b:
            total += cost
            used_a.add(i)
            used_b.add(j)
    return total / len(a)


@dataclass(frozen=True)
class Template:
    char: str
    mode: str
    strokes: tuple
    cloud: tuple
    grid: tuple


class HandwritingRecognizer:
    def __init__(self, path=None, cancelled=lambda: False):
        self.templates = []
        self.counts = {'all': 0, 'hans': 0, 'hant': 0, 'ja': 0}
        index = resource_path('assets/strokes/handwriting.json.zlib')
        if path is None and index.exists():
            try:
                data = json.loads(zlib.decompress(index.read_bytes()))
                if data['version'] != 2:
                    raise ValueError('Unsupported handwriting index')
                for char, mode, strokes, cloud, grid in data['templates']:
                    if cancelled():
                        return
                    self.templates.append(Template(char, mode, tuple(tuple(tuple(p) for p in s) for s in strokes),
                                                   tuple(tuple(p) for p in cloud), tuple(grid)))
                    self.counts[mode] += 1
                self.counts['all'] = len({t.char for t in self.templates})
                if self.templates:
                    return
            except (ValueError, KeyError, TypeError, zlib.error):
                # A missing or obsolete derived index can be rebuilt in memory.
                self.templates.clear()
                self.counts = dict.fromkeys(self.counts, 0)
        path = Path(path) if path is not None else resource_path('assets/strokes/characters.sqlite3')
        if not path.exists():
            raise FileNotFoundError('The bundled stroke pack is missing. Restore assets/strokes/characters.sqlite3.')
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            for mode, char, compressed in conn.execute('SELECT mode,char,graphics FROM glyphs ORDER BY mode,char'):
                if cancelled():
                    return
                if mode not in self.counts:
                    continue
                graphics = json.loads(zlib.decompress(compressed))
                strokes = normalize([[(x, 900 - y) for x, y in s] for s in graphics['medians']])
                if strokes:
                    cloud, grid = features(strokes)
                    self.templates.append(Template(char, mode, tuple(tuple(resample(s, 8)) for s in strokes), cloud, grid))
                    self.counts[mode] += 1
        finally:
            conn.close()
        self.counts['all'] = len({t.char for t in self.templates})
        if not self.templates and not cancelled():
            raise ValueError('The bundled stroke pack contains no handwriting templates.')

    def recognize(self, strokes, mode='all', limit=24, cancelled=lambda: False):
        if mode not in self.counts:
            raise ValueError('Unknown handwriting mode')
        strokes = normalize(strokes)
        if not strokes or limit <= 0:
            return []
        cloud, grid = features(strokes)
        sampled = tuple(tuple(resample(s, 8)) for s in strokes)
        coarse = []
        for index, template in enumerate(self.templates):
            if index % 128 == 0 and cancelled():
                return []
            if mode != 'all' and template.mode != mode:
                continue
            count_penalty = abs(len(strokes) - len(template.strokes)) / max(len(strokes), len(template.strokes))
            score = 1 - sum(a * b for a, b in zip(grid, template.grid)) + .12 * count_penalty
            coarse.append((score, index))
        ranked = {}
        for _, index in heapq.nsmallest(100, coarse):
            if cancelled():
                return []
            template = self.templates[index]
            score = cloud_distance(cloud, template.cloud)
            count_penalty = abs(len(strokes) - len(template.strokes)) / max(len(strokes), len(template.strokes))
            score += .06 * count_penalty
            if len(sampled) == len(template.strokes):
                score += .22 * stroke_distance(sampled, template.strokes)
                # Stroke order is a small tie-breaker; geometry remains dominant.
                ordered = sum(min(sum(math.dist(p, q) ** 2 for p, q in zip(a, b)),
                                  sum(math.dist(p, q) ** 2 for p, q in zip(a, reversed(b))))
                              for a, b in zip(sampled, template.strokes)) / (8 * len(sampled))
                score += .001 * ordered
            previous = ranked.get(template.char)
            if previous is None or score < previous['distance']:
                ranked[template.char] = {'char': template.char, 'mode': template.mode, 'distance': score}
        return sorted(ranked.values(), key=lambda row: (row['distance'], row['char']))[:limit]


def build_index(source, target):
    """Regenerate the bundled acceleration index after updating regional medians."""
    import hashlib
    recognizer = HandwritingRecognizer(source)
    def rounded(points):
        return [[round(x, 5), round(y, 5)] for x, y in points]
    data = {'version': 2, 'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            'source': 'AnimCJK medians; see assets/strokes/manifest.json and bundled licences',
            'templates': [[t.char, t.mode, [rounded(s) for s in t.strokes], rounded(t.cloud),
                           [round(v, 5) for v in t.grid]] for t in recognizer.templates]}
    content = zlib.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9)
    target = Path(target)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(target)
    return recognizer.counts
