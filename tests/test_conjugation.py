"""Japanese lookup behavior: real forms, POS validation, ranking and filters."""
from pathlib import Path
import tempfile
import unittest

from sanlex.conjugation import MAX_CANDIDATES, deinflect
from sanlex.db import Dictionary


def add_word(db, word, reading, pos, *, identifier=None, source='grammar', lang='jp', target='en', common=0):
    identifier = identifier or 'grammar:' + word
    db.add_entry({'id': identifier, 'headword': word, 'reading': reading, 'lang': lang,
                  'source': source, 'definition_lang': target, 'common': common,
                  'glosses': [word + ' definition'], 'senses': [{'pos': [pos], 'glosses': [word + ' definition']}]})
    return identifier


class ConjugationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Dictionary(Path(self.directory.name) / 'dictionary.sqlite3')
        self.db.initialize()
        with self.db.conn:
            for word, reading, pos in (
                    ('食べる', 'たべる', 'Ichidan verb'), ('見る', 'みる', 'v1'),
                    ('買う', 'かう', "Godan verb with 'u' ending"),
                    ('書く', 'かく', "Godan verb with 'ku' ending"),
                    ('泳ぐ', 'およぐ', 'v5g'), ('話す', 'はなす', 'v5s'),
                    ('待つ', 'まつ', 'v5t'), ('死ぬ', 'しぬ', 'v5n'),
                    ('遊ぶ', 'あそぶ', 'v5b'), ('読む', 'よむ', 'v5m'),
                    ('帰る', 'かえる', "Godan verb with 'ru' ending"),
                    ('行く', 'いく', 'Godan verb - Iku/Yuku special class'),
                    ('有る', 'ある', 'v5r-i'), ('する', 'する', 'suru verb - irregular'),
                    ('勉強', 'べんきょう', 'noun or participle which takes the aux. verb suru'),
                    ('来る', 'くる', 'Kuru verb - special class'),
                    ('高い', 'たかい', 'adjective (keiyoushi)'), ('いい', 'いい', 'adj-ix'),
                    ('静か', 'しずか', 'adjectival nouns or quasi-adjectives (keiyodoshi)')):
                add_word(self.db, word, reading, pos)

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_common_and_stacked_forms_resolve_to_the_correct_dictionary_entry(self):
        cases = {
            '食べました': '食べる', '食べませんでした': '食べる', '食べなかった': '食べる',
            '食べなくて': '食べる', '食べなければ': '食べる', '食べず': '食べる',
            '食べて': '食べる', '食べれば': '食べる', '食べたら': '食べる',
            '食べろ': '食べる', '食べよう': '食べる',
            '食べたい': '食べる', '食べたくなかった': '食べる', '食べられませんでした': '食べる',
            '食べさせられた': '食べる', '食べていました': '食べる', '食べていない': '食べる',
            '見た': '見る', '買った': '買う', '買わない': '買う', '買えます': '買う',
            '書いた': '書く', '書いて': '書く', '書かれました': '書く',
            '書かせなかった': '書く', '書けなかった': '書く', '書こう': '書く',
            '泳いだ': '泳ぐ', '泳いで': '泳ぐ', '話した': '話す', '話して': '話す',
            '待った': '待つ', '待てば': '待つ', '死んだ': '死ぬ', '遊んで': '遊ぶ',
            '読んだ': '読む', '読んだら': '読む', '読んだり': '読む',
            '読んでいた': '読む', '読んでる': '読む', '読める': '読む',
            '帰った': '帰る', '帰りません': '帰る', '帰ろう': '帰る',
            '行った': '行く', '行っていました': '行く', 'いきました': '行く',
            'なかった': '有る', 'しました': 'する', 'しない': 'する', 'できました': 'する',
            '勉強しました': '勉強', '勉強させられました': '勉強', '勉強できる': '勉強',
            '来ました': '来る', 'きました': '来る', 'こなかった': '来る',
            '来られない': '来る', 'こさせました': '来る', '来い': '来る',
            '高かった': '高い', '高くなかった': '高い', '高かったです': '高い',
            '高くありませんでした': '高い', 'よかった': 'いい', 'よくなかった': 'いい',
            '静かだった': '静か', '静かじゃなかった': '静か', '静かでした': '静か',
            '静かではありませんでした': '静か', 'たべました': '食べる', 'タベマシタ': '食べる',
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                rows = self.db.search(query, 'jp')
                self.assertIn(expected, [r['headword'] for r in rows])
                match = next(r['_conjugation'] for r in rows if r['headword'] == expected)
                self.assertEqual(match['query'], query)
                self.assertEqual(match['forms'][0], query)

    def test_explanations_order_grammar_from_dictionary_form_to_surface(self):
        entry = self.db.search('食べなかった', 'jp')[0]
        self.assertEqual(entry['_conjugation']['forms'], ['食べなかった', '食べない', '食べる'])
        self.assertEqual(entry['_conjugation']['reasons'], ['negative', 'past'])
        self.assertNotIn('_conjugation', self.db.entry(entry['id']))
        self.assertNotIn('_conjugation', self.db.search('食べる', 'jp')[0])

    def test_pos_and_irregular_classes_reject_invalid_analyses(self):
        with self.db.conn:
            add_word(self.db, '図書る', '', 'noun')
            add_word(self.db, '試験', '', 'noun')
            add_word(self.db, '知らる', '', '')
        for query, forbidden in (('図書ました', '図書る'), ('試験しました', '試験'),
                                 ('知らました', '知らる'), ('帰ました', '帰る'),
                                 ('食べった', '食べる'), ('行いた', '行く'), ('来ります', '来る')):
            with self.subTest(query=query):
                self.assertNotIn(forbidden, [r['headword'] for r in self.db.search(query, 'jp')])

    def test_exact_surface_first_and_filters_apply_before_limit(self):
        with self.db.conn:
            add_word(self.db, '食べました', '', 'noun', identifier='surface')
            for i in range(100):
                add_word(self.db, '食べる', '', 'noun', identifier=f'noun:{i}', common=1)
            add_word(self.db, '食べる', 'たべる', 'v1', identifier='chosen', source='chosen', target='cn')
            add_word(self.db, '食べる', '', 'verb', identifier='chinese', lang='cn')
        rows = self.db.search('食べました', limit=2)
        self.assertEqual(rows[0]['id'], 'surface')
        self.assertNotIn('_conjugation', rows[0])
        self.assertIn('_conjugation', rows[1])
        rows = self.db.search('食べました', limit=1, sources=('chosen',), directions=(('jp', 'cn'),))
        self.assertEqual([r['id'] for r in rows], ['chosen'])
        self.assertEqual(self.db.search('食べました', sources=()), [])
        self.assertEqual(self.db.search('食べました', directions=(('en', 'jp'),)), [])
        self.assertEqual(self.db.search('食べました', lang='cn'), [])
        self.assertEqual(self.db.search('食べました', lang='en'), [])

    def test_broad_wiktionary_pos_and_ambiguous_potential_passive(self):
        with self.db.conn:
            add_word(self.db, '寝る', 'ねる', 'verb')
            add_word(self.db, '美しい', 'うつくしい', 'adj')
        self.assertEqual(self.db.search('寝ました')[0]['headword'], '寝る')
        self.assertEqual(self.db.search('美しかった')[0]['headword'], '美しい')
        match = self.db.search('食べられる')[0]['_conjugation']
        self.assertIn('potential / passive', match['reasons'])

    def test_generation_is_bounded_and_does_not_process_english_or_sentences(self):
        for query in ('', 'eating', "'; DROP TABLE entries;--", '本を食べました。', 'あ' * 101):
            self.assertEqual(deinflect(query), [])
        self.assertLessEqual(len(deinflect('食べさせられたくなかったです')), MAX_CANDIDATES)
        self.assertTrue(self.db.search('食べました'))
        self.assertTrue(self.db.search('食べる'))


if __name__ == '__main__':
    unittest.main()
