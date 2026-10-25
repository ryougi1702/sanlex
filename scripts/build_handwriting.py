"""Rebuild the offline handwriting acceleration index from bundled stroke data."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sanlex.handwriting import build_index

if __name__ == '__main__':
    pack = ROOT / 'assets' / 'strokes'
    print(build_index(pack / 'characters.sqlite3', pack / 'handwriting.json.zlib'))
