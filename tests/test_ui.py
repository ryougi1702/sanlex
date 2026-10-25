import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QUrl, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sanlex.ui import MainWindow
from sanlex.db import Dictionary
from sample_data import populate


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / 'dictionary.sqlite3'
        db = Dictionary(path)
        db.initialize()
        populate(db)
        db.close()
        self.window = MainWindow(path)
        self.window.show()
        self.wait_search()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def wait_search(self):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            self.app.processEvents()
            if not self.window.workers and not self.window.timer.isActive():
                return
            QTest.qWait(10)
        self.fail('Search did not finish in 8 seconds')

    def type_suggestion(self,query):
        self.window.activateWindow()
        self.window.search_input.setFocus()
        self.window.search_input.selectAll()
        QTest.keyClicks(self.window.search_input,query)
        end=time.monotonic()+5
        while time.monotonic()<end:
            self.app.processEvents()
            if not self.window.autocomplete.workers and not self.window.autocomplete.timer.isActive():
                return
            QTest.qWait(10)
        self.fail('Suggestions did not finish')

    def test_autocomplete_keyboard_selection_is_lightweight_and_opens_selected_entry(self):
        auto=self.window.autocomplete
        before=self.window.current_entry['id']
        history=list(self.window.db.history())
        self.type_suggestion('gakk')
        self.assertTrue(auto.completer.popup().isVisible())
        self.assertGreater(auto.model.rowCount(),0)
        self.assertEqual(self.window.current_entry['id'],before)
        self.assertEqual(self.window.db.history(),history)
        self.assertFalse(self.window.workers)
        QTest.keyClick(self.window.search_input,Qt.Key.Key_Down)
        QTest.keyClick(self.window.search_input,Qt.Key.Key_Return)
        self.wait_search()
        self.assertEqual(self.window.search_input.text(),'学校')
        self.assertEqual(self.window.current_entry['lang'],'jp')
        self.assertFalse(auto.completer.popup().isVisible())

    def test_autocomplete_mouse_escape_stale_results_and_ime(self):
        from sanlex.autocomplete import ROW_ROLE
        auto=self.window.autocomplete
        self.type_suggestion('xuex')
        popup=auto.completer.popup()
        self.assertTrue(popup.isVisible())
        index=popup.model().index(0,0)
        chosen=index.data(ROW_ROLE)
        QTest.mouseClick(popup.viewport(),Qt.MouseButton.LeftButton,pos=popup.visualRect(index).center())
        self.wait_search()
        self.assertEqual(self.window.current_entry['id'],chosen['id'])
        self.type_suggestion('gakk')
        generation=auto.generation
        rows=[auto.model.item(0).data(ROW_ROLE)]
        QTest.keyClick(self.window.search_input,Qt.Key.Key_Escape)
        auto.receive(generation,rows)
        self.assertFalse(popup.isVisible())
        event=QInputMethodEvent('がっ',[])
        self.app.sendEvent(self.window.search_input,event)
        self.assertTrue(auto.composing)
        self.assertFalse(auto.timer.isActive())
        self.assertFalse(popup.isVisible())
        end=QInputMethodEvent('',[])
        self.app.sendEvent(self.window.search_input,end)

    def test_autocomplete_filter_change_and_enter_without_selection(self):
        auto=self.window.autocomplete
        self.window.language.setCurrentIndex(2)
        self.wait_search()
        self.type_suggestion('xue')
        from sanlex.autocomplete import ROW_ROLE
        self.assertTrue(all(auto.model.item(i).data(ROW_ROLE)['lang']=='cn' for i in range(auto.model.rowCount())))
        self.window.filter_panel.select_group('sources',False)
        self.wait_search()
        self.assertFalse(auto.completer.popup().isVisible())
        self.window.reset_filters()
        self.wait_search()
        self.type_suggestion('school')
        QTest.keyClick(self.window.search_input,Qt.Key.Key_Escape)
        QTest.keyClick(self.window.search_input,Qt.Key.Key_Return)
        self.wait_search()
        self.assertEqual(self.window.search_input.text(),'school')
        self.assertGreater(self.window.results.count(),0)

    def test_initial_search_and_character_link(self):
        self.assertNotIn('starter', self.window.filter_panel.source_checks)
        self.assertEqual(self.window.search_input.text(), '学校')
        self.assertGreater(self.window.results.count(), 0)
        self.assertIn('English definitions', self.window.word_view.toPlainText())
        # Click the second character of the large headword, not the separate atlas links.
        heading = self.window.word_view.document().find('学校')
        heading.setPosition(heading.selectionStart()+1)
        target = self.window.word_view.cursorRect(heading).center()+QPoint(8,0)
        self.assertTrue(self.window.word_view.anchorAt(target).startswith('analyse:'))
        QTest.mouseClick(self.window.word_view.viewport(),Qt.MouseButton.LeftButton,pos=target)
        self.app.processEvents()
        self.assertEqual(self.window.analysis_window.char,'校')
        self.assertEqual(self.window.tabs.currentIndex(),0)
        self.window.handle_link(QUrl('char:%E5%BC%9F'))
        self.assertTrue(self.window.analysis_window.isVisible())
        self.assertEqual(self.window.analysis_window.char,'弟')
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertIn('梯', self.window.char_view.toPlainText())
        self.assertIn('Part of', self.window.char_view.toPlainText())

    def test_save_history_and_stale_search(self):
        self.window.save_current()
        self.window.show_saved()
        self.assertEqual(self.window.results.count(), 1)
        self.window.set_query('water')
        self.window.set_query('cat')
        self.wait_search()
        self.assertIn('cat', self.window.result_label.text())
        self.assertNotIn('water', self.window.result_label.text())
        self.window.show_history()
        self.assertGreaterEqual(self.window.results.count(), 3)

    def test_empty_search_and_language_filter(self):
        self.window.language.setCurrentIndex(1)
        self.window.set_query('school')
        self.wait_search()
        for i in range(self.window.results.count()):
            entry_id = self.window.results.item(i).data(Qt.ItemDataRole.UserRole)[1]
            self.assertEqual(self.window.db.entry(entry_id)['lang'], 'jp')
        self.window.search_input.clear()
        self.wait_search()
        self.assertEqual(self.window.results.count(), 0)
        self.assertFalse(self.window.save_button.isEnabled())

    def test_sources_dialog_and_minimum_size(self):
        self.window.resize(1020, 690)
        self.window.open_data()
        self.app.processEvents()
        self.assertEqual(len(self.window.data_dialog.checks), 8)
        self.assertFalse(self.window.data_dialog.install.isEnabled())
        self.window.data_dialog.checks['jmdict'].setChecked(True)
        self.assertTrue(self.window.data_dialog.install.isEnabled())
        self.window.data_dialog.close()

    def test_analysis_word_links_filters_and_reopening(self):
        self.window.open_character_analysis('校','ja')
        analysis = self.window.analysis_window
        self.assertTrue(analysis.isVisible())
        self.assertIn('学校',analysis.words.toPlainText())
        self.window.filter_panel.select_group('sources',False)
        self.wait_search()
        self.assertIn('No matching words',analysis.words.toPlainText())
        self.window.reset_filters()
        self.wait_search()
        self.assertIn('学校',analysis.words.toPlainText())
        analysis.handle_link(QUrl('entry:fixture%3Aschool%3Ajp'))
        self.assertEqual(self.window.current_entry['id'],'fixture:school:jp')
        self.assertEqual(self.window.tabs.currentIndex(),0)
        analysis.canvas.play()
        analysis.close()
        self.assertFalse(analysis.canvas.timer.isActive())
        self.window.open_character_analysis('弟','hant')
        self.assertIs(self.window.analysis_window,analysis)
        self.assertEqual((analysis.char,analysis.mode),('弟','hant'))

    def test_offline_corpus_toggle_paging_and_navigation(self):
        from sanlex.examples import sentence_tokens
        db=self.window.db
        with db.conn:
            for index in range(7):
                identifier=1000+index
                text=f'学校に行く。{index}'
                db.conn.execute('INSERT INTO sentences VALUES(?,?,?,?,?)',(identifier,'jp',text,text,'JapaneseAuthor'))
                db.conn.execute('INSERT INTO sentence_fts(rowid,tokens) VALUES(?,?)',(identifier,' '.join(sentence_tokens(text))))
            db.set_source('tatoeba',{'entries':7})
        self.window.refresh_library()
        self.assertTrue(self.window.filter_panel.corpus_check.isChecked())
        with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected network')):
            self.window.show_entry('fixture:school:jp')
            self.assertIn('Sentences containing this spelling',self.window.word_view.toPlainText())
            self.assertIn('JapaneseAuthor',self.window.word_view.toPlainText())
            self.assertIn('Show more examples',self.window.word_view.toPlainText())
            self.window.handle_link(QUrl('examplesmore:fixture%3Aschool%3Ajp'))
            self.assertNotIn('Show more examples',self.window.word_view.toPlainText())
            self.window.filter_panel.corpus_check.setChecked(False)
            self.wait_search()
            self.assertNotIn('Sentences containing this spelling',self.window.word_view.toPlainText())
            self.window.go_back()
            self.app.processEvents()
            self.assertTrue(self.window.filter_panel.corpus_check.isChecked())
            self.assertIn('JapaneseAuthor',self.window.word_view.toPlainText())

    def test_sources_distinguish_installed_data_from_cached_downloads_without_network(self):
        with self.window.db.conn:
            self.window.db.set_source('jmdict', {'entries': 123, 'name': 'JMdict'})
        cache = self.window.db.path.parent / 'downloads'
        cache.mkdir()
        (cache / 'JMdict_e_examp.gz').write_bytes(b'cached source fixture')
        with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network access')):
            self.window.set_query('school')
            self.wait_search()
            self.window.open_data()
            dialog = self.window.data_dialog
            self.assertIn('1 of 8 sources installed', dialog.library_summary.text())
            self.assertIn('INSTALLED · Ready offline · 123 records', dialog.source_labels['jmdict'].text())
            self.assertIn('NOT INSTALLED', dialog.source_labels['cedict'].text())
            self.assertIn('JMdict_e_examp.gz', dialog.cache_labels['jmdict'].text())
            self.assertIn('Cached download: none', dialog.cache_labels['cedict'].text())
            self.assertIn('No online lookup', dialog.offline_explanation.text())
            self.assertTrue(self.window.results.count())
            self.assertFalse(any(check.isChecked() for check in dialog.checks.values()))
            dialog.close()

    def test_search_paging_reaches_beyond_first_eighty(self):
        with self.window.db.conn:
            for i in range(95):
                self.window.db.add_entry({'id':f'test:{i}', 'headword':f'word{i}', 'reading':'',
                                          'lang':'en', 'glosses':['water'], 'source':'test'})
        self.window.refresh_library()
        self.window.set_query('water')
        self.wait_search()
        self.assertEqual(self.window.results.count(), 80)
        self.assertTrue(self.window.more_button.isVisible())
        self.window.load_more_results()
        self.wait_search()
        self.assertGreater(self.window.results.count(), 95)
        self.assertFalse(self.window.more_button.isVisible())

    def test_back_and_forward_from_source_link_restore_scroll(self):
        window = self.window
        origin = window.current_entry['id']
        with window.db.conn:
            window.db.add_entry({'id': 'test:school-source', 'headword': '学校', 'lang': 'jp',
                                 'reading': 'がっこう', 'definition_lang': 'jp', 'source': 'test',
                                 'glosses': [f'学校の説明 {i}' for i in range(35)],
                                 'senses': [{'glosses': [f'学校の説明 {i}']} for i in range(35)]})
        window.refresh_library()
        window.show_entry(origin)
        self.app.processEvents()
        self.assertIn('Full source entry', window.word_view.toPlainText())
        origin_scroll = window.word_view.verticalScrollBar()
        self.assertGreater(origin_scroll.maximum(), 0)
        origin_scroll.setValue(origin_scroll.maximum())
        position = origin_scroll.value()
        window.handle_link(QUrl('entry:test%3Aschool-source'))
        self.assertEqual(window.current_entry['id'], 'test:school-source')
        self.assertTrue(window.back_button.isEnabled())
        self.assertFalse(window.forward_button.isEnabled())
        target_scroll = window.word_view.verticalScrollBar()
        target_scroll.setValue(min(250, target_scroll.maximum()))
        target_position = target_scroll.value()
        QTest.mouseClick(window.back_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(window.current_entry['id'], origin)
        self.assertEqual(window.word_view.verticalScrollBar().value(), position)
        QTest.mouseClick(window.forward_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(window.current_entry['id'], 'test:school-source')
        self.assertEqual(window.word_view.verticalScrollBar().value(), target_position)
        self.assertFalse(window.forward_button.isEnabled())

    def test_back_across_character_and_entry_links_restores_explorer_options(self):
        window = self.window
        window.handle_link(QUrl('char:弟'))
        window.recursive.setChecked(False)
        window.part_limit = 400
        window.show_character('弟')
        self.app.processEvents()
        window.char_view.verticalScrollBar().setValue(window.char_view.verticalScrollBar().maximum())
        position = window.char_view.verticalScrollBar().value()
        window.handle_link(QUrl('char:梯'))
        window.handle_link(QUrl('entry:fixture%3Aladder%3Ajp'))
        self.assertEqual(window.tabs.currentIndex(), 0)
        window.go_back()
        self.app.processEvents()
        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.current_char, '梯')
        window.go_back()
        self.app.processEvents()
        self.assertEqual(window.current_char, '弟')
        self.assertFalse(window.recursive.isChecked())
        self.assertEqual(window.part_limit, 400)
        self.assertEqual(window.char_view.verticalScrollBar().value(), position)
        window.go_forward()
        self.app.processEvents()
        self.assertEqual(window.current_char, '梯')

    def test_new_link_after_back_discards_forward_path_and_same_page_is_not_duplicated(self):
        window = self.window
        origin = window.current_entry['id']
        window.show_entry('fixture:water:jp')
        window.show_entry('fixture:cat:jp')
        window.go_back()
        self.assertTrue(window.forward_button.isEnabled())
        window.show_entry('fixture:tree:jp')
        self.assertFalse(window.forward_button.isEnabled())
        size = len(window._navigation_history)
        window.show_entry('fixture:tree:jp')
        self.assertEqual(len(window._navigation_history), size)
        window.go_back()
        self.assertEqual(window.current_entry['id'], 'fixture:water:jp')
        window.go_back()
        self.assertEqual(window.current_entry['id'], origin)
        self.assertFalse(window.back_button.isEnabled())

    def test_back_restores_search_context_and_rejects_pending_search_results(self):
        window = self.window
        window.language.setCurrentIndex(1)
        window.set_query('water')
        self.wait_search()
        water_id = window.current_entry['id']
        rows = window.results.count()
        window.handle_link(QUrl('lookup:cat'))
        self.wait_search()
        cat_id = window.current_entry['id']
        window.set_query('tree')
        window.go_back()
        self.wait_search()
        self.assertEqual(window.search_input.text(), 'water')
        self.assertEqual(window.language.currentData(), 'jp')
        self.assertEqual(window.current_entry['id'], water_id)
        self.assertEqual(window.results.count(), rows)
        self.assertIn('water', window.result_label.text())
        window.go_forward()
        self.app.processEvents()
        self.assertEqual(window.search_input.text(), 'cat')
        self.assertEqual(window.current_entry['id'], cat_id)

    def test_keyboard_shortcuts_and_reopening_selected_search_result(self):
        window = self.window
        origin = window.current_entry['id']
        window.show_entry('fixture:water:jp')
        self.app.setActiveWindow(window)
        window.search_input.setFocus()
        QTest.keyClick(window.search_input, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertEqual(window.current_entry['id'], origin)
        QTest.keyClick(window.search_input, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertEqual(window.current_entry['id'], 'fixture:water:jp')
        window.activate_result(window.results.currentItem())
        self.assertEqual(window.current_entry['id'], origin)
        self.assertFalse(window.forward_button.isEnabled())

    def add_filter_entries(self):
        with self.window.db.conn:
            for source in ('file-a', 'file-b'):
                for origin, target in (('en', 'jp'), ('jp', 'jp'), ('jp', 'en'), ('cn', 'cn')):
                    self.window.db.add_entry({'id': f'{source}:{origin}:{target}',
                        'headword': f'filterprobe-{source}-{origin}-{target}', 'reading': '',
                        'lang': origin, 'definition_lang': target, 'glosses': ['filterprobe'], 'source': source})
        self.window.refresh_library()

    def test_source_and_direction_filters_combine_and_reset(self):
        self.add_filter_entries()
        panel = self.window.filter_panel
        panel.restore_selection(('file-a',), (('en', 'jp'), ('jp', 'jp')))
        panel.selection_changed()
        self.window.set_query('filterprobe')
        self.wait_search()
        results = [self.window.db.entry(self.window.results.item(i).data(Qt.ItemDataRole.UserRole)[1])
                   for i in range(self.window.results.count())]
        self.assertEqual(len(results), 2)
        self.assertEqual({e['source'] for e in results}, {'file-a'})
        self.assertEqual({(e['lang'], e['definition_lang']) for e in results}, {('en','jp'), ('jp','jp')})
        panel.select_group('sources', False)
        self.wait_search()
        self.assertEqual(self.window.results.count(), 0)
        self.assertIn('Reset all filters', self.window.word_view.toPlainText())
        self.window.reset_filters()
        self.wait_search()
        self.assertEqual(self.window.results.count(), 8)
        panel.select_group('directions', False)
        self.wait_search()
        self.assertEqual(self.window.results.count(), 0)

    def test_back_forward_restore_filters_and_saved_preferences(self):
        self.add_filter_entries()
        window = self.window
        panel = window.filter_panel
        window.set_query('filterprobe')
        self.wait_search()
        panel.restore_selection(('file-a',), (('jp','jp'),))
        panel.selection_changed()
        self.wait_search()
        first_id = window.current_entry['id']
        panel.restore_selection(('file-b',), (('en','jp'),))
        panel.selection_changed()
        self.wait_search()
        window.go_back()
        self.app.processEvents()
        self.assertEqual(panel.selected_sources(), ('file-a',))
        self.assertEqual(panel.selected_directions(), (('jp','jp'),))
        self.assertEqual(window.current_entry['id'], first_id)
        window.go_forward()
        self.app.processEvents()
        self.assertEqual(panel.selected_sources(), ('file-b',))
        self.assertEqual(panel.selected_directions(), (('en','jp'),))
        self.assertEqual(window.db.preference('word-filters')['sources']['file-b'], True)
        other = MainWindow(window.db.path)
        try:
            self.assertEqual(other.filter_panel.selected_sources(), ('file-b',))
            self.assertEqual(other.filter_panel.selected_directions(), (('en','jp'),))
        finally:
            other.close()
        self.window.toggle_filters()
        self.assertTrue(self.window.filter_dock.isHidden())
        self.window.toggle_filters()
        self.assertFalse(self.window.filter_dock.isHidden())

    def test_search_paging_keeps_source_and_direction_filters(self):
        with self.window.db.conn:
            for source in ('file-a', 'file-b'):
                for i in range(95):
                    self.window.db.add_entry({'id': f'{source}:{i}', 'headword':f'filterprobe-{source}-{i}',
                        'reading':'', 'lang':'jp', 'definition_lang':'en', 'glosses':['filterprobe'], 'source':source})
        self.window.refresh_library()
        self.window.filter_panel.restore_selection(('file-b',), (('jp','en'),))
        self.window.filter_panel.selection_changed()
        self.window.set_query('filterprobe')
        self.wait_search()
        self.assertEqual(self.window.results.count(), 80)
        self.window.load_more_results()
        self.wait_search()
        self.assertEqual(self.window.results.count(), 95)
        for i in range(self.window.results.count()):
            entry = self.window.db.entry(self.window.results.item(i).data(Qt.ItemDataRole.UserRole)[1])
            self.assertEqual(entry['source'], 'file-b')

    def test_saved_words_and_csv_follow_filters(self):
        self.add_filter_entries()
        for identifier in ('file-a:jp:jp', 'file-b:en:jp'):
            self.window.db.toggle_favorite(identifier)
        self.window.filter_panel.restore_selection(('file-a',), (('jp','jp'),))
        self.window.filter_panel.selection_changed()
        self.wait_search()
        self.window.show_saved()
        self.assertEqual(self.window.results.count(), 1)
        path = Path(self.directory.name) / 'filtered.csv'
        with patch('sanlex.ui.QFileDialog.getSaveFileName', return_value=(str(path), 'CSV (*.csv)')):
            self.window.export_saved()
        content = path.read_text(encoding='utf-8-sig')
        self.assertIn('file-a:jp:jp', content)
        self.assertNotIn('file-b:en:jp', content)

    def test_navigation_restores_filter_panel_visibility(self):
        self.window.toggle_filters()
        self.assertTrue(self.window.filter_dock.isHidden())
        self.window.show_entry('fixture:water:jp')
        self.window.go_back()
        self.app.processEvents()
        self.assertTrue(self.window.filter_dock.isHidden())
        self.window.go_forward()
        self.window.toggle_filters()
        self.window.show_entry('fixture:cat:jp')
        self.window.go_back()
        self.app.processEvents()
        self.assertFalse(self.window.filter_dock.isHidden())


if __name__ == '__main__':
    unittest.main()
