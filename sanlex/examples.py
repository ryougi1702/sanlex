"""Offline sentence corpus, literal-spelling lookup and dictionary usage examples."""
import bz2
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote

from .text import normalize

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sentences(id INTEGER PRIMARY KEY,lang TEXT,text TEXT,norm TEXT,author TEXT);
CREATE INDEX IF NOT EXISTS sentence_text ON sentences(lang,text);
CREATE VIRTUAL TABLE IF NOT EXISTS sentence_fts USING fts5(tokens);
CREATE TABLE IF NOT EXISTS sentence_links(sentence_id INTEGER,translation_id INTEGER,PRIMARY KEY(sentence_id,translation_id));
'''
LANGS = {'jpn':'jp','cmn':'cn','eng':'en'}
FILES = [f'per_language/{lang}/{lang}_sentences_detailed.tsv.bz2' for lang in LANGS] + [
    'per_language/jpn/jpn-eng_links.tsv.bz2', 'per_language/cmn/cmn-eng_links.tsv.bz2',
    'per_language/jpn/jpn-cmn_links.tsv.bz2']


def sentence_tokens(text):
    text = normalize(text)
    tokens = {'w'+word for word in re.findall(r'[a-z0-9]+',text)}
    def cjk(char):
        return ord(char)>127 and unicodedata.category(char).startswith('L')
    for i,char in enumerate(text):
        if cjk(char):
            tokens.add('u'+format(ord(char),'x'))
            if i+1<len(text) and cjk(text[i+1]):
                tokens.add('b'+format(ord(char),'x')+'x'+format(ord(text[i+1]),'x'))
    return tokens


def import_tatoeba(db,path,progress,cancel):
    from .importers import check_cancel
    manifest = json.loads(path.read_text(encoding='utf-8'))
    files = {name:path.parent/'tatoeba'/Path(name).name for name in FILES}
    if manifest.get('files') != FILES or any(not p.is_file() for p in files.values()):
        raise ValueError('The Tatoeba manifest needs its six source files in the adjacent tatoeba folder.')
    for name,file in files.items():
        check_cancel(cancel)
        expected=manifest.get('sha256',{}).get(name)
        if expected and hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
            raise ValueError('Tatoeba source checksum mismatch: '+file.name)
    # English is restricted to direct translations of Japanese or Mandarin.
    english_ids = set()
    db.conn.execute('DELETE FROM sentence_links')
    for name in FILES[3:]:
        check_cancel(cancel)
        progress('Reading translation links: '+Path(name).name)
        batch = []
        with bz2.open(files[name],'rt',encoding='utf-8') as stream:
            for i,line in enumerate(stream):
                if i%10000==0:
                    check_cancel(cancel)
                a,b = map(int,line.rstrip().split('\t'))
                batch.extend([(a,b),(b,a)])
                if '-eng_' in name:
                    english_ids.add(b)
                if len(batch)>=10000:
                    db.conn.executemany('INSERT OR IGNORE INTO sentence_links VALUES(?,?)',batch)
                    batch=[]
        db.conn.executemany('INSERT OR IGNORE INTO sentence_links VALUES(?,?)',batch)
    db.conn.execute('DELETE FROM sentence_fts')
    db.conn.execute('DELETE FROM sentences')
    count = 0
    for code in LANGS:
        name = f'per_language/{code}/{code}_sentences_detailed.tsv.bz2'
        progress('Indexing Tatoeba '+code.upper())
        batch,fts = [],[]
        with bz2.open(files[name],'rt',encoding='utf-8') as stream:
            for i,line in enumerate(stream):
                if i%10000==0:
                    check_cancel(cancel)
                    progress(f'Tatoeba {code.upper()}: {i:,} lines; {count:,} sentences indexed')
                fields=line.rstrip('\r\n').split('\t')
                if len(fields)<4:
                    continue
                identifier,language,text,author = fields[:4]
                if language!=code or not identifier.isdigit():
                    continue
                identifier=int(identifier)
                if code=='eng' and identifier not in english_ids or not text or len(text)>1000:
                    continue
                batch.append((identifier,LANGS[code],text,normalize(text),author if author!='\\N' else ''))
                fts.append((identifier,' '.join(sorted(sentence_tokens(text)))))
                count+=1
                if len(batch)>=2000:
                    db.conn.executemany('INSERT INTO sentences VALUES(?,?,?,?,?)',batch)
                    db.conn.executemany('INSERT INTO sentence_fts(rowid,tokens) VALUES(?,?)',fts)
                    batch,fts=[],[]
        db.conn.executemany('INSERT INTO sentences VALUES(?,?,?,?,?)',batch)
        db.conn.executemany('INSERT INTO sentence_fts(rowid,tokens) VALUES(?,?)',fts)
    if not count:
        raise ValueError('No Tatoeba sentences found')
    db.conn.execute('INSERT INTO sentence_fts(sentence_fts) VALUES(?)',('optimize',))
    return count


def attribution(db,identifier=None,text=None,lang=None):
    row = db.conn.execute('SELECT id,author FROM sentences WHERE id=?',(identifier,)).fetchone() if identifier else None
    if row is None and text and lang:
        row=db.conn.execute('SELECT id,author FROM sentences WHERE lang=? AND text=? LIMIT 1',(lang,text)).fetchone()
    return {'url':f'https://tatoeba.org/en/sentences/show/{row[0] if row else identifier}',
            'author':row[1] if row else ''} if row or identifier else {'url':'https://tatoeba.org','author':''}


def dictionary_examples(db,entry,limit=4,*,sources=None,directions=None):
    own,related,seen = [],[],set()
    candidates=[entry,*db.localized_definitions(entry,sources=sources,directions=directions)]
    for candidate in candidates:
        url = next((s['source_url'] for s in candidate['senses'] if s.get('source_url')), '')
        destination = own if candidate['id']==entry['id'] else related
        for number,sense in enumerate(candidate['senses'],1):
            for example in sense.get('examples',[]):
                text=example.get('text','')
                if not text or text in seen:
                    continue
                seen.add(text)
                result = {**example,'text':text,'source':candidate['source'], 'entry_id':candidate['id'],
                          'sense':'; '.join(sense['glosses'][:2]),'sense_number':number,'url':url,'translations':[]}
                if example.get('translation'):
                    translated={'lang':example.get('translation_lang',candidate['definition_lang']),
                                'text':example['translation']}
                    if example.get('tatoeba_id'):
                        translated.update(attribution(db,text=translated['text'],lang=translated['lang']))
                    result['translations'].append(translated)
                if example.get('tatoeba_id'):
                    result.update(attribution(db,example['tatoeba_id']))
                    result['source']='Tatoeba via JMdict'
                destination.append(result)
    return own[:limit],related[:limit],len(own)>limit or len(related)>limit


def corpus_examples(db,entry,limit=4,*,directions=None,exclude=()):
    spellings = list(dict.fromkeys([entry['headword'],*[f for f in entry['forms']
                    if f!=entry['reading'] and len(f)<=80]]))[:12]
    allowed = {target for origin,target in directions if origin==entry['lang']} if directions is not None else {'jp','cn','en'}
    if not allowed:
        return [],False
    results,seen = [],set(exclude)
    for spelling in spellings:
        term=normalize(spelling)
        tokens=sentence_tokens(term)
        if not tokens:
            continue
        expression=' AND '.join('"'+t+'"' for t in sorted(tokens))
        rows = db.conn.execute('SELECT s.* FROM sentence_fts CROSS JOIN sentences s ON s.id=sentence_fts.rowid '
            'WHERE sentence_fts MATCH ? AND s.lang=? AND instr(s.norm,?)>0 ORDER BY length(s.text),s.id LIMIT ?',
            (expression,entry['lang'],term,max(60,limit*5)))
        for row in rows:
            if row['text'] in seen:
                continue
            if entry['lang']=='en' and not re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',row['norm']):
                continue
            seen.add(row['text'])
            translations=[]
            for translated in db.conn.execute('SELECT s.* FROM sentence_links l JOIN sentences s ON s.id=l.translation_id '
                                              'WHERE l.sentence_id=? ORDER BY s.lang,length(s.text),s.id',(row['id'],)):
                if translated['lang'] not in allowed:
                    continue
                if sum(t['lang']==translated['lang'] for t in translations)>=2:
                    continue
                translations.append({'lang':translated['lang'],'text':translated['text'],
                                     **attribution(db,translated['id'])})
            results.append({'text':row['text'],'source':'Tatoeba','match':spelling,'translations':translations,
                            **attribution(db,row['id'])})
        if len(results)>limit:
            break
    results.sort(key=lambda r:(not bool(r['translations']),len(r['text'])))
    return results[:limit],len(results)>limit
