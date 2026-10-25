"""Build a portable Qt desktop folder with optional offline dictionary snapshot."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
parser = argparse.ArgumentParser()
parser.add_argument('--database', type=Path)
parser.add_argument('--dist-dir', type=Path, default=Path('dist'), help='Output root; choose a separate folder while an existing app is running')
parser.add_argument('--work-dir', type=Path, help='Separate PyInstaller work folder when the existing build is running')
parser.add_argument('--reuse-snapshot', action='store_true', help='Reuse the existing compact snapshot after UI-only changes')
args = parser.parse_args()

# A text mark rendered by native Qt; no external fonts or images bundled.
from make_icon import make_icon
assets = ROOT / 'assets'
make_icon(assets / 'icon.ico')

command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
           '--name', 'SanLex', '--icon', str(assets / 'icon.ico'), '--distpath', str(args.dist_dir.resolve())]
if args.work_dir:
    command += ['--workpath', str(args.work_dir.resolve())]
for source, destination in [('assets','assets'), ('licenses','licenses'),
                            ('THIRD_PARTY_NOTICES.md','.'), ('README.md','.'), ('LICENSE','.'),
                            ('sanlex','source/sanlex'), ('scripts','source/scripts'),
                            ('requirements.txt','source'), ('requirements-dev.txt','source'), ('run.py','source'),
                            ('assets','source/assets'), ('licenses','source/licenses'), ('tests','source/tests'),
                            ('THIRD_PARTY_NOTICES.md','source'), ('README.md','source'), ('LICENSE','source')]:
    command += ['--add-data', f'{source}{os.pathsep}{destination}']
if args.database:
    snapshot_dir = ROOT / 'build' / 'bundled-data'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / 'dictionary.sqlite3'
    if not (args.reuse_snapshot and snapshot.exists()):
        if snapshot.exists():
            snapshot.unlink()
        print('Creating a compact, consistent offline snapshot…', flush=True)
        source = sqlite3.connect(f'file:{args.database.resolve().as_posix()}?mode=ro', uri=True, timeout=120)
        source.execute('VACUUM INTO ?', (str(snapshot),))
        manifest = {row[0]: json.loads(row[1]) for row in source.execute('SELECT * FROM sources')}
        source.close()
        (snapshot_dir / 'sources.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    command += ['--add-data', f'{snapshot_dir}{os.pathsep}bundled-data']
command += ['run.py']
build_env = os.environ.copy()
if sys.platform == 'win32':
    # Dependency discovery also searches PATH. Other installed tools can ship
    # identically named, ABI-incompatible DLLs (notably Poppler's icuuc.dll).
    # Qt uses the Windows ICU API; let it resolve against Windows itself.
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    build_env['PATH'] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), windows / 'System32', windows)))
    for variable in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        build_env.pop(variable, None)
subprocess.run(command, check=True, env=build_env)
for name in ('README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE'):
    shutil.copy2(ROOT / name, args.dist_dir / 'SanLex' / name)
subprocess.run([sys.executable, str(ROOT / 'scripts' / 'smoke_build.py'),
                str(args.dist_dir / 'SanLex' / 'SanLex.exe')], check=True)
print(f'Ready: {args.dist_dir.resolve() / "SanLex/SanLex.exe"}')
