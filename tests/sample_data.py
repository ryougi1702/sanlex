"""Small isolated fixtures, never loaded by the application."""
import json
from pathlib import Path


def populate(db):
    data = json.loads((Path(__file__).parent / 'fixtures/words.json').read_text(encoding='utf-8'))
    with db.conn:
        for item in data['concepts']:
            for lang in ('jp', 'cn'):
                word = item[lang]
                db.add_entry({'id': f"fixture:{item['id']}:{lang}", 'lang': lang,
                              'headword': word[0], 'reading': word[1], 'forms': word[2:],
                              'glosses': [item['en']], 'source': 'fixture', 'common': 1})
        for char, props in data['characters'].items():
            db.conn.execute('INSERT INTO characters(char,unihan,kanjidic) VALUES(?,?,?)',
                            (char,json.dumps(props.get('unihan',{})),json.dumps(props.get('kanjidic',{}))))
            if props.get('ids'):
                db.add_decomposition(char, props['ids'], 'fixture')
        db.set_source('fixture', {'entries': len(data['concepts']) * 2})
