"""Build the bundled regional character data from a pinned AnimCJK revision.

Original source files and licences are retained alongside the derived SQLite file.
Run this explicitly during development; the application never downloads strokes.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
REVISION = '3e1253b341cc7be14c3540bb3c045e6163557777'
BASE = f'https://raw.githubusercontent.com/parsimonhi/animCJK/{REVISION}/'
MODES = {'ja': 'Ja', 'hans': 'ZhHans', 'hant': 'ZhHant'}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    target = ROOT / 'assets' / 'strokes'
    originals = target / 'originals'
    originals.mkdir(parents=True, exist_ok=True)
    names = [prefix + suffix + '.txt' for suffix in MODES.values()
             for prefix in ('graphics', 'dictionary')]

    def fetch(name):
        path = originals / name
        if not path.exists():
            with urllib.request.urlopen(BASE + name, timeout=120) as response:
                content = response.read()
            path.write_bytes(content)
        return name, hashlib.sha256(path.read_bytes()).hexdigest()

    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = dict(pool.map(fetch, names))
    conn = sqlite3.connect(str(target / 'characters.sqlite3'))
    conn.executescript('''CREATE TABLE IF NOT EXISTS glyphs(
        mode TEXT, char TEXT, graphics BLOB, metadata TEXT, PRIMARY KEY(mode,char));
        CREATE TABLE IF NOT EXISTS parts(mode TEXT, parent TEXT, component TEXT,
        PRIMARY KEY(mode,parent,component));
        CREATE INDEX IF NOT EXISTS part_lookup ON parts(mode,component);
        CREATE TABLE IF NOT EXISTS provenance(key TEXT PRIMARY KEY,value TEXT);''')
    sys.path.insert(0, str(ROOT))
    from sanlex.text import is_han, parse_ids
    counts = {}
    with conn:
        conn.execute('DELETE FROM glyphs')
        conn.execute('DELETE FROM parts')
        for mode, suffix in MODES.items():
            definitions = {row['character']: row for line in
                           (originals / f'dictionary{suffix}.txt').read_text(encoding='utf-8').splitlines()
                           if (row := json.loads(line))}
            count = 0
            for line in (originals / f'graphics{suffix}.txt').read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                char = row['character']
                if len(char) != 1:
                    continue
                metadata = definitions.get(char, {})
                conn.execute('INSERT INTO glyphs VALUES(?,?,?,?)',
                             (mode, char, zlib.compress(line.encode('utf-8')), json.dumps(metadata, ensure_ascii=False)))
                try:
                    leaves = parse_ids(metadata.get('decomposition', '')).leaves()
                except ValueError:
                    leaves = []
                conn.executemany('INSERT OR IGNORE INTO parts VALUES(?,?,?)',
                                 [(mode,char,c) for c in leaves if c != char and is_han(c)])
                count += 1
            counts[mode] = count
    manifest = {'project':'AnimCJK', 'revision':REVISION, 'url':'https://github.com/parsimonhi/animCJK',
                'sha256': hashes, 'glyphs':counts,
                'modified':datetime.now(timezone.utc).isoformat(),
                'changes':'Regional records compressed into SQLite; components indexed from decomposition; original files retained.'}
    with conn:
        conn.execute('INSERT OR REPLACE INTO provenance VALUES(?,?)',('manifest',json.dumps(manifest)))
        conn.execute('INSERT OR REPLACE INTO provenance VALUES(?,?)',('license','Arphic Public License (graphics); LGPL-3.0-or-later (dictionary metadata). Copyright 2016–2026 FM&SH. Derived from Arphic and Make Me a Hanzi. No warranty. See bundled licences and original files.'))
    assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    conn.close()
    (target / 'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for name, filename in [('licenses/COPYING.txt','AnimCJK-COPYING.txt'),
                            ('licenses/APL/english/ARPHICPL.TXT','AnimCJK-Arphic-Public-License.txt')]:
        with urllib.request.urlopen(BASE + name, timeout=60) as response:
            (ROOT / 'licenses' / filename).write_bytes(response.read())
    print(json.dumps(manifest,indent=2),flush=True)


if __name__ == '__main__':
    main()
