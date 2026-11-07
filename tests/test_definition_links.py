"""Exact written-word links, filters, boundaries and safe HTML rendering."""
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

from sanlex.db import Dictionary
from sanlex.definition_links import DefinitionLinker


class DefinitionLinkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Dictionary(Path(self.directory.name) / 'dictionary.sqlite3')
        self.db.initialize()
        with self.db.conn:
            for identifier, word, lang, source, definition_lang in [
                ('jp:kyogen', '狂言', 'jp', 'jmdict', 'en'),
                ('jp:actor', '狂言師', 'jp', 'jmdict', 'en'),
                ('jp:native', '狂言', 'jp', 'wiktionary-ja', 'jp'),
                ('cn:kyogen', '狂言', 'cn', 'cedict', 'en'),
                ('en:water', 'water', 'en', 'wiktionary-ja', 'jp'),
                ('en:bird', 'water bird', 'en', 'wiktionary-ja', 'jp'),
                ('jp:rare', '𠀀語', 'jp', 'jmdict', 'en'),
                ('jp:kana', 'でい', 'jp', 'jmdict', 'en'),
                ('jp:kata', 'ワキ', 'jp', 'jmdict', 'en'),
            ]:
                self.db.add_entry({'id': identifier, 'headword': word, 'lang': lang,
                                   'reading': 'きょうげん' if word == '狂言' else '',
                                   'forms': ['狂言劇'] if identifier == 'jp:kyogen' else [],
                                   'source': source, 'definition_lang': definition_lang, 'glosses': ['test']})

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def href(self, identifier):
        return 'entry:' + quote(identifier, safe='')

    def test_longest_nonoverlapping_spellings_and_unknown_text(self):
        linker = DefinitionLinker(self.db)
        text = linker.render('狂言師による狂言。𠀀語と未登録の字。', 'jp')
        self.assertEqual(text.count('<a '), 3)
        self.assertIn(self.href('jp:actor'), text)
        self.assertIn(self.href('jp:native'), text)
        self.assertIn(self.href('jp:rare'), text)
        self.assertNotIn('analyse:', text)
        self.assertIn('未登録の字。', text)
        self.assertIn(self.href('jp:kyogen'), linker.render('狂言劇', 'jp'))
        self.assertEqual(linker.render('きょうげん', 'jp'), 'きょうげん')

    def test_language_sources_directions_and_cache_are_separate(self):
        linker = DefinitionLinker(self.db)
        self.assertIn(self.href('cn:kyogen'), linker.render('狂言', 'cn'))
        self.assertIn(self.href('jp:native'), linker.render('狂言', 'jp'))
        linker = DefinitionLinker(self.db, sources=('jmdict',))
        self.assertIn(self.href('jp:kyogen'), linker.render('狂言', 'jp'))
        self.assertEqual(linker.render('狂言', 'cn'), '狂言')
        linker = DefinitionLinker(self.db, directions=(('jp', 'en'),))
        self.assertIn(self.href('jp:kyogen'), linker.render('狂言', 'jp'))
        self.assertEqual(DefinitionLinker(self.db, sources=()).render('狂言', 'jp'), '狂言')

    def test_english_phrase_boundaries_and_escaping(self):
        text = DefinitionLinker(self.db).render('A WATER bird; waterfall water’s <water> & "unknown".', 'en')
        self.assertEqual(text.count('<a '), 2)
        self.assertIn(self.href('en:bird'), text)
        self.assertIn('>WATER bird</a>', text)
        self.assertIn('waterfall water’s &lt;', text)
        self.assertIn('&gt; &amp; &quot;unknown&quot;.', text)
        self.assertEqual(DefinitionLinker(self.db).render('', 'en'), '')

    def test_kana_fragments_inside_longer_expressions_are_left_plain(self):
        text = DefinitionLinker(self.db).render('狂言でいうワキにあたる者。', 'jp')
        self.assertIn(self.href('jp:kata'), text)
        self.assertNotIn(self.href('jp:kana'), text)
        self.assertIn('でいう', text)


if __name__ == '__main__':
    unittest.main()
