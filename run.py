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
        import sys
        message = f'{error}\n\nDetails: {log}'
        if sys.platform == 'win32':
            # Startup may have failed while loading Qt itself. Reporting that
            # error must not depend on successfully importing Qt a second time.
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'SanLex could not start', 0x10)
        else:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, 'SanLex could not start', message)
        raise SystemExit(1)
