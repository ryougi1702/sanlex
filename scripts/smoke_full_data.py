"""Validate the real indexed dictionaries and render the three main GUI views."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sanlex.db import Dictionary

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
home = Path(sys.argv[1] if len(sys.argv) > 1 else 'local-data')
output = Path('test-output')
output.mkdir(exist_ok=True)
db = Dictionary(home / 'dictionary.sqlite3')
db.initialize()
assert db.conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
counts = db.counts()
assert counts['jp'] > 200000 and counts['cn'] > 100000 and counts['characters'] > 90000
assert len(db.sources()) == 8
assert 'starter' not in db.sources()
assert any(p['parent'] == '梯' for p in db.part_of('弟', False)[0])
assert any(p['parent'] == '森' for p in db.part_of('木', True)[0])
queries = {}
for query in ('学校', 'がっこう', 'ガッコウ', 'gakkou', 'xue2 xiao4', 'xuexiao', 'dictionary', '保护', '梯', 'lǜ'):
    start = time.perf_counter()
    entries = db.search(query)
    assert entries, query
    queries[query] = {'count': len(entries), 'seconds': round(time.perf_counter()-start, 3)}
school = db.entry('jmdict:1206730')
localized = db.localized_definitions(school)
assert {e['definition_lang'] for e in localized} == {'jp', 'cn'}
links = db.conn.execute('SELECT count(*) FROM lexical_links').fetchone()[0]
assert links > 10000
report = {'counts': counts, 'translation_links': links, 'queries': queries, 'database_check': 'ok'}
(output / 'full-data-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
db.close()

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from sanlex.ui import MainWindow
app = QApplication([])
window = MainWindow(home / 'dictionary.sqlite3')
window.show()
end = time.monotonic() + 30
while time.monotonic() < end:
    app.processEvents()
    if not window.workers:
        break
    QTest.qWait(20)
assert not window.workers
window.show_entry('jmdict:1206730')
assert 'Japanese 日本語 definitions' in window.word_view.toPlainText()
assert 'Chinese 中文 definitions' in window.word_view.toPlainText()
window.grab().save(str(output / 'dictionary.png'))
window.show_character('弟')
app.processEvents()
assert '梯' in window.char_view.toPlainText()
window.char_view.find('Part of')
window.char_view.verticalScrollBar().setValue(window.char_view.verticalScrollBar().value() + 220)
window.grab().save(str(output / 'character.png'))
window.open_data()
app.processEvents()
window.data_dialog.grab().save(str(output / 'sources.png'))
window.data_dialog.close()
window.close()
app.processEvents()
