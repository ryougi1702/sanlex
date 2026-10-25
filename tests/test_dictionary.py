import gzip
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile

from sample_data import populate
from sanlex.db import Dictionary
from sanlex.importers import Cancelled, install_source
from sanlex.text import gloss_key, normalize, parse_ids, reading_aliases, romaji


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = Dictionary(self.root / 'dictionary.sqlite3')
        self.db.initialize()
        populate(self.db)

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def entry(self, word, lang):
        return next(e for e in self.db.search(word, lang) if e['headword'] == word)

    def fixture(self, filename, content):
        path = self.root / filename
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            stream.write(content)
        return path

    def test_fresh_database_has_no_sample_dictionary(self):
        db = Dictionary(self.root / 'empty' / 'dictionary.sqlite3')
        try:
            db.initialize()
            db.initialize()
            self.assertEqual(db.sources(), {})
            self.assertEqual(db.search('school'), [])
        finally:
            db.close()

    def test_existing_sample_is_removed_without_changing_other_sources(self):
        with self.db.conn:
            self.db.add_entry({'id': 'starter:retired:jp', 'lang': 'jp', 'headword': '試作語',
                               'reading': '', 'glosses': ['retiredsampleword'], 'source': 'starter'})
            self.db.add_decomposition('梯', '⿰木弟', 'starter')
            self.db.set_source('starter', {'entries': 1})
        original = self.db.entry('fixture:school:jp')
        self.db.toggle_favorite(original['id'])
        self.db.initialize()
        self.db.initialize()
        self.assertNotIn('starter', self.db.sources())
        self.assertIsNone(self.db.entry('starter:retired:jp'))
        self.assertEqual(self.db.search('retiredsampleword'), [])
        self.assertEqual(self.db.search('試作語'), [])
        for table in ('forms', 'gloss_index', 'word_chars'):
            self.assertEqual(self.db.conn.execute(
                f"SELECT count(*) FROM {table} WHERE entry_id LIKE 'starter:%'").fetchone()[0], 0)
        for table in ('components', 'decompositions', 'lexical_links'):
            self.assertEqual(self.db.conn.execute(
                f"SELECT count(*) FROM {table} WHERE source='starter'").fetchone()[0], 0)
        self.assertEqual(self.db.entry(original['id']), original)
        self.assertTrue(self.db.is_favorite(original['id']))
        self.assertIn('梯', [p['parent'] for p in self.db.part_of('弟', False)[0]])

    def test_search_all_three_languages_and_scripts(self):
        for query in ('school', '学校', '學校', 'がっこう', 'ガッコウ', 'gakkou', 'xue2 xiao4', 'xuexiao', 'xué xiào'):
            with self.subTest(query=query):
                self.assertTrue(self.db.search(query))
        self.assertEqual({e['lang'] for e in self.db.search('school')}, {'jp', 'cn'})
        self.assertEqual({e['lang'] for e in self.db.search('school', 'jp')}, {'jp'})

    def test_autocomplete_prefixes_reading_aliases_and_filters(self):
        for query,language in [('学','jp'),('がっこ','jp'),('ガッコ','jp'),('gakk','jp'),
                               ('学校','cn'),('xue2 x','cn'),('xuex','cn'),('xué xi','cn')]:
            rows=self.db.autocomplete(query,language)
            self.assertTrue(any(r['headword']=='学校' for r in rows),(query,rows))
            self.assertLessEqual(len(rows),10)
            self.assertTrue(all(r['lang']==language and 'senses' not in r for r in rows))
        self.assertEqual(self.db.autocomplete('学',sources=()),[])
        self.assertEqual(self.db.autocomplete('学',directions=(('en','jp'),)),[])
        self.assertEqual(self.db.autocomplete('   '),[])

    def test_autocomplete_filters_before_limit_and_exact_before_prefix(self):
        with self.db.conn:
            for i in range(150):
                self.db.add_entry({'id':f'other:{i}','lang':'en','headword':f'school{i:03}',
                    'reading':'','glosses':['school meaning'],'source':'other','common':1})
            for word in ('school','schoolhouse'):
                self.db.add_entry({'id':'chosen:'+word,'lang':'en','headword':word,'reading':'',
                    'glosses':['English definition'],'source':'chosen'})
        rows=self.db.autocomplete('school',sources=('chosen',),directions=(('en','en'),),limit=1)
        self.assertEqual([r['id'] for r in rows],['chosen:school'])
        self.assertEqual(self.db.autocomplete('school',sources=('chosen',),directions=()),[])
        self.assertEqual(self.db.autocomplete("'; DROP TABLE entries;--"),[])

    def test_trilingual_mappings_both_directions(self):
        japanese = self.entry('弟', 'jp')
        chinese = self.entry('弟弟', 'cn')
        self.assertTrue(any(e['headword'] == '弟弟' and reason.startswith('Suggested') for e, reason in self.db.mappings(japanese)))
        self.assertTrue(any(e['headword'] == '弟' and reason.startswith('Suggested') for e, reason in self.db.mappings(chinese)))

    def test_filters_apply_to_all_search_paths_before_limit(self):
        with self.db.conn:
            for source in ('first-file', 'second-file'):
                for origin in ('en', 'jp', 'cn'):
                    for target in ('en', 'jp', 'cn'):
                        self.db.add_entry({'id': f'{source}:{origin}:{target}',
                            'headword': f'filterprobe-{source}-{origin}-{target}', 'reading': '',
                            'lang': origin, 'definition_lang': target, 'source': source,
                            'common': 1 if source == 'first-file' else 0, 'glosses': ['filterprobe']})
        all_results = self.db.search('filterprobe')
        self.assertEqual(len(all_results), 18)
        results = self.db.search('filterprobe', limit=1, sources=('second-file',), directions=(('jp','jp'),))
        self.assertEqual([e['id'] for e in results], ['second-file:jp:jp'])
        exact = self.db.search(results[0]['headword'], sources=('second-file',), directions=(('jp','jp'),))
        self.assertEqual(exact[0]['id'], results[0]['id'])
        self.assertEqual(self.db.search('filterprobe', sources=[]), [])
        self.assertEqual(self.db.search('filterprobe', directions=[]), [])
        self.assertEqual(self.db.search('filterprobe', sources=["'); DROP TABLE entries;--"]), [])
        self.assertEqual(self.db.search('filterprobe', lang='cn', directions=(('jp','jp'),)), [])

    def test_filters_apply_to_related_content_and_preserve_character_metadata(self):
        japanese = self.entry('弟', 'jp')
        self.assertTrue(self.db.mappings(japanese, sources=('fixture',), directions=(('jp','cn'),)))
        self.assertEqual(self.db.mappings(japanese, sources=(), directions=(('jp','cn'),)), [])
        self.assertEqual(self.db.mappings(japanese, directions=(('jp','jp'),)), [])
        self.assertEqual(self.db.containing('弟', sources=()), [])
        self.db.toggle_favorite(japanese['id'])
        self.assertEqual(self.db.favorites(sources=()), [])
        self.assertEqual(self.db.favorites(directions=(('cn','en'),)), [])
        self.assertEqual(len(self.db.favorites(sources=('fixture',), directions=(('jp','en'),))), 1)
        self.assertEqual(self.db.character('梯')['unihan']['kRSUnicode'], '75.7')

    def test_excluded_sources_do_not_leak_into_localized_definitions_or_translation_links(self):
        with self.db.conn:
            for identifier, source, definition_lang, meaning in (
                ('test:base', 'jmdict', 'en', 'protection'),
                ('test:ja', 'wiktionary-ja', 'jp', '危険から守ること'),
                ('test:zh', 'wiktionary-zh', 'cn', '保护')):
                self.db.add_entry({'id':identifier, 'headword':'保護', 'reading':'ほご', 'lang':'jp',
                                   'definition_lang':definition_lang, 'glosses':[meaning], 'source':source})
            self.db.conn.execute('INSERT INTO lexical_links VALUES(?,?,?,?,?,?,?,?)',
                ('jp','保護','cn','保护','bao3 hu4','protection','wiktionary-ja','https://ja.wiktionary.org/wiki/保護'))
        base = self.db.entry('test:base')
        self.assertEqual(self.db.localized_definitions(base, sources=('jmdict',)), [])
        self.assertEqual(self.db.mappings(base, sources=('jmdict',)), [])
        native = self.db.localized_definitions(base, sources=('wiktionary-ja',), directions=(('jp','jp'),))
        self.assertEqual([e['id'] for e in native], ['test:ja'])
        self.assertEqual(self.db.localized_definitions(base, sources=('wiktionary-ja',), directions=(('jp','cn'),)), [])
        links = self.db.mappings(base, sources=('wiktionary-ja',), directions=(('jp','cn'),))
        self.assertEqual([e['_translation_word'] for e, reason in links], ['保护'])
        self.assertEqual(self.db.mappings(base, sources=('wiktionary-zh',), directions=(('jp','cn'),)), [])

    def test_direct_and_nested_part_of(self):
        self.assertIn('梯', [p['parent'] for p in self.db.part_of('弟', False)[0]])
        self.assertNotIn('弟', [p['parent'] for p in self.db.part_of('弟')[0]])
        with self.db.conn:
            self.db.add_decomposition('甲', '⿰乙木', 'test')
            self.db.add_decomposition('申', '⿰甲火', 'test')
        direct = self.db.part_of('乙', False)[0]
        nested = self.db.part_of('乙', True)[0]
        self.assertEqual([r['parent'] for r in direct], ['甲'])
        self.assertEqual({r['parent']: r['direct'] for r in nested}, {'甲': 1, '申': 0})

    def test_cycles_terminate(self):
        with self.db.conn:
            self.db.add_decomposition('甲', '⿰乙木', 'test')
            self.db.add_decomposition('乙', '⿰甲火', 'test')
        self.assertEqual([r['parent'] for r in self.db.part_of('乙')[0]], ['甲'])

    def test_components_are_not_radicals(self):
        char = self.db.character('梯')
        self.assertEqual(char['unihan']['kRSUnicode'], '75.7')
        self.assertEqual(parse_ids(char['decompositions'][0]['expression']).leaves(), ['木', '弟'])
        self.assertTrue(any(e['headword'] == '梯子' for e in self.db.containing('梯')))

    def test_saves_and_history_persist_separately(self):
        entry = self.entry('水', 'jp')
        self.assertTrue(self.db.toggle_favorite(entry['id']))
        self.db.record_search('water')
        other = Dictionary(self.db.path)
        try:
            self.assertTrue(other.is_favorite(entry['id']))
            self.assertEqual(other.history(), ['water'])
            self.assertEqual(other.favorites()[0]['id'], entry['id'])
        finally:
            other.close()
        self.assertTrue(self.db.path.with_name('user.sqlite3').exists())

    def test_user_saves_during_dictionary_write(self):
        writer = Dictionary(self.db.path)
        try:
            writer.conn.execute("UPDATE settings SET value=value")
            self.db.record_search('still responsive')
            self.db.toggle_favorite(self.entry('木', 'jp')['id'])
        finally:
            writer.conn.rollback()
            writer.close()

    def test_fts_special_input_is_literal(self):
        for query in ('" OR *', 'school" OR "cat', "'; DROP TABLE entries;--", '()', '水*', '𠮷'):
            self.db.search(query)
        self.assertTrue(self.db.search('school'))

    def test_gloss_qualifiers_preserved(self):
        self.assertNotEqual(gloss_key('school (of fish)'), gloss_key('school'))
        self.assertEqual(gloss_key('to eat'), 'eat')

    def test_rebuilding_indexes_keeps_entries_and_bookmarks(self):
        entry = self.entry('学校', 'jp')
        self.db.toggle_favorite(entry['id'])
        self.db.rebuild_search(lambda _: None)
        self.assertTrue(self.db.search('ガッコウ'))
        self.assertTrue(self.db.search('gakkou'))
        self.assertTrue(self.db.is_favorite(entry['id']))

    def test_cedict_import_update_and_stable_bookmarks(self):
        path = self.fixture('cedict.gz', '# test\n學校 学校 [xue2 xiao4] /school/\n綠 绿 [lu:4] /green/\n')
        install_source(self.db, 'cedict', path, lambda _: None)
        green = self.entry('绿', 'cn')
        self.assertTrue(self.db.search('lv4', 'cn'))
        self.db.toggle_favorite(green['id'])
        install_source(self.db, 'cedict', path, lambda _: None)
        self.assertTrue(self.db.is_favorite(green['id']))
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM entries WHERE source='cedict'").fetchone()[0], 2)

    def test_cancelled_import_rolls_back(self):
        old = self.fixture('old.gz', '木 木 [mu4] /wood/\n')
        install_source(self.db, 'cedict', old, lambda _: None)
        new = self.fixture('new.gz', '水 水 [shui3] /water/\n')
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            install_source(self.db, 'cedict', new, lambda _: None, cancel)
        self.assertEqual(self.db.conn.execute("SELECT headword FROM entries WHERE source='cedict'").fetchone()[0], '木')

    def test_bad_source_rolls_back_existing_data(self):
        old = self.fixture('old.gz', '木 木 [mu4] /wood/\n')
        install_source(self.db, 'cedict', old, lambda _: None)
        bad = self.fixture('bad.gz', 'invalid data\n')
        with self.assertRaises(ValueError):
            install_source(self.db, 'cedict', bad, lambda _: None)
        self.assertTrue(self.db.search('wood'))
        self.assertEqual(self.db.sources()['cedict']['entries'], 1)

    def test_jmdict_entities_and_sense_restrictions(self):
        xml = '''<?xml version="1.0"?><!DOCTYPE JMdict [<!ENTITY n "noun">]><JMdict><entry>
          <ent_seq>123</ent_seq><k_ele><keb>学校</keb><ke_pri>ichi1</ke_pri></k_ele>
          <r_ele><reb>がっこう</reb><re_restr>学校</re_restr></r_ele>
          <sense><pos>&n;</pos><gloss>school</gloss></sense>
          <sense><stagk>学校</stagk><gloss>educational institution</gloss></sense>
        </entry></JMdict>'''
        install_source(self.db, 'jmdict', self.fixture('jmdict.gz', xml), lambda _: None)
        entry = self.db.entry('jmdict:123')
        self.assertEqual(entry['senses'][1]['pos'], ['noun'])
        self.assertEqual(entry['senses'][1]['spellings'], ['学校'])
        self.assertEqual(entry['senses'][0]['reading_restrictions'][0]['spellings'], ['学校'])
        self.assertTrue(any(e['id'] == entry['id'] for e in self.db.search('gakkou')))

    def test_wiktionary_native_definitions_and_reverse_links(self):
        item = {'word': '保護', 'lang_code': 'ja', 'pos': 'noun',
                'forms': [{'form': 'ほご', 'tags': ['transliteration']}],
                'sounds': [{'other': '('}], 'senses': [{'glosses': ['危険から守ること。']}],
                'translations': [{'lang_code': 'zh', 'word': '保护', 'sense': '危険から守る', 'roman': 'bǎohù'},
                                 {'lang_code': 'en', 'word': 'protection', 'sense': '危険から守る'}]}
        path = self.fixture('wiki.gz', json.dumps(item, ensure_ascii=False) + '\n')
        install_source(self.db, 'wiktionary-ja', path, lambda _: None)
        entry = self.entry('保護', 'jp')
        self.assertEqual(entry['definition_lang'], 'jp')
        self.assertEqual(entry['reading'], 'ほご')
        self.assertTrue(self.db.search('hogo'))
        mapped = self.db.mappings(entry)
        self.assertEqual({e['_translation_word'] for e, _ in mapped}, {'保护', 'protection'})
        with self.db.conn:
            self.db.add_entry({'id': 'test:protect', 'headword': '保护', 'reading': 'bao3 hu4',
                               'lang': 'cn', 'glosses': ['protect'], 'source': 'test'})
        self.assertTrue(any(e['headword'] == '保護' for e, _ in self.db.mappings(self.db.entry('test:protect'))))

    def test_unihan_import_and_ids_regions(self):
        archive = self.root / 'unihan.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('Unihan_Readings.txt', 'U+68AF\tkDefinition\tladder\nU+68AF\tkMandarin\ttī\n')
            stream.writestr('Unihan_IRGSources.txt', 'U+68AF\tkRSUnicode\t75.7\n')
        install_source(self.db, 'unihan', archive, lambda _: None)
        self.assertEqual(self.db.character('梯')['unihan']['kMandarin'], 'tī')
        path = self.root / 'ids.txt'
        path.write_text('U+68AF\t梯\t⿰木弟[G]\t⿰木弟[J]\n', encoding='utf-8')
        install_source(self.db, 'ids', path, lambda _: None)
        self.assertEqual(len(self.db.character('梯')['decompositions']), 3)
        self.assertIn('梯', [e['parent'] for e in self.db.part_of('弟')[0]])
        self.assertNotIn('G', [r[0] for r in self.db.conn.execute('SELECT component FROM components')])


class TextTests(unittest.TestCase):
    def test_unicode_and_readings(self):
        self.assertEqual(normalize('lǜ'), 'lv')
        self.assertEqual(normalize('lu:4'), 'lv4')
        self.assertNotEqual(normalize('がく'), normalize('かく'))
        self.assertEqual(romaji('ガッコウ'), 'gakkou')
        self.assertEqual(romaji('ちゃ'), 'cha')
        self.assertEqual(romaji('コンピューター'), 'konpyuutaa')
        self.assertIn('nihao', reading_aliases('ni3 hao3', 'cn'))

    def test_ids_nested_ternary_and_malformed(self):
        self.assertEqual(parse_ids('⿱木⿰木木[J]').leaves(), ['木', '木', '木'])
        self.assertEqual(parse_ids('⿲木木木').leaves(), ['木', '木', '木'])
        self.assertEqual(parse_ids('⿾木').leaves(), ['木'])
        for expression in ('⿰木', '木木', ''):
            with self.assertRaises(ValueError):
                parse_ids(expression)


if __name__ == '__main__':
    unittest.main()
