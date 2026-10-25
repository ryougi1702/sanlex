"""Launch the real frozen executable with an isolated, tiny offline database.

Run after packaging, rather than relying on source-mode tests to catch missing
or incompatible DLLs. No user dictionary, preferences or bookmarks are changed.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sanlex.db import Dictionary


def smoke_build(executable):
    executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix='sanlex-build-') as directory:
        home = Path(directory)
        db = Dictionary(home / 'dictionary.sqlite3')
        db.initialize()
        db.close()
        capture = home / 'startup.png'
        env = os.environ.copy()
        env['QT_QPA_PLATFORM'] = 'offscreen'
        # Retain the normal PATH here: the built app must work in the user's
        # environment, even though build-time dependency discovery is isolated.
        startup = None
        if sys.platform == 'win32':
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
        for name, arguments in [('startup', []), ('workspace', ['--character','木','--handwriting'])]:
            capture = home / f'{name}.png'
            result = subprocess.run([str(executable), '--home', str(home), '--screenshot', str(capture), *arguments],
                                    env=env, startupinfo=startup, timeout=30)
            if result.returncode or not capture.exists() or capture.stat().st_size < 100:
                raise RuntimeError(f'Packaged application failed to launch {name} (exit {result.returncode})')
        print('Packaged application launch passed: main window and embedded character / handwriting tools rendered.', flush=True)


if __name__ == '__main__':
    smoke_build(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'dist/SanLex/SanLex.exe')
