import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sanlex.analysis_window import AnalysisWindow
from sanlex.db import Dictionary
from sanlex.stroke_widget import outline_path, partial_median
from sanlex.strokes import CharacterAnalysis, StrokeStore


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Dictionary(Path(self.directory.name)/'dictionary.sqlite3')
        self.db.initialize()
        with self.db.conn:
            for char,props in [('学',{'kTraditionalVariant':'U+5B78'}),
                               ('學',{'kSimplifiedVariant':'U+5B66'}),
                               ('发',{'kTraditionalVariant':'U+767C U+9AEE'})]:
                self.db.conn.execute('INSERT INTO characters(char,unihan) VALUES(?,?)',(char,json.dumps(props)))
            for identifier,lang,headword,forms in [
                ('cedict:school','cn','学校',['学校','學校']),
                ('jmdict:school','jp','学校',['学校']),
                ('native:simple','cn','学校',['学校']),
                ('native:traditional','cn','學校',['學校'])]:
                self.db.add_entry({'id':identifier,'lang':lang,'headword':headword,'reading':'',
                    'forms':forms,'glosses':['school'],'source':identifier.split(':')[0]})
        self.filters = {'sources':None,'directions':None}
        self.window = AnalysisWindow(self.db,lambda:self.filters)

    def tearDown(self):
        self.window.shutdown()
        self.db.close()
        self.app.processEvents()
        self.directory.cleanup()

    def test_region_specific_data_and_ambiguous_variants(self):
        model = self.window.model
        self.assertEqual(model.variants('学','hant'),['學'])
        self.assertEqual(model.variants('學','hans'),['学'])
        self.assertEqual(model.variants('发','hant'),['發','髮'])
        self.assertEqual(model.variants('学','ja'),['学'])
        graphics = [self.window.store.record('骨',mode)['graphics'] for mode in ('ja','hans','hant')]
        self.assertNotEqual(graphics[0],graphics[1])
        self.assertNotEqual(graphics[1],graphics[2])
        self.assertEqual(len(self.window.store.record('吾','ja')['graphics']['strokes']),7)
        # A missing traditional animation must never silently borrow the mainland one.
        self.assertIsNone(self.window.store.record('吾','hant'))

    def test_regional_components_and_parent_relationships(self):
        self.assertIn('弟',self.window.model.components('梯','ja'))
        for mode in ('ja','hans','hant'):
            self.assertIn('梯',[char for char,_ in self.window.model.parents('弟',mode)[0]])
        # An uncommon test parent exercises explicitly tagged IDS fallback.
        with self.db.conn:
            for expression in ('⿰木火[G]','⿰水火[T]','⿰土火[J]'):
                self.db.add_decomposition('𠀀',expression,'ids')
        for mode,component in [('hans','木'),('hant','水'),('ja','土')]:
            self.assertEqual(self.window.model.components('𠀀',mode),[component,'火'])
            self.assertIn('𠀀',[char for char,_ in self.window.model.parents(component,mode,limit=10000)[0]])
        self.assertNotIn('𠀀',[char for char,_ in self.window.model.parents('水','ja')[0]])

    def test_simplified_input_resolves_to_attested_japanese_variant(self):
        with self.db.conn:
            for char, props in [
                ('务', {'kTraditionalVariant': 'U+52D9'}),
                ('務', {'kSimplifiedVariant': 'U+52A1', 'kJapaneseOn': 'MU'}),
                ('将', {'kTraditionalVariant': 'U+5C07', 'kJapaneseOn': 'SHOU'}),
                ('军', {'kTraditionalVariant': 'U+8ECD'}),
            ]:
                self.db.conn.execute('INSERT INTO characters(char,unihan) VALUES(?,?)',
                                     (char, json.dumps(props)))
            self.db.add_entry({'id': 'jmdict:duty', 'lang': 'jp', 'headword': '勤務',
                               'reading': 'きんむ', 'glosses': ['duty'], 'source': 'jmdict'})
        model = self.window.model
        self.assertEqual(model.variants('务', 'ja'), ['務'])
        self.assertEqual(model.variants('務', 'hans'), ['务'])
        self.assertEqual(model.variants('務', 'ja'), ['務'])
        self.assertEqual(model.variants('将', 'ja'), ['将'])
        self.assertEqual(model.variants('军', 'ja'), ['軍'])
        self.assertEqual(model.variants('发', 'ja'), ['發', '髮'])
        self.window.show_character('务', 'hans')
        self.window.modes.setCurrentIndex(2)
        self.assertEqual((self.window.root_char, self.window.char, self.window.mode), ('务', '務', 'ja'))
        self.assertIn('From 务: Japanese form', self.window.variant_note.text())
        self.assertIn('On readings', self.window.info.toPlainText())
        self.assertIn('勤務', self.window.words.toPlainText())
        self.assertTrue(self.window.play.isEnabled())
        self.window.travel(-1)
        self.assertEqual((self.window.char, self.window.mode), ('务', 'hans'))
        self.window.travel(1)
        self.assertEqual((self.window.char, self.window.mode), ('務', 'ja'))

    def test_japanese_mapping_requires_regional_evidence_not_semantic_similarity(self):
        with self.db.conn:
            self.db.conn.execute('INSERT INTO characters(char,unihan) VALUES(?,?)',
                ('𠀀', json.dumps({'kTraditionalVariant': 'U+20001', 'kSemanticVariant': 'U+52D9'})))
        self.assertEqual(self.window.model.variants('𠀀', 'ja'), ['𠀀'])
        # Dictionary readings still resolve the variant without any animation pack.
        with tempfile.TemporaryDirectory() as directory:
            store = StrokeStore(Path(directory)/'absent.sqlite3')
            with self.db.conn:
                for char, props in [('务', {'kTraditionalVariant': 'U+52D9'}),
                                    ('務', {'kJapaneseOn': 'MU'})]:
                    self.db.conn.execute('INSERT INTO characters(char,unihan) VALUES(?,?)',
                                         (char, json.dumps(props)))
            self.assertEqual(CharacterAnalysis(self.db, store).variants('务', 'ja'), ['務'])
            store.close()

    def test_chinese_spellings_and_language_and_source_filters(self):
        model = self.window.model
        self.assertEqual({w['lang'] for w in model.words('校','ja')},{'jp'})
        simplified = model.words('校','hans')
        traditional = model.words('校','hant')
        self.assertTrue(simplified and traditional)
        self.assertEqual({w['display_word'] for w in simplified},{'学校'})
        self.assertEqual({w['display_word'] for w in traditional},{'學校'})
        self.assertEqual([w['display_word'] for w in model.words('學','hant',sources=('cedict',))],['學校'])
        self.assertEqual(model.words('學','hans'),[])
        self.assertEqual(model.words('校','ja',sources=('cedict',)),[])
        self.assertEqual(model.words('校','hant',directions=(('cn','jp'),)),[])

    def test_playback_steps_pause_slider_and_close(self):
        self.window.show_character('吾','ja')
        self.window.show()
        self.app.processEvents()
        canvas = self.window.canvas
        self.assertEqual(canvas.position,7)
        self.window.toggle_play()
        QTest.qWait(180)
        self.assertTrue(canvas.timer.isActive())
        self.assertGreater(canvas.position,0)
        self.assertLess(canvas.position,1)
        self.window.toggle_play()
        value = canvas.position
        QTest.qWait(40)
        self.assertEqual(canvas.position,value)
        canvas.step(1)
        self.assertEqual(canvas.position,1)
        self.window.progress.setValue(250)
        self.assertEqual(canvas.position,2.5)
        canvas.step(-1)
        self.assertEqual(canvas.position,2)
        canvas.play()
        self.window.close()
        self.assertFalse(canvas.timer.isActive())

    def test_missing_animation_and_missing_entire_data_pack(self):
        self.window.show_character('吾','hant')
        self.assertIn('No Traditional Chinese stroke animation',self.window.availability.text())
        self.assertFalse(self.window.play.isEnabled())
        self.assertIn('Parts',self.window.parts.toPlainText())
        with tempfile.TemporaryDirectory() as directory:
            store = StrokeStore(Path(directory)/'absent.sqlite3')
            self.assertIsNone(store.record('吾','ja'))
            self.assertEqual(store.parents('弟','ja'),[])
            store.close()

    def test_mode_navigation_and_word_links_are_offline(self):
        selected = []
        self.window.entry_requested.connect(selected.append)
        with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected network')):
            self.window.show_character('学','ja')
            self.window.modes.setCurrentIndex(1)
            self.assertEqual((self.window.char,self.window.mode),('學','hant'))
            self.window.handle_link(QUrl('char:弟'))
            self.assertEqual(self.window.char,'弟')
            self.window.travel(-1)
            self.assertEqual((self.window.root_char,self.window.char,self.window.mode),('学','學','hant'))
            self.window.travel(1)
            self.assertEqual(self.window.char,'弟')
            self.window.handle_link(QUrl('entry:jmdict%3Aschool'))
            self.assertEqual(selected,['jmdict:school'])
            self.window.show_character('发','hant')
            self.assertEqual(self.window.variants.count(),2)
            self.window.variants.setCurrentIndex(1)
            self.assertEqual(self.window.char,'髮')

    def test_paths_and_partial_strokes(self):
        path = outline_path('M0,0Q5,0 10,10C10,20 0,20 0,10Z')
        self.assertFalse(path.isEmpty())
        half = partial_median([[0,0],[10,0],[10,10]],0.75)
        self.assertEqual((half.currentPosition().x(),half.currentPosition().y()),(10,5))
        for mode in ('ja','hans','hant'):
            row = self.window.store.record('骨',mode)['graphics']
            self.assertEqual(len(row['strokes']),len(row['medians']))
            self.assertTrue(all(not outline_path(path).isEmpty() for path in row['strokes']))


if __name__=='__main__':
    unittest.main()
