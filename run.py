from sanlex.__main__ import main

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback
        from sanlex.db import default_home
        home = default_home()
        home.mkdir(parents=True, exist_ok=True)
        log = home / 'startup-error.log'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, 'SanLex could not start', f'{error}\n\nDetails: {log}')
        raise SystemExit(1)
