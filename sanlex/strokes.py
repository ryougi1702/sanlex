"""Offline regional glyph data and language-specific character relationships."""
from collections import deque
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3
import zlib

from .db import resource_path
from .text import is_han, parse_ids

MODES = {'hans': ('Simplified Chinese', 'CN · Mainland'),
         'hant': ('Traditional Chinese', 'CN · Taiwan'),
         'ja': ('Japanese', 'JP')}
REGIONS = {'hans': 'G', 'hant': 'T', 'ja': 'J'}


@lru_cache(maxsize=1)
def joyo_forms():
    path = resource_path('assets/joyo-forms.tsv')
    pairs = dict(line.split() for line in path.read_text(encoding='utf-8').splitlines()
                 if line and not line.startswith('#')) if path.is_file() else {}
    return pairs, {older: modern for modern, older in pairs.items()}


def unihan_variants(data, field):
    return [chr(int(code, 16)) for code in re.findall(r'U\+([0-9A-Fa-f]+)', data.get(field, ''))]


class StrokeStore:
    def __init__(self, path=None):
        path = Path(path) if path else resource_path('assets/strokes/characters.sqlite3')
        self.conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) if path.exists() else None

    def close(self):
        self.record.cache_clear()
        if self.conn:
            self.conn.close()
            self.conn = None

    @lru_cache(maxsize=512)
    def record(self, char, mode):
        row = self.conn.execute('SELECT graphics,metadata FROM glyphs WHERE mode=? AND char=?',
                                (mode,char)).fetchone() if self.conn else None
        return {'graphics':json.loads(zlib.decompress(row[0])), 'metadata':json.loads(row[1])} if row else None

    def parents(self, char, mode):
        return [row[0] for row in self.conn.execute('SELECT parent FROM parts WHERE mode=? AND component=? ORDER BY parent',
                                                   (mode,char))] if self.conn else []


