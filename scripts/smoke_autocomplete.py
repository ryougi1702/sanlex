"""Check autocomplete on the full local snapshot and capture its native popup."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from sanlex.db import Dictionary
from sanlex.ui import MainWindow

sys.stdout.reconfigure(encoding='utf-8')
output=Path('test-output')
output.mkdir(exist_ok=True)
db=Dictionary(Path('local-data/dictionary.sqlite3'),read_only=True)
report={}
for term,language,filters in [
    ('a','all',{}),('s','all',{}),('x','all',{}),
    ('学','jp',{}),('がっこ','jp',{}),('ガッコ','jp',{}),('gakk','jp',{}),
    ('xue2 x','cn',{}),('xué xi','cn',{}),('學','cn',{}),('scho','en',{}),
    ('a','jp',{'sources':['jmdict'],'directions':[('jp','en')]}),
    ('a','en',{'sources':['wiktionary-zh'],'directions':[('en','cn')]}),
]:
    start=time.perf_counter()
    deadline=time.monotonic()+0.18
    db.conn.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    rows=db.autocomplete(term,language,**filters)
    report[f'{term}:{language}:{filters}']={
        'ms':round((time.perf_counter()-start)*1000,1),
        'count':len(rows),'first':[row['headword'] for row in rows[:3]]}
db.close()
app=QApplication([])
window=MainWindow(Path('local-data/dictionary.sqlite3'))
window.show()
window.activateWindow()
window.reset_filters()

def settle():
    end=time.monotonic()+20
    while (window.workers or window.timer.isActive() or window.autocomplete.workers
           or window.autocomplete.timer.isActive()) and time.monotonic()<end:
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()
    assert not window.workers and not window.autocomplete.workers

settle()
with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected network lookup')):
    window.search_input.setFocus()
    window.search_input.selectAll()
    QTest.keyClicks(window.search_input,'gakk')
    app.processEvents()
    settle()
    popup=window.autocomplete.completer.popup()
    assert popup.isVisible() and popup.model().rowCount()>0
    report['popup']={'rows':popup.model().rowCount(),'width':popup.width(),'height':popup.height()}
    window.grab().save(str(output/'autocomplete-main.png'))
    popup.grab().save(str(output/'autocomplete-popup.png'))
    QTest.keyClick(window.search_input,Qt.Key.Key_Down)
    QTest.keyClick(window.search_input,Qt.Key.Key_Return)
    settle()
    assert window.current_entry['lang']=='jp'
    report['selected']=window.current_entry['headword']
    window.grab().save(str(output/'autocomplete-selected.png'))
window.close()
app.processEvents()
print(json.dumps(report,ensure_ascii=False,indent=2))
