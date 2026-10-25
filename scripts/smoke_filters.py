"""Check filters against full data and render the native desktop filter panel."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sanlex.db import Dictionary

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
home = Path('local-data')
db = Dictionary(home / 'dictionary.sqlite3')
db.initialize()
report = {}
for query, source, direction in [('学校', 'wiktionary-ja', ('jp','jp')),
                                  ('school', 'wiktionary-ja', ('en','jp')),
                                  ('学校', 'jmdict', ('jp','en'))]:
    start = time.perf_counter()
    results = db.search(query, sources=(source,), directions=(direction,))
    assert results, (query, source, direction)
    assert all(e['source'] == source and (e['lang'], e['definition_lang']) == direction for e in results)
    report[source + ':' + '>'.join(direction)] = {'results':len(results), 'seconds':round(time.perf_counter()-start, 3)}
print(json.dumps(report, indent=2))
db.close()

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from sanlex.ui import MainWindow
app = QApplication([])
window = MainWindow(home / 'dictionary.sqlite3')
window.show()
window.filter_panel.restore_selection(('wiktionary-ja',), (('jp','jp'),))
window.filter_panel.selection_changed()
window.set_query('学校')
end = time.monotonic() + 15
while window.workers and time.monotonic() < end:
    app.processEvents()
    QTest.qWait(10)
assert not window.workers
assert window.current_entry['source'] == 'wiktionary-ja'
assert window.current_entry['definition_lang'] == 'jp'
window.grab().save('test-output/filters.png')
window.reset_filters()
window.close()
app.processEvents()

# Include the covering index in the shipped snapshot as well, without reimporting data.
snapshot = Dictionary(Path('build/bundled-data/dictionary.sqlite3'))
snapshot.initialize()
snapshot.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
snapshot.close()
print('Full-data filters and native panel passed')