class CharacterAnalysis:
    def __init__(self, db, strokes):
        self.db, self.strokes = db, strokes

    def variants(self, char, mode):
        older_forms, modern_forms = joyo_forms()
        data = self.db.character(char)
        uni = data['unihan']
        if mode == 'ja':
            if char in modern_forms:
                modern = modern_forms[char]
                return [modern, char] if self.has_japanese_data(char) else [modern]
            # Shared modern forms such as 学 and 将 are already Japanese.
            if char in older_forms or data['kanjidic'] or self.strokes.record(char, 'ja'):
                return [char]
            related = unihan_variants(uni, 'kTraditionalVariant') + unihan_variants(uni, 'kSimplifiedVariant')
            # A reading alone can be recorded for a Chinese form such as 边.
            # Prefer an explicit modern Japanese counterpart when one is known.
            if not any(candidate in modern_forms for candidate in related) and self.has_japanese_data(char):
                return [char]
            candidates = []
            for candidate in related:
                if candidate == char:
                    continue
                if candidate in modern_forms:
                    candidates.append(modern_forms[candidate])
                elif self.has_japanese_data(candidate):
                    candidates.append(candidate)
            return list(dict.fromkeys(candidates)) or [char]

        field = 'kSimplifiedVariant' if mode == 'hans' else 'kTraditionalVariant'
        variants = unihan_variants(uni, field)
        if variants:
            return list(dict.fromkeys(variants))
        older = older_forms.get(char)
        if older and not self.strokes.record(char, mode):
            # Use the documented older form as a bridge only when Chinese
            # variant data or a glyph for this region supports the result.
            simplified = unihan_variants(self.db.character(older)['unihan'], 'kSimplifiedVariant')
            if simplified:
                return list(dict.fromkeys(simplified)) if mode == 'hans' else [older]
            if self.strokes.record(older, mode):
                return [older]
        return [char]

    def has_japanese_data(self, char):
        data = self.db.character(char)
        return bool(data['kanjidic'] or data['unihan'].get('kJapaneseOn') or
                    data['unihan'].get('kJapaneseKun') or self.strokes.record(char, 'ja'))

    def structures(self, char, mode):
        record = self.strokes.record(char,mode)
        expression = record['metadata'].get('decomposition', '') if record else ''
        if expression and expression != '？':
            return [(expression, 'AnimCJK · ' + MODES[mode][1])]
        result = []
        for row in self.db.character(char)['decompositions']:
            expression = row['expression']
            regions = re.findall(r'\[([A-Z]+)\]',expression)
            if not regions or any(REGIONS[mode] in group for group in regions):
                result.append((expression, row['source'] + (' · regional' if regions else ' · shared / region unspecified')))
        return result

    def components(self, char, mode):
        result = []
        for expression, _ in self.structures(char,mode):
            try:
                result.extend(c for c in parse_ids(expression).leaves() if c != char and is_han(c))
            except ValueError:
                continue
        return list(dict.fromkeys(result))

    def direct_parents(self, char, mode):
        candidates = set(self.strokes.parents(char,mode))
        candidates.update(row[0] for row in self.db.conn.execute(
            'SELECT DISTINCT parent FROM components WHERE component=? AND parent<>?', (char,char)))
        result = []
        for parent in sorted(candidates):
            if mode == 'ja':
                data = self.db.character(parent)
                if not self.strokes.record(parent,mode) and not data['kanjidic'] and not any(
                    re.search(r'\[[A-Z]*J[A-Z]*\]',row['expression']) for row in data['decompositions']):
                    continue
            elif self.script_conflict(parent,mode):
                continue
            if char in self.components(parent,mode):
                result.append(parent)
        return result

    def parents(self, char, mode, recursive=False, limit=100):
        queue, seen, result = deque([(char,True)]), {char}, []
        while queue:
            component, direct = queue.popleft()
            for parent in self.direct_parents(component,mode):
                if parent in seen:
                    continue
                seen.add(parent)
                result.append((parent,direct))
                if len(result) > limit:
                    return result[:limit], True
                if recursive:
                    queue.append((parent,False))
        return result, False

    @lru_cache(maxsize=8192)
    def script_conflict(self, char, mode):
        if not is_han(char):
            return False
        uni = self.db.character(char)['unihan']
        # A form shared by both scripts is allowed in both. Variant relations are
        # not a language detector, so uncertain forms are kept rather than rewritten.
        field = 'kSimplifiedVariant' if mode == 'hans' else 'kTraditionalVariant'
        other = 'kTraditionalVariant' if mode == 'hans' else 'kSimplifiedVariant'
        return bool(uni.get(field) and not uni.get(other) and
                    any(chr(int(code,16)) != char for code in re.findall(r'U\+([0-9A-Fa-f]+)', uni[field])))

    def words(self, char, mode, limit=40, *, sources=None, directions=None):
        lang = 'jp' if mode == 'ja' else 'cn'
        suffix, args = self.db.entry_filters(sources,directions)
        # CC-CEDICT explicitly supplies a simplified headword then its traditional
        # spelling. Other sources keep their own headword without automatic conversion.
        display = "coalesce(json_extract(e.forms,'$[1]'),e.headword)" if mode == 'hant' else 'e.headword'
        display = f"CASE WHEN e.source='cedict' THEN {display} ELSE e.headword END"
        rows = self.db.conn.execute(
            'SELECT e.*,' + display + ' display_word FROM word_chars wc CROSS JOIN entries e ON e.id=wc.entry_id '
            'WHERE wc.char=? AND e.lang=?' + suffix + ' AND instr(' + display + ',?)>0 '
            'ORDER BY e.common DESC,length(e.headword),e.headword,e.source', [char,lang,*args,char])
        result, seen = [], set()
        for row in rows:
            word = self.db.decode(row)
            shown = word['display_word']
            if mode != 'ja' and word['source'] != 'cedict' and any(self.script_conflict(c,mode) for c in shown):
                continue
            key = (shown,word['reading'],word['definition_lang'],tuple(word['glosses']))
            if key in seen:
                continue
            seen.add(key)
            result.append(word)
            if len(result) >= limit:
                break
        return result
