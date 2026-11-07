"""Generate word lookup links from installed dictionary spellings."""
from html import escape
import re
from urllib.parse import quote

from .text import normalize


class DefinitionLinker:
    def __init__(self, db, *, sources=None, directions=None):
        self.db = db
        self.sources, self.directions = sources, directions
        self.cache = {}

    def render(self, text, lang):
        # Work in original-text offsets so normalization never changes labels.
        # Bound phrase length and query batches to keep long entries responsive.
        candidates = {}
        for run in re.finditer(r"\w+(?:[ '\-’]\w+)*", text):
            for start in range(run.start(), run.end()):
                if not text[start].isalnum() or self.inside_latin_word(text, start):
                    continue
                for end in range(start + 2, min(run.end(), start + 48) + 1):
                    if not text[end - 1].isalnum() or self.inside_latin_word(text, end):
                        continue
                    label = text[start:end]
                    if any(c.isalpha() for c in label) and self.complete_kana_run(text, start, end):
                        term = normalize(label)
                        candidates.setdefault(start, []).append((end, term))
        terms = {term for matches in candidates.values() for _, term in matches}
        missing = sorted(term for term in terms if (lang, term) not in self.cache)
        for offset in range(0, len(missing), 400):
            batch = missing[offset:offset + 400]
            targets = self.db.definition_targets(batch, lang, sources=self.sources, directions=self.directions)
            self.cache.update(((lang, term), targets.get(term)) for term in batch)
        output, position = [], 0
        while position < len(text):
            match = next(((end, self.cache[lang, term])
                          for end, term in reversed(candidates.get(position, []))
                          if self.cache.get((lang, term))), None)
            if match:
                end, entry_id = match
                label = text[position:end]
                output.append(f'<a href="entry:{quote(entry_id, safe="")}" '
                              f'title="Look up {escape(label, quote=True)}" '
                              f'style="text-decoration:underline">{escape(label)}</a>')
                position = end
            else:
                output.append(escape(text[position]))
                position += 1
        return ''.join(output)

    @staticmethod
    def complete_kana_run(text, start, end):
        # Without a sentence tokenizer, a kana-only dictionary match is safe
        # only at script boundaries; e.g. でい inside でいう is misleading.
        def script(char):
            if 'ぁ' <= char <= 'ゖ':
                return 'hiragana'
            if 'ァ' <= char <= 'ヺ' or char == 'ー':
                return 'katakana'
            return None

        kind = script(text[start])
        if kind and all(script(c) == kind for c in text[start:end]):
            return ((start == 0 or script(text[start - 1]) != kind) and
                    (end == len(text) or script(text[end]) != kind))
        return True

    @staticmethod
    def inside_latin_word(text, position):
        if position == 0 or position == len(text):
            return False
        return all((c.isascii() and c.isalnum()) or c in "_'’-"
                   for c in text[position - 1:position + 1])
