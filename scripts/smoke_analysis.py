"""Validate actual regional glyphs, full-data relationships and native rendering."""
from pathlib import Path
import json
import sys
import time
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from sanlex.db import Dictionary
from sanlex.analysis_window import AnalysisWindow
from sanlex.stroke_widget import outline_path
from sanlex.ui import STYLE

sys.stdout.reconfigure(encoding='utf-8')
app = QApplication([])
db = Dictionary(Path('local-data/dictionary.sqlite3'))
db.initialize()
old_mode = db.preference('character-analysis-mode','ja')
window = AnalysisWindow(db,lambda:{'sources':None,'directions':None})
window.setStyleSheet(STYLE)
window.show()
report = {}
for mode in ('ja','hans','hant'):
    start = time.perf_counter()
    window.show_character('弟',mode)
    assert window.canvas.paths
    assert '梯' in window.part_of.toPlainText()
    words = window.model.words('弟',mode)
    assert words and all(w['lang']==('jp' if mode=='ja' else 'cn') for w in words)
    report[mode]={'seconds':round(time.perf_counter()-start,3),'strokes':len(window.canvas.paths),'words':len(words)}
    window.details.setCurrentIndex(0)
    app.processEvents()
    window.grab().save(f'test-output/analysis-{mode}.png')
window.show_character('吾','ja')
assert len(window.canvas.paths)==7
window.details.setCurrentIndex(1)
app.processEvents()
window.grab().save('test-output/analysis-japanese-words.png')
window.canvas.set_position(0.1)
app.processEvents()
frame_a = window.canvas.grab().toImage()
window.canvas.set_position(0.8)
app.processEvents()
assert frame_a != window.canvas.grab().toImage(), 'Stroke must progressively reveal'
window.canvas.set_position(3.5)
app.processEvents()
window.grab().save('test-output/analysis-playing.png')
window.canvas.play()
before = window.canvas.position
QTest.qWait(200)
assert window.canvas.position>before
window.hide()
assert not window.canvas.timer.isActive()
total = 0
for mode,char,compressed in window.store.conn.execute('SELECT mode,char,graphics FROM glyphs'):
    row=json.loads(zlib.decompress(compressed))
    assert len(row['strokes'])==len(row['medians']),(mode,char)
    assert row['strokes'] and all(not outline_path(path).isEmpty() for path in row['strokes']),(mode,char)
    total+=1
report['validated_glyphs']=total
print(json.dumps(report,ensure_ascii=False,indent=2))
window.shutdown()
db.set_preference('character-analysis-mode',old_mode)
db.close()
