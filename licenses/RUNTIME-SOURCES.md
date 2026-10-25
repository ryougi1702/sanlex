# Runtime source references

The portable application uses unmodified, dynamically loaded Qt / PySide6 / Shiboken6 6.10.2 libraries. Compatible replacement libraries can be placed in the corresponding `_internal` runtime locations. The application source, starter data, requirements, tests and build scripts are included under `_internal/source/`.

- [Qt 6.10.2 source archives](https://download.qt.io/archive/qt/6.10/6.10.2/submodules/) (notably qtbase, which provides Core, Gui and Widgets).
- [Qt for Python / Shiboken 6.10.2 source](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.10.2).
- [CPython 3.11 source](https://www.python.org/downloads/source/).
- [PyInstaller source and bootloader exception](https://github.com/pyinstaller/pyinstaller).

The full LGPL v3, GPL v3, Python licence, and Qt / PySide third-party notices are provided alongside this file. Runtime source copyrights and licences remain with their authors.
