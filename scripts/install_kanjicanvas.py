"""Bundle a pinned KanjiCanvas release for fully offline recognition."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a9214105f156def3b96930e5fcf10b7652b7a1f7'
PROJECT = 'https://github.com/asdfjkl/kanjicanvas'


def install():
    target = ROOT / 'assets' / 'kanjicanvas'
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for source, name in [('docs/resources/javascript/kanji-canvas.js', 'kanji-canvas.js'),
                         ('docs/resources/javascript/ref-patterns.js', 'patterns.json.zlib'),
                         ('LICENSE.TXT', 'LICENSE.TXT'), ('README.md', 'UPSTREAM-README.md')]:
        url = f'https://raw.githubusercontent.com/asdfjkl/kanjicanvas/{REVISION}/{source}'
        data = urllib.request.urlopen(url, timeout=60).read()
        hashes[source] = hashlib.sha256(data).hexdigest()
        if name == 'patterns.json.zlib':
            # The assigned array is JSON with trailing commas. Preserve its
            # numeric values while discarding comments and JavaScript syntax.
            literal = data.decode('utf-8').split('KanjiCanvas.refPatterns =', 1)[1].strip().rstrip(';')
            patterns = json.loads(re.sub(r',\s*]', ']', literal))
            data = zlib.compress(json.dumps(patterns, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9)
        (target / name).write_bytes(data)
    manifest = {'project': 'KanjiCanvas', 'url': PROJECT, 'revision': REVISION,
                'source_sha256': hashes, 'characters': len({p[0] for p in patterns}),
                'character_set': ''.join(dict.fromkeys(p[0] for p in patterns)),
                'changes': 'Upstream engine unchanged. Reference array serialized as compressed JSON; '
                           'no reference coordinates changed. SanLex supplies a native drawing pad and headless adapter.'}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Bundled {manifest["characters"]:,} KanjiCanvas characters at {REVISION}.')


if __name__ == '__main__':
    install()
