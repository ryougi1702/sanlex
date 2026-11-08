from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from .db import Dictionary, default_home, resource_path


def main():
    # Required before argument parsing in the frozen Windows application's
    # local KanjiCanvas helper process.
    import multiprocessing
    multiprocessing.freeze_support()
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="SanLex · Japanese / English / Chinese dictionary")
    parser.add_argument("--home", type=Path, default=default_home(), help="Dictionary and user data folder")
    parser.add_argument("--install-data", action="store_true", help="Download and index full dictionaries, then exit")
    from .importers import SOURCES
    parser.add_argument("--sources", nargs="+", choices=list(SOURCES))
    parser.add_argument("--refresh", action="store_true", help="Fetch fresh source files")
    parser.add_argument('--character',help='Open the character analysis window for one kanji / hanzi')
    parser.add_argument('--character-mode',choices=('ja','hans','hant'),help='Character analysis region')
    parser.add_argument('--handwriting',action='store_true',help='Open the handwriting panel in the main window')
    parser.add_argument("--screenshot", type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--handwriting-check', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.character:
        from .text import is_han
        if not is_han(args.character):
            parser.error('--character requires one kanji or hanzi')
    args.home.mkdir(parents=True, exist_ok=True)
    path = args.home / "dictionary.sqlite3"
    bundled = resource_path("bundled-data/dictionary.sqlite3")
    if not path.exists() and bundled.exists():
        temporary = path.with_suffix(".copying")
        shutil.copyfile(bundled, temporary)
        temporary.replace(path)
    db = Dictionary(path)
    db.initialize()
    if args.install_data:
        from .importers import SOURCES, download, install_source
        try:
            for source in args.sources or SOURCES:
                downloaded = download(source, args.home / "downloads", refresh=args.refresh)
                install_source(db, source, downloaded)
            print(db.counts())
        finally:
            db.close()
        return
    db.close()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from .ui import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("SanLex")
    app.setOrganizationName("SanLex")
    window = MainWindow(path)
    window.show()
    if args.character:
        window.open_character_analysis(args.character,args.character_mode)
    if args.handwriting:
        window.open_handwriting()
    if args.handwriting_check:
        import json
        import time
        window.open_handwriting()
        pad = window.handwriting_window
        pad.mode.setCurrentIndex(pad.mode.findData('ja'))
        pad.canvas.strokes = [[(.1,.35),(.9,.35)],[(.5,.05),(.5,.95)],
                              [(.48,.38),(.35,.65),(.08,.9)],[(.52,.38),(.7,.7),(.95,.9)]]
        pad.canvas.changed.emit()
        deadline = time.monotonic() + 15

        def check_handwriting():
            if pad.error or time.monotonic() > deadline or pad.candidates.count():
                matches = [pad.candidates.item(i).text() for i in range(pad.candidates.count())]
                success = not pad.error and '木' in matches[:5]
                args.handwriting_check.write_text(json.dumps(
                    {'success': success, 'engine': pad.backend, 'matches': matches, 'error': pad.error}), encoding='utf-8')
                window.close()
                app.exit(0 if success else 1)
            else:
                QTimer.singleShot(50, check_handwriting)

        QTimer.singleShot(50, check_handwriting)
    if args.screenshot:
        def capture():
            window.grab().save(str(args.screenshot))
            window.close()
            app.quit()
        QTimer.singleShot(1600, capture)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
