"""AND component lookup, recursive graphs, paging and input validation."""
import json
from pathlib import Path
import tempfile
import unittest

from sanlex.db import Dictionary
from sanlex.text import parse_components


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Dictionary(Path(self.directory.name) / 'dictionary.sqlite3')
        self.db.initialize()
        with self.db.conn:
            for char, strokes, frequency in [('木', 4, None), ('目', 5, None), ('氵', 3, None),
                                              ('相', 9, 10), ('想', 13, 20), ('湘', 12, 30),
                                              ('林', 8, 40), ('森', 12, 50), ('沐', 7, 60)]:
                self.db.conn.execute('INSERT INTO characters VALUES(?,?,?)',
                                     (char, '{}', json.dumps({'strokes': [str(strokes)], 'frequency': frequency})))
            for char, expression in [('相', '⿰木目'), ('想', '⿱相心'), ('湘', '⿰氵相'),
                                     ('林', '⿰木木'), ('森', '⿱木林'), ('沐', '⿰氵木')]:
                self.db.add_decomposition(char, expression, 'test')

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def matches(self, parts, nested=True, limit=80):
        rows, more = self.db.find_by_components(parts, nested, limit)
        return [row['parent'] for row in rows], more

    def test_every_component_required_and_nested_toggle_changes_results(self):
        self.assertEqual(self.matches('木 + 目', False), (['相'], False))
        self.assertEqual(self.matches('木目'), (['相', '想', '湘'], False))
        self.assertEqual(self.matches('目木'), self.matches('木目'))
        self.assertEqual(self.matches('氵木', False), (['沐'], False))
        self.assertEqual(self.matches('氵木'), (['湘', '沐'], False))
        self.assertEqual(self.matches('木目火'), ([], False))
        self.assertEqual(self.matches('木林'), (['森'], False))

    def test_duplicate_components_and_sources_do_not_affect_intersection(self):
        with self.db.conn:
            self.db.add_decomposition('相', '⿰木目', 'another-source')
            self.db.add_decomposition('林', '⿰木木', 'another-source')
        self.assertEqual(self.matches('木木目'), self.matches('木目'))
        self.assertEqual(self.matches('⽊,目'), self.matches('木目'))

    def test_cycles_self_links_and_missing_character_metadata_are_safe(self):
        with self.db.conn:
            self.db.add_decomposition('甲', '⿰乙木', 'cycle')
            self.db.add_decomposition('乙', '⿰甲目', 'cycle')
            self.db.add_decomposition('木', '木', 'self')
        rows, _ = self.db.find_by_components('木目')
        self.assertTrue({'甲', '乙', '相', '想', '湘'}.issubset({r['parent'] for r in rows}))
        self.assertNotIn('甲', self.matches('甲')[0])
        self.assertNotIn('木', self.matches('木')[0])
        self.assertIsNone(next(r for r in rows if r['parent'] == '甲')['kanjidic'])

    def test_paging_follows_intersection_and_is_stable(self):
        self.assertEqual(self.matches('木目', limit=1), (['相'], True))
        self.assertEqual(self.matches('木目', limit=2), (['相', '想'], True))
        self.assertEqual(self.matches('木目', limit=3), (['相', '想', '湘'], False))
        self.assertEqual(self.matches('', limit=1), ([], False))
        self.assertEqual(self.matches('木', limit=0), ([], False))

    def test_catalog_uses_recorded_components_with_strokes_and_no_entities(self):
        with self.db.conn:
            self.db.add_decomposition('试', '⿰&CDP-1234;言', 'entity')
        catalog = {r['char']: r for r in self.db.component_catalog()}
        self.assertEqual(catalog['木']['strokes'], 4)
        self.assertEqual(catalog['木']['uses'], 4)
        self.assertIsNone(catalog['心']['strokes'])
        self.assertNotIn('&CDP-1234;', catalog)
        self.assertNotIn('试', catalog)

    def test_invalid_or_excessive_input_is_rejected_without_modifying_database(self):
        self.assertEqual(parse_components('木，目 + 木'), ['木', '目'])
        self.assertEqual(parse_components('水氵'), ['水', '氵'])
        for value in ('wood', "'; DROP TABLE components;--", '一二三四五六七八九'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.db.find_by_components(value)
        self.assertEqual(self.matches('木目'), (['相', '想', '湘'], False))

    def test_empty_install_and_read_only_search(self):
        empty = Dictionary(Path(self.directory.name) / 'empty.sqlite3')
        try:
            empty.initialize()
            self.assertEqual(empty.component_catalog(), [])
            self.assertEqual(empty.find_by_components('木目'), ([], False))
        finally:
            empty.close()
        readonly = Dictionary(self.db.path, read_only=True)
        try:
            self.assertEqual([r['parent'] for r in readonly.find_by_components('木目')[0]], ['相', '想', '湘'])
        finally:
            readonly.close()


if __name__ == '__main__':
    unittest.main()
