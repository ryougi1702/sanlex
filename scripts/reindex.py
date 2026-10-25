"""Rebuild local development indexes after changing normalization rules."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sanlex.db import Dictionary
from sanlex.importers import import_wiktionary

parser = argparse.ArgumentParser()
parser.add_argument('--home', type=Path, default=Path('local-data'))
args = parser.parse_args()
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
db = Dictionary(args.home / 'dictionary.sqlite3')
db.initialize()
for edition in ('ja', 'zh'):
    path = args.home / 'downloads' / (edition + 'wiktionary.jsonl.gz')
    if path.exists():
        with db.conn:
            import_wiktionary(db, path, print, None, edition, links_only=True)
db.rebuild_search()
db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
print(db.counts())
db.close()
