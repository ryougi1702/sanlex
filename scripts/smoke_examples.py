"""Validate and render real offline examples in Japanese, Chinese and English."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from sanlex.ui import MainWindow
from sanlex.examples import dictionary_examples,corpus_examples

sys.stdout.reconfigure(encoding='utf-8')
app=QApplication([])
window=MainWindow(Path('local-data/dictionary.sqlite3'))
window.show()
window.reset_filters()
end=time.monotonic()+20
while window.workers and time.monotonic()<end:
    app.processEvents();QTest.qWait(10)
assert not window.workers
report={}
with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected network lookup')):
    for term,language in [('学校','jp'),('学校','cn'),('school','en')]:
        entry=next(e for e in window.db.search(term,language) if e['headword']==term)
        start=time.perf_counter()
        window.show_entry(entry['id'])
        text=window.word_view.toPlainText()
        assert 'Example sentences' in text and 'Sentences containing this spelling' in text
        assert 'View source sentence / attribution' in text
        own,related,_=dictionary_examples(window.db,entry)
        corpus,_=corpus_examples(window.db,entry)
        report[language]={'own':len(own),'related':len(related),'corpus':len(corpus),'render_seconds':round(time.perf_counter()-start,3)}
        if language=='jp':
            assert own and own[0]['translations']
            assert 'Tatoeba via JMdict' in text
        window.word_view.verticalScrollBar().setValue(0)
        app.processEvents()
        window.grab().save(f'test-output/examples-{language}.png')
        cursor=window.word_view.document().find('Example sentences')
        window.word_view.setTextCursor(cursor)
        window.word_view.ensureCursorVisible()
        scroll=window.word_view.verticalScrollBar()
        scroll.setValue(scroll.value()+window.word_view.cursorRect(cursor).top()-25)
        app.processEvents()
        window.grab().save(f'test-output/examples-{language}-detail.png')
counts=[tuple(row) for row in window.db.conn.execute('SELECT lang,count(*) FROM sentences GROUP BY lang')]
report['sentences']=counts
report['jmdict_entries_with_examples']=window.db.conn.execute("SELECT count(*) FROM entries WHERE source='jmdict' AND senses LIKE '%\"tatoeba_id\"%'").fetchone()[0]
print(json.dumps(report,ensure_ascii=False,indent=2))
window.close()
app.processEvents()
