from __future__ import annotations

import csv
from datetime import datetime
from html import escape as esc
import json
from pathlib import Path
import re
import threading
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QUrl, QSize
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QKeySequence, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QScrollArea, QDockWidget)

from .db import Dictionary, resource_path
from .filters import FilterPanel
from .fonts import REGIONAL_FONT_CSS, entry_font, font_style, language_html
from .analysis_window import AnalysisPopup, AnalysisWindow
from .examples import corpus_examples, dictionary_examples
from .autocomplete import Autocomplete
from .handwriting_window import HandwritingWindow
from .importers import Cancelled, SOURCES, download, install_source
from .text import IDS_LABELS, is_han, parse_ids, radical_label


STYLE = """
QMainWindow, QDialog { background: #f4f3ed; color: #202c32; }
QWidget { font-family: 'Segoe UI', 'Yu Gothic UI', 'Microsoft YaHei UI'; font-size: 14px; }
QLabel { color: #202c32; }
QFrame#sidebar { background: #172e35; border-radius: 0px; }
QWidget#sourceList, QScrollArea { background: #f4f3ed; }
QWidget#filterPanel { background: #f4f3ed; }
QDockWidget { color: #25453e; background: #f4f3ed; }
QDockWidget::title { background: #e5ebe1; padding: 8px; }
QFrame#sourceCard { background: #fffef9; border: 1px solid #d7ded7; border-radius: 7px; }
QLabel#sourceTitle { font-weight: 600; }
QLabel#installedStatus { color: #236348; font-weight: 600; }
QLabel#missingStatus { color: #8b612b; font-weight: 600; }
QFrame#sidebar QLabel { color: #dfe8e6; background: transparent; }
QLabel#brand { font-size: 26px; font-weight: 700; color: #fff; }
QLabel#subtitle { color: #aabfbb; font-size: 12px; }
QLabel#eyebrow { color: #56726c; font-size: 12px; font-weight: 600; }
QLabel#pageTitle { font-size: 26px; font-weight: 600; }
QLabel#muted { color: #687d7c; font-size: 12px; }
QLabel#count { color: #56726c; font-weight: 600; }
QLineEdit { background: #fff; color: #202c32; border: 1px solid #c6d2cd; border-radius: 8px; padding: 12px; font-size: 17px; selection-background-color: #cce3dc; }
QLineEdit:focus { border: 2px solid #397668; padding: 11px; }
QPushButton { background: #fff; border: 1px solid #c7d3cd; border-radius: 6px; padding: 9px 14px; color: #25453e; }
QPushButton:hover { background: #e4eee8; }
QPushButton:pressed { background: #d3e4da; }
QPushButton:disabled { color: #87928c; background: #e9ece6; }
QPushButton#primary { background: #296b58; color: #fff; border: 1px solid #296b58; font-weight: 600; }
QPushButton#primary:hover { background: #1e5747; }
QPushButton#nav { color: #e2edeb; background: transparent; border: none; text-align: left; padding: 13px 12px; }
QPushButton#nav:hover { background: #2a454b; }
QPushButton#nav:checked { background: #36574f; border-left: 3px solid #d6bd81; }
QPushButton#example { padding: 5px 10px; background: #e8ece4; border: none; font-size: 12px; }
QComboBox { background: #fff; color: #25453e; border: 1px solid #c7d3cd; border-radius: 6px; padding: 10px; min-width: 110px; }
QComboBox QAbstractItemView { background: white; color: #202c32; selection-background-color: #d4e6dc; }
QListWidget { border: 1px solid #d7ded7; border-radius: 9px; background: #fbfcf8; padding: 5px; outline: none; }
QListWidget::item { padding: 12px 10px; margin: 3px 0; border-radius: 6px; color: #293d3d; border-bottom: 1px solid #e8ece4; }
QListWidget::item:selected { background: #dfebe2; color: #163e32; border-left: 3px solid #32775e; }
QListWidget::item:hover { background: #edf2e9; }
QTextBrowser { border: none; background: #fffef9; padding: 18px; border-radius: 8px; selection-background-color: #d0e5dc; color: #202c32; }
QTabWidget::pane { border: 1px solid #d9e0d6; background: #fffef9; border-radius: 8px; }
QTabBar::tab { background: transparent; padding: 13px 18px; color: #6c7c77; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { color: #205f4b; font-weight: 600; border-bottom: 3px solid #2b7158; }
QSplitter::handle { background: #f4f3ed; width: 14px; }
QStatusBar { color: #61746e; background: #e9ece4; font-size: 12px; }
QProgressBar { border: 1px solid #c7d3cd; border-radius: 4px; background: #fff; height: 9px; }
QProgressBar::chunk { background: #39775f; }
QCheckBox { spacing: 10px; padding: 5px; color: #25453e; }
QCheckBox::indicator { width: 17px; height: 17px; }
"""

HTML_STYLE = """
body {color:#273b3c;font-family:'Segoe UI','Yu Gothic UI','Microsoft YaHei UI';font-size:14px;}
h1 {font-size:38px;font-weight:600;color:#183e33;margin-bottom:4px;}
h2 {font-size:18px;color:#244e41;margin-top:25px;margin-bottom:10px;}
h3 {font-size:15px;color:#38634f;margin-top:18px;}
p {line-height:150%;}
a {color:#287357;text-decoration:none;}
.muted {color:#708076;font-size:12px;}
.reading {font-size:19px;color:#71816c;}
.tag {color:#9b7136;font-size:12px;}
.character {font-size:35px;color:#245843;}
td {padding:10px;}
li {margin-bottom:8px;}
hr {color:#e3e8dd;}
"""


def html(body: str, language=None) -> str:
    style = HTML_STYLE
    if language:
        # Qt rich text reapplies body CSS to descendants, overriding an inline
        # body font. Set the regional preference in the stylesheet itself.
        style = re.sub(r'font-family:[^;]+;', font_style(language), style, count=1)
    return f"<html><head><style>{style}\n{REGIONAL_FONT_CSS}</style></head><body>{body}</body></html>"


def link(kind: str, value: str, label: str | None = None, css="") -> str:
    return f'<a class="{css}" href="{kind}:{quote(value, safe="")}">{esc(label or value)}</a>'


def chars_html(value: str) -> str:
    return " ".join(link("char", c, css="character") for c in dict.fromkeys(value) if is_han(c))


def analysis_text(value: str, color=None) -> str:
    """Keep word spelling intact while linking each Han character separately."""
    style = f' style="color:{color};text-decoration:none"' if color else ''
    return ''.join(f'<a href="analyse:{quote(c,safe="")}" title="Analyse {c}"{style}>{esc(c)}</a>'
                   if is_han(c) else esc(c) for c in value)


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, slot, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(slot)
    return widget


def installed_date(metadata):
    return datetime.fromisoformat(metadata['installed']).astimezone().strftime('%Y-%m-%d')


class SearchWorker(QThread):
    result = Signal(int, object)
    failed = Signal(str)

    def __init__(self, path, query, lang, generation, parent, limit=80, sources=None, directions=None):
        super().__init__(parent)
        self.path, self.query, self.lang, self.generation = path, query, lang, generation
        self.limit = limit
        self.sources, self.directions = sources, directions

    def run(self):
        db = Dictionary(self.path)
        db.conn.set_progress_handler(lambda: int(self.isInterruptionRequested()), 2000)
        try:
            self.result.emit(self.generation, db.search(self.query, self.lang, self.limit + 1,
                                                       sources=self.sources, directions=self.directions))
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
        finally:
            db.close()


class InstallWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)

    def __init__(self, path, selected, refresh=False, local_file=None, parent=None):
        super().__init__(parent)
        self.path, self.selected, self.refresh = path, selected, refresh
        self.local_file = local_file
        self.cancel = threading.Event()

    def run(self):
        errors = []
        db = Dictionary(self.path)
        try:
            for source in self.selected:
                try:
                    downloaded = self.local_file or download(source, Path(self.path).parent / "downloads",
                                                            self.progress.emit, self.cancel, self.refresh)
                    install_source(db, source, downloaded, self.progress.emit, self.cancel)
                except Cancelled as error:
                    self.progress.emit(str(error))
                    break
                except Exception as error:
                    errors.append(f"{SOURCES[source]['name']}: {error}")
                    self.progress.emit(errors[-1])
        finally:
            db.close()
        self.completed.emit(errors)


class DataDialog(QDialog):
    data_changed = Signal()

    def __init__(self, db, parent):
        super().__init__(parent)
        self.db, self.worker = db, None
        self.setWindowTitle("SanLex · Dictionaries & sources")
        self.resize(940, 880)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 22, 25, 22)
        layout.addWidget(label("Your offline library", "pageTitle"))
        self.library_summary = label('', 'installedStatus')
        layout.addWidget(self.library_summary)
        self.offline_explanation = label(
            'Searches read the installed database on this device. No online lookup or automatic downloads.\n'
            'Checkboxes select a download or update; they do not indicate what is installed.', 'muted')
        self.offline_explanation.setWordWrap(True)
        layout.addWidget(self.offline_explanation)
        stroke_manifest = resource_path('assets/strokes/manifest.json')
        if stroke_manifest.exists():
            glyphs = json.loads(stroke_manifest.read_text(encoding='utf-8')).get('glyphs',{})
            stroke_status = label('Stroke animations installed offline · AnimCJK\n' +
                f"Japanese {glyphs.get('ja',0):,} · Simplified Chinese {glyphs.get('hans',0):,} · Traditional Chinese {glyphs.get('hant',0):,}\n" +
                'Included in the application folder and updated with the app. Word dictionary filters do not disable stroke data.', 'muted')
            stroke_status.setWordWrap(True)
            layout.addWidget(stroke_status)
        if resource_path('bundled-data/dictionary.sqlite3').exists():
            included = label('This Windows build includes preloaded dictionaries, so it works before you download anything here.', 'muted')
            included.setWordWrap(True)
            layout.addWidget(included)
        location_row = QHBoxLayout()
        location = label('Search database: ' + str(db.path.resolve()), 'muted')
        location.setTextFormat(Qt.TextFormat.PlainText)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.setWordWrap(True)
        location_row.addWidget(location, 1)
        location_row.addWidget(button('Open data folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(db.path.parent.resolve())))))
        layout.addLayout(location_row)
        self.checks = {}
        self.source_labels = {}
        self.cache_labels = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        source_list = QWidget()
        source_list.setObjectName('sourceList')
        source_layout = QVBoxLayout(source_list)
        source_layout.setContentsMargins(0, 0, 0, 0)
        for source, spec in SOURCES.items():
            card = QFrame()
            card.setObjectName('sourceCard')
            card_layout = QVBoxLayout(card)
            heading = QHBoxLayout()
            title = label(spec['name'], 'sourceTitle')
            title.setWordWrap(True)
            heading.addWidget(title, 1)
            check = QCheckBox('Select for download / update')
            check.setChecked(False)
            self.checks[source] = check
            heading.addWidget(check)
            card_layout.addLayout(heading)
            status = label('')
            card_layout.addWidget(status)
            self.source_labels[source] = status
            detail = label(f"{spec['about']}\n{spec['license']}", "muted")
            detail.setWordWrap(True)
            card_layout.addWidget(detail)
            cache_status = label('', 'muted')
            cache_status.setWordWrap(True)
            card_layout.addWidget(cache_status)
            self.cache_labels[source] = cache_status
            source_layout.addWidget(card)
        scroll.setWidget(source_list)
        layout.addWidget(scroll, 2)
        row = QHBoxLayout()
        self.install = button("Download / update selected", self.start_download, "primary")
        self.install.setToolTip('Manually download from publishers and install the selected dictionaries. Search never does this automatically.')
        row.addWidget(self.install)
        self.refresh = QCheckBox("Download latest files")
        self.refresh.setToolTip('When unchecked, reuse cached source files if available. Missing files are still downloaded when you request an update.')
        self.refresh.setChecked(True)
        row.addWidget(self.refresh)
        self.cancel_button = button("Cancel operation", self.cancel)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.source_combo = QComboBox()
        for source, spec in SOURCES.items():
            self.source_combo.addItem(source.upper(), source)
        row.addWidget(self.source_combo)
        self.import_button = button("Import downloaded source file…", self.import_file)
        row.addWidget(self.import_button)
        layout.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        self.log = QTextBrowser()
        self.log.setMinimumHeight(110)
        self.log.setHtml(html("<p class='muted'><b>Installed</b> means ready for offline search. <b>Cached download</b> means an original source archive retained for reinstalling; it is optional once installed.<br>Internet is used only when you explicitly request a download / update or open a source website link.</p>"))
        layout.addWidget(self.log, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(button("Attribution && licences", self.show_licenses))
        bottom.addStretch()
        bottom.addWidget(button("Done", self.close))
        layout.addLayout(bottom)
        for check in self.checks.values():
            check.toggled.connect(self.update_selection)
        self.refresh_status()

    def refresh_status(self):
        installed = self.db.sources()
        count = sum(source in installed for source in SOURCES)
        self.library_summary.setText(f'{count} of {len(SOURCES)} sources installed · ' +
                                     ('Ready for offline search' if count else 'Install dictionaries to begin'))
        for source, spec in SOURCES.items():
            meta = installed.get(source)
            status = self.source_labels[source]
            status.setObjectName('installedStatus' if meta else 'missingStatus')
            status.setText(f"INSTALLED · Ready offline · {meta['entries']:,} records · Data indexed {installed_date(meta)}"
                           if meta else 'NOT INSTALLED · Download or import this dictionary to add it')
            status.style().unpolish(status)
            status.style().polish(status)
            archive = self.db.path.parent / 'downloads' / spec['filename']
            self.cache_labels[source].setText(
                f'Cached download: {archive.name} ({archive.stat().st_size / 1048576:.1f} MB)'
                if archive.is_file() else 'Cached download: none (not required for installed dictionaries)')
            if source=='tatoeba' and archive.is_file():
                from .examples import FILES
                files=[archive.parent/'tatoeba'/Path(name).name for name in FILES]
                cached=[p for p in files if p.is_file()]
                self.cache_labels[source].setText(f'Cached download: {len(cached)} of 6 corpus files · '
                    f'{sum(p.stat().st_size for p in cached)/1048576:.1f} MB · {archive.name}')
        self.update_selection()

    def update_selection(self):
        count = sum(check.isChecked() for check in self.checks.values())
        busy = self.worker is not None and self.worker.isRunning()
        self.install.setEnabled(count > 0 and not busy)
        self.install.setText(f'Download / update selected ({count})' if count else 'Select dictionaries above to download / update')

    def show_licenses(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Sources, licences & coverage")
        dialog.resize(800, 650)
        layout = QVBoxLayout(dialog)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setMarkdown(resource_path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"))
        layout.addWidget(view)
        layout.addWidget(button("Close", dialog.close))
        dialog.exec()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose original dictionary source", "",
                                             "Dictionary / sentence sources (*.gz *.zip *.txt *.json);;All files (*)")
        if path:
            self.start([self.source_combo.currentData()], Path(path))

    def start_download(self):
        selected = [s for s, c in self.checks.items() if c.isChecked()]
        if not selected:
            self.log.append("Select at least one dictionary above.")
            return
        self.start(selected)

    def start(self, selected, local_file=None):
        if self.worker and self.worker.isRunning():
            return
        self.install.setEnabled(False)
        self.import_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.bar.setRange(0, 0)
        self.worker = InstallWorker(self.db.path, selected, self.refresh.isChecked(), local_file, self)
        self.worker.progress.connect(lambda text: self.log.append(esc(text)))
        self.worker.completed.connect(self.completed)
        self.worker.finished.connect(self.update_selection)
        self.worker.start()

    def completed(self, errors):
        self.import_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if errors:
            self.log.append("<b>Some sources could not be installed.</b> Check the messages above; retry or import a local file.")
        elif not self.worker.cancel.is_set():
            self.log.append("<b>Library is ready. Close this dialog to explore.</b>")
        self.refresh_status()
        self.data_changed.emit()

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.log.append("Cancelling safely… the current import will roll back.")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.cancel()
            event.ignore()
        else:
            event.accept()


class MainWindow(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.db = Dictionary(path)
        self.db.initialize()
        self.current_entry = None
        self.current_char = "弟"
        self.part_limit = 200
        self.compound_limit = 40
        self.example_limit = 4
        self.generation = 0
        self.result_limit = 80
        self._completion_target = None
        self._result_query = None
        self._recent_search_generation = None
        self.workers = []
        self.data_dialog = None
        self.analysis_window = None
        self.analysis_popup = None
        self.handwriting_window = None
        self._tool_filters_restore = False
        self._tool_space_active = False
        self._closing = False
        self._opening_analysis = False
        self.mode = "dictionary"
        self._navigation_history = []
        self._navigation_index = -1
        self._restoring_navigation = False
        self._filling_results = False
        self.setWindowTitle("SanLex · 三言辞典 · JP / EN / CN")
        self.setWindowIcon(QIcon(str(resource_path('assets/icon.ico'))))
        self.resize(1360, 900)
        self.setMinimumSize(1020, 690)
        self.setStyleSheet(STYLE)
        QApplication.instance().setFont(QFont("Segoe UI", 10))
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(202)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(19, 30, 17, 23)
        side.addWidget(label("三言  SanLex", "brand"))
        side.addWidget(label("ONE WORD. THREE WORLDS.", "subtitle"))
        side.addSpacing(43)
        self.nav = {}
        for key, title, action in (("dictionary", "01   Dictionary", lambda: self.navigate("dictionary")),
                                   ("characters", "02   Characters", lambda: self.navigate("characters")),
                                   ("saved", "03   Saved words", self.show_saved),
                                   ("history", "04   Recent searches", self.show_history)):
            nav = button(title, action, "nav")
            nav.setCheckable(True)
            self.nav[key] = nav
            side.addWidget(nav)
        side.addStretch()
        self.library_label = label("", "subtitle")
        self.library_label.setWordWrap(True)
        side.addWidget(self.library_label)
        side.addSpacing(16)
        side.addWidget(button("Dictionaries && sources", self.open_data, "nav"))
        side.addWidget(label("日本語  /  English  /  中文", "subtitle"))
        outer.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 25, 27, 20)
        layout.setSpacing(13)
        layout.addWidget(label("A DICTIONARY FOR THE CURIOUS", "eyebrow"))
        title_row = QHBoxLayout()
        self.title = label("Find the word. Explore its roots.", "pageTitle")
        self.title.setWordWrap(True)
        title_row.addWidget(self.title, 1)
        self.save_button = button("☆  Save word", self.save_current)
        self.save_button.setEnabled(False)
        title_row.addWidget(self.save_button)
        layout.addLayout(title_row)
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Japanese, English, 中文, kana, romaji or pinyin…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName("Dictionary search")
        self.search_input.returnPressed.connect(self.search_now)
        self.search_input.textChanged.connect(self.schedule_search)
        row.addWidget(self.search_input, 1)
        self.language = QComboBox()
        self.language.addItem("All languages", "all")
        self.language.addItem("Japanese", "jp")
        self.language.addItem("Chinese", "cn")
        self.language.addItem("English", "en")
        self.language.setAccessibleName("Filter entry language")
        self.language.currentIndexChanged.connect(self.search_now)
        row.addWidget(self.language)
        self.filter_toggle = button('Filters', self.toggle_filters)
        self.filter_toggle.setCheckable(True)
        self.filter_toggle.setChecked(True)
        self.filter_toggle.setToolTip('Show or hide dictionary and translation-direction filters')
        row.addWidget(self.filter_toggle)
        row.addWidget(button("Search", self.search_now, "primary"))
        layout.addLayout(row)
        self.examples_widget = QWidget()
        examples = QHBoxLayout(self.examples_widget)
        examples.setContentsMargins(0,0,0,0)
        examples.addWidget(label("EXPLORE", "muted"))
        for query in ("学校", "younger brother", "梯", "木", "dictionary"):
            examples.addWidget(button(query, lambda checked=False, q=query: self.set_query(q), "example"))
        examples.addStretch()
        self.handwriting_button = button('✎  Handwriting', self.toggle_handwriting)
        self.handwriting_button.setCheckable(True)
        self.handwriting_button.setToolTip('Draw an unfamiliar character to look it up (Ctrl+H)')
        layout.addWidget(self.examples_widget)
        self.result_label = label("", "count")
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        navigation_row = QHBoxLayout()
        self.back_button = button('← Back', self.go_back)
        self.back_button.setAccessibleName('Go back')
        self.back_button.setToolTip('Go back (Alt+Left)')
        self.back_button.setEnabled(False)
        navigation_row.addWidget(self.back_button)
        self.forward_button = button('Forward →', self.go_forward)
        self.forward_button.setAccessibleName('Go forward')
        self.forward_button.setToolTip('Go forward (Alt+Right)')
        self.forward_button.setEnabled(False)
        navigation_row.addWidget(self.forward_button)
        navigation_row.addWidget(self.handwriting_button)
        navigation_row.addStretch()
        navigation_row.addWidget(self.result_label)
        layout.addLayout(navigation_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.search_splitter = splitter
        left = QSplitter(Qt.Orientation.Vertical)
        left.setChildrenCollapsible(False)
        self.results_splitter = left
        results_panel = QWidget()
        left_layout = QVBoxLayout(results_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setAccessibleName("Dictionary results")
        self.results.setMinimumHeight(90)
        self.results.currentItemChanged.connect(self.select_result)
        self.results.itemClicked.connect(self.activate_result)
        self.results.itemActivated.connect(self.activate_result)
        left_layout.addWidget(self.results)
        self.more_button = button('Show more results', self.load_more_results)
        self.more_button.hide()
        left_layout.addWidget(self.more_button)
        self.export_button = button("Export saved words…", self.export_saved)
        self.export_button.hide()
        left_layout.addWidget(self.export_button)
        left.addWidget(results_panel)
        splitter.addWidget(left)
        self.tabs = QTabWidget()
        self.word_view = QTextBrowser()
        self.word_view.setOpenLinks(False)
        self.word_view.anchorClicked.connect(self.handle_link)
        self.tabs.addTab(self.word_view, "Word + translations")
        char_panel = QWidget()
        char_layout = QVBoxLayout(char_panel)
        char_layout.setContentsMargins(10, 10, 10, 10)
        char_row = QHBoxLayout()
        self.char_input = QLineEdit("弟")
        self.char_input.setPlaceholderText("One kanji / hanzi")
        self.char_input.setMaximumWidth(180)
        self.char_input.setAccessibleName("Character to explore")
        self.char_input.returnPressed.connect(self.explore_input)
        char_row.addWidget(self.char_input)
        char_row.addWidget(button("Explore", self.explore_input))
        char_row.addStretch()
        self.recursive = QCheckBox("Include nested parts")
        self.recursive.setChecked(True)
        self.recursive.toggled.connect(lambda: self.show_character(self.current_char))
        char_row.addWidget(self.recursive)
        char_layout.addLayout(char_row)
        char_layout.addWidget(button("Strokes, readings && parts", lambda: self.open_character_analysis(self.current_char)),
                              alignment=Qt.AlignmentFlag.AlignLeft)
        self.char_view = QTextBrowser()
        self.char_view.setOpenLinks(False)
        self.char_view.anchorClicked.connect(self.handle_link)
        char_layout.addWidget(self.char_view)
        self.tabs.addTab(char_panel, "Character explorer")
        self.analysis_page = QWidget()
        self.analysis_layout = QVBoxLayout(self.analysis_page)
        self.analysis_layout.setContentsMargins(0,0,0,0)
        self.analysis_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.analysis_placeholder)
        placeholder_layout.addWidget(label('Character analysis is open in a separate window.', 'muted'))
        placeholder_layout.addWidget(button('Return analysis to main window', self.return_analysis))
        placeholder_layout.addStretch()
        self.analysis_placeholder.hide()
        self.analysis_layout.addWidget(self.analysis_placeholder)
        self.tabs.addTab(self.analysis_page, 'Character analysis')
        self.tabs.setStyleSheet('QTabBar::tab {padding:10px 9px;}')
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([350, 700])
        layout.addWidget(splitter, 1)
        footer = label("JMdict / KANJIDIC2 © EDRDG · CC-CEDICT · Unicode Unihan · CJKVI / CHISE   |   Sources & licences in Library", "muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        outer.addWidget(content, 1)
        self.filter_dock = QDockWidget('Search filters', self)
        self.filter_dock.setObjectName('searchFiltersDock')
        self.filter_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.filter_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.filter_dock.setMinimumWidth(285)
        self.filter_panel = FilterPanel(self.db, self.filter_dock)
        self.filter_dock.setWidget(self.filter_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.filter_dock)
        self.resizeDocks([self.filter_dock], [300], Qt.Orientation.Horizontal)
        self.filter_dock.visibilityChanged.connect(self.filter_toggle.setChecked)
        self.filter_panel.changed.connect(self.filters_changed)
        self.filter_panel.reset_requested.connect(self.reset_filters)
        self.statusBar().showMessage("Ready · search stays on this device")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(280)
        self.timer.timeout.connect(lambda: self.search_now(record=False))
        self.autocomplete=Autocomplete(self.search_input,self.db.path,
            lambda:(self.language.currentData(),self.filter_kwargs()),self)
        self.autocomplete.selected.connect(self.accept_suggestion)
        self.language.currentIndexChanged.connect(self.autocomplete.context_changed)
        self.filter_panel.changed.connect(self.autocomplete.context_changed)
        self.nav["dictionary"].setChecked(True)
        search_action = QAction(self)
        search_action.setShortcut(QKeySequence("Ctrl+L"))
        search_action.triggered.connect(lambda: (self.search_input.setFocus(), self.search_input.selectAll()))
        self.addAction(search_action)
        handwriting_action = QAction(self)
        handwriting_action.setShortcut(QKeySequence('Ctrl+H'))
        handwriting_action.triggered.connect(self.toggle_handwriting)
        self.addAction(handwriting_action)
        for sequence, callback in (('Alt+Left', self.go_back), ('Alt+Right', self.go_forward)):
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(callback)
            self.addAction(action)
        self.tabs.currentChanged.connect(self.detail_tab_changed)
        self.refresh_library()
        self.show_character("弟", activate=False)
        self.set_query("学校")

    def navigation_key(self):
        if self.tabs.currentIndex() == 2 and self.analysis_window:
            panel = self.analysis_window
            return ('analysis',panel.root_char,panel.mode,panel.char,panel.details.currentIndex(),self.filter_panel.signature())
        if self.tabs.currentIndex() == 1:
            return ('character', self.current_char, self.filter_panel.signature())
        if self.current_entry:
            return ('entry', self.current_entry['id'], self.filter_panel.signature())
        return ('message', self.word_view.toPlainText(), self.filter_panel.signature())

    def filter_kwargs(self):
        return {'sources': self.filter_panel.selected_sources(),
                'directions': self.filter_panel.selected_directions()}

    def toggle_filters(self):
        self.filter_dock.setVisible(self.filter_dock.isHidden())
        if self._tool_space_active:
            self._tool_filters_restore = not self.filter_dock.isHidden()

    def tool_space_needed(self):
        return bool((self.handwriting_window and self.handwriting_window.isVisible()) or
                    (self.tabs.currentIndex() == 2 and not (self.analysis_popup and self.analysis_popup.isVisible())))

    def update_tool_space(self):
        if self._closing or self._restoring_navigation or not hasattr(self,'filter_dock'):
            return
        needed = self.tool_space_needed()
        if needed and not self._tool_space_active:
            self._tool_filters_restore = not self.filter_dock.isHidden()
            self.filter_dock.hide()
        elif not needed and self._tool_space_active:
            self.filter_dock.setVisible(self._tool_filters_restore)
        self._tool_space_active = needed

    def reset_filters(self):
        blocked = self.language.blockSignals(True)
        self.language.setCurrentIndex(0)
        self.language.blockSignals(blocked)
        self.filter_panel.reset_selection()

    def filters_changed(self):
        if self._restoring_navigation:
            return
        if self.mode == 'saved':
            self.show_saved()
        else:
            self.search_now(record=False, preserve_character=True)
        if self.tabs.currentIndex() == 1:
            self.show_character(self.current_char, activate=False)
        if self.analysis_window and self.analysis_window.isVisible():
            self.analysis_window.refresh_words()

    def navigation_snapshot(self):
        return {
            'key': self.navigation_key(), 'entry_id': self.current_entry['id'] if self.current_entry else None,
            'char': self.current_char, 'tab': self.tabs.currentIndex(),
            'word_html': self.word_view.toHtml(), 'char_html': self.char_view.toHtml(),
            'word_scroll': self.word_view.verticalScrollBar().value(),
            'char_scroll': self.char_view.verticalScrollBar().value(),
            'query': self.search_input.text(), 'language': self.language.currentIndex(), 'mode': self.mode,
            'result_query': self._result_query,
            'analysis': self.analysis_window.snapshot() if self.analysis_window and self.analysis_window.root_char else None,
            'tool_space_active': self._tool_space_active, 'tool_filters_restore': self._tool_filters_restore,
            'sources': self.filter_panel.selected_sources(), 'directions': self.filter_panel.selected_directions(),
            'corpus':self.filter_panel.corpus_check.isChecked(), 'example_limit':self.example_limit,
            'filters_visible': not self.filter_dock.isHidden(),
            'results': [(self.results.item(i).text(), self.results.item(i).data(Qt.ItemDataRole.UserRole),
                         self.results.item(i).toolTip(), self.results.item(i).font()) for i in range(self.results.count())],
            'result_row': self.results.currentRow(), 'result_scroll': self.results.verticalScrollBar().value(),
            'result_label': self.result_label.text(), 'result_limit': self.result_limit,
            'more_results': not self.more_button.isHidden(), 'export': not self.export_button.isHidden(),
            'recursive': self.recursive.isChecked(), 'part_limit': self.part_limit,
            'compound_limit': self.compound_limit,
        }

    def save_navigation_position(self):
        if self._restoring_navigation or self._opening_analysis or self._navigation_index < 0:
            return
        page = self._navigation_history[self._navigation_index]
        page['filters_visible'] = not self.filter_dock.isHidden()
        page['tool_space_active'] = self._tool_space_active
        page['tool_filters_restore'] = self._tool_filters_restore
        # Save the document being left, even after the user has switched tabs.
        # Keep its recorded query/results: an asynchronous search may already
        # be preparing the next page's context.
        kind, value = page['key'][:2]
        if kind == 'entry' and self.current_entry and self.current_entry['id'] == value:
            page['word_scroll'] = self.word_view.verticalScrollBar().value()
        elif kind == 'character' and self.current_char == value:
            page['char_scroll'] = self.char_view.verticalScrollBar().value()
        elif kind == 'analysis' and self.analysis_window and page.get('analysis'):
            state = self.analysis_window.snapshot()
            previous = page['analysis']
            if (state['root'],state['mode'],state['char']) == (previous['root'],previous['mode'],previous['char']):
                state['detail'] = previous['detail']
                page['analysis'] = state
        if page['query'] == self.search_input.text() and page['language'] == self.language.currentIndex():
            page['result_scroll'] = self.results.verticalScrollBar().value()

    def record_navigation_page(self):
        if self._restoring_navigation:
            return
        page = self.navigation_snapshot()
        if self._navigation_index >= 0 and self._navigation_history[self._navigation_index]['key'] == page['key']:
            self._navigation_history[self._navigation_index] = page
        else:
            del self._navigation_history[self._navigation_index + 1:]
            self._navigation_history.append(page)
            if len(self._navigation_history) > 100:
                self._navigation_history.pop(0)
            self._navigation_index = len(self._navigation_history) - 1
        self.update_navigation_buttons()

    def update_navigation_buttons(self):
        self.back_button.setEnabled(self._navigation_index > 0)
        self.forward_button.setEnabled(0 <= self._navigation_index < len(self._navigation_history) - 1)

    def set_detail_tab(self, index):
        blocked = self.tabs.blockSignals(True)
        try:
            self.tabs.setCurrentIndex(index)
        finally:
            self.tabs.blockSignals(blocked)
        self.update_tool_space()

    def detail_tab_changed(self, index):
        if not self._restoring_navigation:
            self.save_navigation_position()
            if index == 2 and not (self.analysis_popup and self.analysis_popup.isVisible()):
                char = self.current_char
                previous = self._navigation_history[self._navigation_index] if self._navigation_index >= 0 else None
                if previous and previous['tab'] == 0 and self.current_entry:
                    word = self.current_entry['headword']
                    panel = self.analysis_window
                    char = panel.root_char if panel and (panel.root_char in word or panel.char in word) else next(
                        (c for c in word if is_han(c)),char)
                if self.analysis_window is None or char not in (self.analysis_window.root_char,self.analysis_window.char):
                    self.open_character_analysis(char)
                    return
            self.update_tool_space()
            self.record_navigation_page()

    def go_back(self):
        self.travel_navigation(-1)

    def go_forward(self):
        self.travel_navigation(1)

    def travel_navigation(self, step):
        target = self._navigation_index + step
        if not 0 <= target < len(self._navigation_history):
            return
        self.autocomplete.dismiss()
        self.save_navigation_position()
        self.timer.stop()
        self.generation += 1
        for worker in self.workers:
            worker.requestInterruption()
        self._navigation_index = target
        page = self._navigation_history[target]
        widgets = (self.search_input, self.language, self.results, self.recursive, self.tabs)
        blocked = [widget.blockSignals(True) for widget in widgets]
        self._restoring_navigation = True
        try:
            self.search_input.setText(page['query'])
            self.language.setCurrentIndex(page['language'])
            self.filter_panel.restore_selection(page['sources'], page['directions'],page.get('corpus',False))
            self.example_limit=page.get('example_limit',4)
            self.filter_dock.setVisible(page['filters_visible'])
            self._tool_space_active = page.get('tool_space_active',False)
            self._tool_filters_restore = page.get('tool_filters_restore',False)
            self.mode = page['mode']
            self._result_query = page.get('result_query')
            for key, nav in self.nav.items():
                nav.setChecked(key == self.mode)
            self.results.clear()
            for text, data, tooltip, font in page['results']:
                item = QListWidgetItem(text)
                item.setFont(font)
                item.setData(Qt.ItemDataRole.UserRole, data)
                item.setToolTip(tooltip)
                self.results.addItem(item)
            self.results.setCurrentRow(page['result_row'])
            self.result_label.setText(page['result_label'])
            self.result_limit = page['result_limit']
            self.more_button.setVisible(page['more_results'])
            self.export_button.setVisible(page['export'])
            self.current_entry = self.db.entry(page['entry_id']) if page['entry_id'] else None
            self.current_char = page['char']
            self.char_input.setText(page['char'])
            self.recursive.setChecked(page['recursive'])
            self.part_limit = page['part_limit']
            self.compound_limit = page['compound_limit']
            self.word_view.setHtml(page['word_html'])
            self.char_view.setHtml(page['char_html'])
            if page.get('analysis'):
                self.ensure_analysis()
                self.analysis_window.restore(page['analysis'])
            self.tabs.setCurrentIndex(page['tab'])
            self.save_button.setEnabled(self.current_entry is not None)
            self.update_save_label()
        finally:
            for widget, previous in zip(widgets, blocked):
                widget.blockSignals(previous)
            self._restoring_navigation = False
        self.filter_panel.persist()
        if self.analysis_window and self.analysis_window.isVisible():
            self.analysis_window.refresh_words()

        def restore_scroll():
            if self._navigation_history[self._navigation_index] is page:
                self.word_view.verticalScrollBar().setValue(page['word_scroll'])
                self.char_view.verticalScrollBar().setValue(page['char_scroll'])
                self.results.verticalScrollBar().setValue(page['result_scroll'])
        restore_scroll()
        QTimer.singleShot(0, restore_scroll)
        self.update_navigation_buttons()

    def navigate(self, mode):
        self.autocomplete.dismiss()
        self.mode = mode
        for key, nav in self.nav.items():
            nav.setChecked(key == mode)
        self.export_button.setVisible(mode == "saved")
        if mode in ('saved', 'history'):
            self.more_button.hide()
        if mode == "characters":
            self.show_character(self.current_char)
        elif mode == "dictionary":
            self.tabs.setCurrentIndex(0)
            self.search_now(record=False)

    def set_query(self, query):
        self.search_input.setText(query)
        self.search_now()

    def schedule_search(self):
        self.generation += 1  # Invalidate results as soon as input changes.
        for worker in self.workers:
            worker.requestInterruption()
        self.timer.stop()
        # Non-empty edits use the lightweight completion preview. Full entries
        # are loaded on Enter, Search, or explicit suggestion selection.
        if not self.search_input.text().strip():
            self.timer.start(0)

    def accept_suggestion(self,row):
        self.search_input.setText(row['headword'])
        self.set_detail_tab(0)
        self.search_now(preserve_character=True,completion_id=row['id'])

    def open_recent_search(self, query):
        entry_id = self.db.history_entry(query)
        entry = self.db.entry(entry_id) if entry_id else None
        filters = self.filter_kwargs()
        if entry and ((filters['sources'] is not None and entry['source'] not in filters['sources']) or
                      (filters['directions'] is not None and
                       (entry['lang'], entry['definition_lang']) not in filters['directions']) or
                      self.language.currentData() not in ('all', entry['lang'])):
            entry_id = None
        # A recent search is a new lookup, independent of any explorer page or
        # unfinished search that happened to be visible when it was selected.
        self.search_input.setText(query)
        self.set_detail_tab(0)
        self.current_entry = None
        self.save_button.setEnabled(False)
        self.update_save_label()
        self.word_view.setHtml(html(f'<h2>Looking up {esc(query)}…</h2>'))
        self.search_now(preserve_character=True, completion_id=entry_id)
        self._recent_search_generation = self.generation
        if len(query) == 1 and is_han(query):
            self.show_character(query, activate=False)

    def search_now(self, checked=False, record=True, expanding=False, preserve_character=False,completion_id=None):
        self.autocomplete.dismiss()
        self.timer.stop()
        for worker in self.workers:
            worker.requestInterruption()
        if not expanding:
            self.result_limit = 80
        self.more_button.hide()
        query = self.search_input.text().strip()
        self.mode = "dictionary"
        self.export_button.hide()
        for key, nav in self.nav.items():
            nav.setChecked(key == "dictionary")
        self.generation += 1
        self._recent_search_generation = None
        self._completion_target=(self.generation,completion_id) if completion_id else None
        if not query:
            self.results.clear()
            self.result_label.setText("Enter a word, reading or English meaning")
            self.word_view.setHtml(html("<h2>Every word opens a new path.</h2><p>Search in Japanese, English or Chinese. Select any character to explore its structure.</p>"))
            self.current_entry = None
            self.save_button.setEnabled(False)
            self.record_navigation_page()
            return
        if record:
            self.db.record_search(query)
        self.result_label.setText("Searching your library…")
        worker = SearchWorker(self.db.path, query, self.language.currentData(), self.generation, self, self.result_limit,
                              **self.filter_kwargs())
        self.workers.append(worker)
        worker.result.connect(self.receive_search)
        worker.failed.connect(lambda message: self.statusBar().showMessage("Search error: " + message))
        worker.finished.connect(lambda w=worker: self.finish_worker(w))
        worker.start()
        if not preserve_character and len(query) == 1 and is_han(query):
            self.show_character(query)

    def finish_worker(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)
        worker.deleteLater()

    def receive_search(self, generation, results):
        if generation != self.generation:
            return
        query = self.search_input.text().strip()
        self._result_query = query
        self.more_button.setVisible(len(results) > self.result_limit)
        results = results[:self.result_limit]
        selected_id=None
        if self._completion_target and self._completion_target[0]==generation:
            selected_id=self._completion_target[1]
            selected=self.db.entry(selected_id)
            if selected and all(e['id']!=selected_id for e in results):
                results=[selected,*results[:max(0,self.result_limit-1)]]
        self._completion_target=None
        self.fill_results(results,selected_id)
        self.db.remember_search_entry(query, self.current_entry['id'] if results and self.current_entry else None)
        count = len(results)
        self.result_label.setText(f"{count} results shown   /   {self.search_input.text().strip()}")
        if not results:
            self.word_view.setHtml(html("<h2>No matching words.</h2><p>Try another word or use <b>Reset all filters</b> in the Filters panel. Dictionary, direction and language filters apply together.</p><p>The character explorer remains available. Use <b>Dictionaries & sources</b> to install additional dictionaries.</p>"))
            self.current_entry = None
            self.save_button.setEnabled(False)
            if self._recent_search_generation == generation and len(query) == 1 and is_han(query):
                self.show_character(query)
        self.record_navigation_page()

    def load_more_results(self):
        self.result_limit += 80
        self.search_now(record=False, expanding=True)

    def fill_results(self, entries, selected_id=None):
        self.save_navigation_position()
        self._filling_results = True
        self.results.clear()
        for entry in entries:
            meaning = "; ".join(entry["glosses"][:2])
            if len(meaning) > 130:
                meaning = meaning[:127] + "…"
            definition_lang = entry.get('definition_lang', 'en').upper()
            text = f"{entry['headword']}    {entry['lang'].upper()} → {definition_lang}\n{entry['reading']}\n{meaning}"
            item = QListWidgetItem(text)
            item.setFont(entry_font(entry['lang'], self.results.font()))
            item.setData(Qt.ItemDataRole.UserRole, ("entry", entry["id"]))
            item.setToolTip(f"{entry['source']} · " + "; ".join(entry["glosses"]))
            self.results.addItem(item)
        if entries:
            selected_row=next((i for i,e in enumerate(entries) if e['id']==selected_id),0)
            self.results.setCurrentRow(selected_row)
        self._filling_results = False

    def select_result(self, item, previous=None):
        if not item:
            return
        kind, value = item.data(Qt.ItemDataRole.UserRole)
        if kind == "query":
            self.open_recent_search(value)
        else:
            self.show_entry(value, activate=not self._filling_results)

    def activate_result(self, item):
        if not item:
            return
        kind, value = item.data(Qt.ItemDataRole.UserRole)
        if kind == 'query' and self.mode == 'history':
            self.open_recent_search(value)
        if kind == 'entry' and (self.tabs.currentIndex() != 0 or not self.current_entry or self.current_entry['id'] != value):
            self.show_entry(value)

    def show_entry(self, entry_id, activate=True):
        entry = self.db.entry(entry_id)
        if not entry:
            return
        visible = not self._filling_results and (activate or self.tabs.currentIndex() == 0)
        if visible:
            self.save_navigation_position()
        if not self.current_entry or self.current_entry['id']!=entry_id:
            self.example_limit=4
        self.current_entry = entry
        self.save_button.setEnabled(True)
        self.update_save_label()
        lang = {"jp": "JAPANESE 日本語", "cn": "CHINESE 中文", "en": "ENGLISH"}[entry['lang']]
        body = f"<p class='tag'>{lang} &nbsp; / &nbsp; {esc(entry['source'].upper())}</p>"
        body += f"<h1>{analysis_text(entry['headword'], '#183e33')}</h1><p class='reading'>{esc(entry['reading'])}</p>"
        alternatives = [f for f in entry["forms"] if f not in (entry["headword"], entry["reading"])]
        if alternatives:
            body += "<p class='muted'>Other forms: " + " · ".join(analysis_text(f) for f in alternatives) + "</p>"
        definition_name = {'en': 'English', 'jp': 'Japanese 日本語', 'cn': 'Chinese 中文'}[entry.get('definition_lang', 'en')]
        body += f"<h2>{definition_name} definitions</h2>"
        for number, sense in enumerate(entry["senses"] or [{"glosses": entry["glosses"]}], 1):
            tags = [*sense.get("pos", []), *sense.get("tags", [])]
            if tags:
                body += "<p class='tag'>" + esc(" · ".join(tags)) + "</p>"
            body += f"<p><b>{number:02d}</b> &nbsp; " + language_html(analysis_text("; ".join(sense["glosses"])), entry.get('definition_lang', 'en')) + "</p>"
            for field, title in (("spellings", "Applies to"), ("readings", "Reading"), ("xref", "See also")):
                if sense.get(field):
                    body += f"<p class='muted'>{title}: {analysis_text(' · '.join(sense[field]))}</p>"
            if sense.get("note"):
                body += f"<p class='muted'>{analysis_text(sense['note'])}</p>"
        restrictions = (entry["senses"] or [{}])[0].get("reading_restrictions", [])
        restricted = [r for r in restrictions if r["spellings"] or r["no_kanji"]]
        if restricted:
            body += "<h3>Reading / spelling restrictions</h3>"
            for r in restricted:
                body += f"<p class='muted'>{esc(r['reading'])}: {esc(' · '.join(r['spellings'])) if r['spellings'] else 'kana only'}</p>"
        body += self.render_examples(entry)
        localized_groups = {}
        for localized in self.db.localized_definitions(entry, **self.filter_kwargs()):
            localized_groups.setdefault(localized['definition_lang'], []).append(localized)
        for native_lang, localized_entries in localized_groups.items():
            name = {'jp': 'Japanese 日本語', 'cn': 'Chinese 中文'}[native_lang]
            body += f"<h2>{name} definitions</h2><p class='muted'>Wiktionary · definition previews · headword match; compare senses</p><ul>"
            seen_glosses = set()
            for localized in localized_entries:
                glosses = [g for g in localized['glosses'] if g not in seen_glosses]
                seen_glosses.update(glosses)
                body += ''.join('<li>' + language_html(analysis_text(g[:240] + ('…' if len(g) > 240 else '')), native_lang) + '</li>' for g in glosses[:3])
            body += '</ul><p>' + ' · '.join(link('entry', e['id'], f"Full source entry {i+1}") for i,e in enumerate(localized_entries)) + '</p>'
        body += "<hr><h2>Across languages · JP / EN / CN</h2>"
        mappings = self.db.mappings(entry, **self.filter_kwargs())
        if mappings:
            body += "<table width='100%' cellspacing='0'>"
            seen = set()
            for candidate, reason in mappings:
                shown_word = candidate.get('_translation_word', candidate['headword'])
                key = (candidate['lang'], shown_word, candidate["reading"], reason)
                if key in seen:
                    continue
                seen.add(key)
                body += "<tr><td bgcolor='#edf3e8'>" + language_html(
                    (link("entry", candidate["id"], shown_word) if candidate['id'] else link('lookup', shown_word))
                    + f" &nbsp; {esc(candidate['reading'])}", candidate['lang'])
                body += f" · {candidate['lang'].upper()}<br><span class='muted'>{esc(reason)}</span>"
                body += '<br>' + language_html(analysis_text('; '.join(candidate['glosses'][:3])), candidate.get('definition_lang', 'en')) + '</td></tr>'
                if candidate.get('_source_url'):
                    body += f"<tr><td><a href='{esc(candidate['_source_url'], quote=True)}'>Wiktionary source &amp; edit history ↗</a></td></tr>"
            body += "</table><p class='muted'>Wiktionary translations retain their source sense labels and may apply to a different sense of this headword. Suggestions use matching English glosses; check register and usage.</p>"
        else:
            body += "<p class='muted'>No cross-language mapping found with the current dictionary and direction filters. Try another English definition or reset the filters.</p>"
        glyphs = chars_html("".join([entry["headword"], *alternatives]))
        if glyphs:
            body += "<h2>Inside the word</h2><p>" + glyphs + "</p><p class='muted'>Select a character to open stroke animation, readings, components, “Part of” relationships and words.</p>"
        body += f"<hr><p class='muted'>Source: {esc(entry['source'])} · Entry {esc(entry['id'])}</p>"
        for sense in entry['senses']:
            if sense.get('source_url'):
                body += f"<p><a href='{esc(sense['source_url'], quote=True)}'>Original Wiktionary page &amp; contributor history ↗</a></p>"
                break
        self.word_view.setHtml(html(body, entry['lang']))
        if activate:
            self.set_detail_tab(0)
        if visible:
            self.record_navigation_page()
        if not self._restoring_navigation and not self._filling_results and self.mode == 'dictionary' and self._result_query:
            if self._result_query in (entry['headword'], entry['reading'], *entry['forms']) or any(
                    self.results.item(i).data(Qt.ItemDataRole.UserRole) == ('entry', entry_id)
                    for i in range(self.results.count())):
                self.db.remember_search_entry(self._result_query, entry_id)

    def explore_input(self):
        char = self.char_input.text().strip()
        if len(char) != 1:
            self.statusBar().showMessage("Enter one character in the explorer.")
            return
        self.show_character(char)

    def component_tree(self, char, ancestors=None, depth=0):
        ancestors = ancestors or set()
        text = link("char", char)
        data = self.db.character(char)
        meaning = data["unihan"].get("kDefinition") or "; ".join(data["kanjidic"].get("meanings", []))
        if meaning:
            text += f" <span class='muted'>— {esc(meaning)}</span>"
        if char in ancestors:
            return text + " <span class='muted'>(cycle)</span>"
        if depth >= 4:
            return text + " <span class='muted'>(click to explore further)</span>"
        decompositions = data["decompositions"]
        if decompositions:
            try:
                node = parse_ids(decompositions[0]["expression"])
                leaves = list(dict.fromkeys(node.leaves()))
                if leaves != [char]:
                    text += "<ul>" + "".join("<li>" + self.component_tree(c, ancestors | {char}, depth + 1) + "</li>"
                                            if len(c) == 1 else f"<li>{esc(c)}</li>" for c in leaves) + "</ul>"
            except ValueError:
                pass
        return text

    def show_character(self, char, activate=True):
        visible = activate or self.tabs.currentIndex() == 1
        if visible:
            self.save_navigation_position()
        if char != self.current_char:
            self.part_limit = 200
            self.compound_limit = 40
        self.current_char = char
        self.char_input.setText(char)
        data = self.db.character(char)
        uni, kan = data["unihan"], data["kanjidic"]
        body = f"<p class='tag'>CHARACTER ATLAS &nbsp; / &nbsp; U+{ord(char):04X}</p><h1 style='font-size:68px'>{analysis_text(char, '#183e33')}</h1>"
        meanings = kan.get("meanings", [])
        body += f"<p>{esc(uni.get('kDefinition', '; '.join(meanings)) or 'No character definition in the installed data.')}</p>"
        if meanings and uni.get("kDefinition"):
            body += f"<p class='muted'>KANJIDIC2: {esc('; '.join(meanings))}</p>"
        body += "<table width='100%' cellspacing='1'>"
        for name, value in (("JP · On", " · ".join(kan.get("on", [])) or uni.get("kJapaneseOn")),
                            ("JP · Kun", " · ".join(kan.get("kun", [])) or uni.get("kJapaneseKun")),
                            ("JP · Names", " · ".join(kan.get("nanori", []))),
                            ("CN · Mandarin", uni.get("kMandarin")), ("CN · Cantonese", uni.get("kCantonese")),
                            ("Strokes", " / ".join(kan.get("strokes", [])) or uni.get("kTotalStrokes")),
                            ("Japanese school grade", kan.get("grade"))):
            if value:
                body += f"<tr><td bgcolor='#eef2e8' width='150'><b>{name}</b></td><td bgcolor='#f7f8f1'>{esc(str(value))}</td></tr>"
        body += "</table><h2>Dictionary radicals</h2>"
        radicals = kan.get("radicals", [])
        if radicals:
            body += "<p>JP · " + esc(" / ".join(radical_label(n) for n in radicals)) + "</p>"
        if uni.get("kRSUnicode"):
            body += "<p>Unicode · " + esc(" / ".join(radical_label(n) for n in uni["kRSUnicode"].split())) + "</p>"
            body += f"<p class='muted'>Radical / additional strokes: {esc(uni['kRSUnicode'])}. Apostrophes indicate simplified radical forms.</p>"
        if not radicals and not uni.get("kRSUnicode"):
            body += "<p class='muted'>Radical metadata is unavailable for this character. Install Unihan and KANJIDIC2 for broader coverage.</p>"
        body += "<h2>Visual components</h2>"
        if data["decompositions"]:
            for decomp in data["decompositions"]:
                expression = decomp["expression"]
                body += f"<p><span class='reading'>{esc(expression)}</span> <span class='muted'> · {esc(decomp['source'])}</span></p>"
                try:
                    node = parse_ids(expression)
                    body += f"<p class='muted'>{esc(IDS_LABELS.get(node.value, 'structure'))}</p>"
                    body += "<p>" + " &nbsp; + &nbsp; ".join(link("char", c, css="character") if len(c) == 1 else esc(c) for c in node.leaves()) + "</p>"
                except ValueError:
                    pass
            body += "<h3>Follow the components</h3><ul><li>" + self.component_tree(char) + "</li></ul>"
        else:
            body += "<p class='muted'>No decomposition is available in the installed sources. This does not establish that the character is indivisible.</p>"
        body += "<p class='muted'>Components describe glyph structure, not necessarily etymology or meaning. Regional forms can differ; [G], [T], [J], [K] identify source glyph variants. The tree uses the first listed structure.</p>"
        body += "<hr><h2>Part of</h2>"
        parents, more = self.db.part_of(char, self.recursive.isChecked(), self.part_limit)
        if parents:
            body += "<p>" + " &nbsp; ".join(link("char", p["parent"], p["parent"] + (" ↗" if not p["direct"] else ""), "character") for p in parents) + "</p>"
            body += f"<p class='muted'>{len(parents)}{' shown; more exist' if more else ' characters'} · ↗ = nested relationship. Includes all indexed regional structures.</p>"
            if more:
                body += '<p>' + link('partmore', char, 'Show 200 more parent characters') + '</p>'
        else:
            body += "<p class='muted'>No parent characters found in the installed component index.</p>"
        variants = []
        for field, title in (("kSimplifiedVariant", "Simplified"), ("kTraditionalVariant", "Traditional"), ("kSemanticVariant", "Semantic")):
            if uni.get(field):
                glyphs = [chr(int(code, 16)) for code in re.findall(r"U\+([0-9A-F]+)", uni[field])]
                variants.append(f"<p>{title}: " + " · ".join(link("char", g) for g in glyphs) + "</p>")
        if variants:
            body += "<h2>Related forms</h2>" + "".join(variants)
        compounds = self.db.containing(char, self.language.currentData(), self.compound_limit + 1, **self.filter_kwargs())
        more_words = len(compounds) > self.compound_limit
        compounds = compounds[:self.compound_limit]
        body += "<h2>Words containing " + esc(char) + "</h2>"
        if compounds:
            body += "<ul>"
            for word in compounds:
                body += '<li>' + language_html(link('entry', word['id'], word['headword'])
                    + f" &nbsp; <span class='muted'>{word['lang'].upper()} · {esc(word['reading'])}</span>", word['lang'])
                body += ' — ' + language_html(esc('; '.join(word['glosses'][:2])), word.get('definition_lang', 'en')) + '</li>'
            body += f"</ul><p class='muted'>{len(compounds)} word entries shown, filtered by dictionary, direction and language.</p>"
            if more_words:
                body += '<p>' + link('wordmore', char, 'Show 40 more word entries') + '</p>'
        else:
            body += "<p class='muted'>No words found for the selected language.</p>"
        self.char_view.setHtml(html(body))
        if activate:
            self.set_detail_tab(1)
        if visible:
            self.record_navigation_page()

    def handle_link(self, url: QUrl):
        kind = url.scheme()
        value = unquote(url.toString().split(":", 1)[1])
        if kind == "char" and len(value) == 1:
            self.open_character_analysis(value)
        elif kind == 'analyse' and len(value) == 1:
            self.open_character_analysis(value)
        elif kind == "entry":
            self.show_entry(value)
        elif kind == 'examplesmore' and self.current_entry and self.current_entry['id']==value:
            position=self.word_view.verticalScrollBar().value()
            self.example_limit+=4
            self.show_entry(value)
            self.word_view.verticalScrollBar().setValue(position)
        elif kind == 'lookup':
            self.save_navigation_position()
            self.set_query(value)
            self.set_detail_tab(0)
        elif kind == 'partmore':
            self.part_limit += 200
            self.show_character(value)
        elif kind == 'wordmore':
            self.compound_limit += 40
            self.show_character(value)
        elif kind == 'https':
            QDesktopServices.openUrl(url)

    def render_examples(self,entry):
        own,related,more = dictionary_examples(self.db,entry,self.example_limit,**self.filter_kwargs())
        corpus,corpus_more = corpus_examples(self.db,entry,self.example_limit,
            directions=self.filter_panel.selected_directions(),exclude=[r['text'] for r in own+related]) \
            if self.filter_panel.corpus_check.isChecked() else ([],False)
        body='<h2>Example sentences</h2>'
        groups=[('From this entry',own,''),('Sentences containing this spelling',corpus,
             'These sentences contain the spelling shown in this entry. Confirm the intended meaning; inflected forms may need a separate lookup. Translations are directly linked by contributors.'),
            ('From related dictionary entries',related,
             'These examples belong to the source entry and its stated meaning; compare it with the meaning above.')]
        for title,examples,note in groups:
            if not examples:
                continue
            body+='<h3>'+title+'</h3>'
            if note:
                body+="<p class='muted'>"+note+'</p>'
            for example in examples:
                body+='<p>'+language_html(analysis_text(example['text']), entry['lang'])
                if example.get('roman'):
                    body+="<br><span class='muted'>"+esc(example['roman'])+'</span>'
                for translation in example.get('translations',[]):
                    body+='<br><b>'+esc(translation['lang'].upper())+'</b> · '+language_html(analysis_text(translation['text']), translation['lang'])
                    if translation.get('url'):
                        credit=translation.get('author') or 'Tatoeba contributors'
                        body+=" <span class='muted'>— <a href='"+esc(translation['url'],quote=True)+"'>"+esc(credit)+'</a></span>'
                body+="<br><span class='muted'>"+esc(example['source'])
                if example.get('author'):
                    body+=' · '+esc(example['author'])
                if example.get('sense'):
                    body+=' · Source meaning: '+esc(example['sense'])
                if example.get('ref'):
                    body+=' · '+esc(str(example['ref']))
                if example.get('url'):
                    body+=" · <a href='"+esc(example['url'],quote=True)+"'>View source sentence / attribution ↗</a>"
                if example.get('entry_id') and example['entry_id']!=entry['id']:
                    body+=' · '+link('entry',example['entry_id'],'View dictionary entry')
                body+='</span></p>'
        if not any((own,related,corpus)):
            body+="<p class='muted'>No examples found with the current source and direction filters.</p>"
        if more or corpus_more:
            body+='<p>'+link('examplesmore',entry['id'],'Show more examples')+'</p>'
        return body

    def open_handwriting(self):
        self.autocomplete.dismiss()
        if self.handwriting_window is None:
            self.handwriting_window = HandwritingWindow(self.db, self.results_splitter, embedded=True)
            self.results_splitter.insertWidget(0,self.handwriting_window)
            self.handwriting_window.lookup_requested.connect(self.lookup_handwriting)
            self.handwriting_window.insert_requested.connect(self.insert_handwriting)
            self.handwriting_window.close_requested.connect(self.close_handwriting)
        self.examples_widget.hide()
        self.handwriting_window.show()
        self.update_tool_space()
        self.handwriting_button.setChecked(True)
        self.search_splitter.setSizes([355,max(420,self.search_splitter.width()-355)])
        self.results_splitter.setSizes([330,max(100,self.results_splitter.height()-330)])

    def toggle_handwriting(self):
        if self.handwriting_window and self.handwriting_window.isVisible():
            self.close_handwriting()
        else:
            self.open_handwriting()

    def close_handwriting(self):
        if self.handwriting_window:
            self.handwriting_window.hide()
        self.handwriting_button.setChecked(False)
        self.examples_widget.show()
        self.update_tool_space()

    def lookup_handwriting(self, char, mode):
        self.set_query(char)
        self.open_character_analysis(char, mode)

    def insert_handwriting(self, char):
        self.search_input.insert(char)
        self.search_input.setFocus()
        self.statusBar().showMessage('Character inserted · write another or press Search to look up the word')

    def open_character_analysis(self, char, mode=None):
        if not is_han(char):
            return
        self.save_navigation_position()
        self.ensure_analysis()
        self._opening_analysis = True
        try:
            if not self.analysis_popup or not self.analysis_popup.isVisible():
                self.set_detail_tab(2)
            self.analysis_window.show_character(char,mode)
        finally:
            self._opening_analysis = False
        self.analysis_window.show()
        if self.analysis_popup and self.analysis_popup.isVisible():
            self.analysis_popup.raise_()
            self.analysis_popup.activateWindow()
        self.record_navigation_page()

    def ensure_analysis(self):
        if self.analysis_window is None:
            self.analysis_window = AnalysisWindow(self.db,self.filter_kwargs,self.analysis_page,embedded=True)
            self.analysis_layout.addWidget(self.analysis_window)
            self.analysis_window.entry_requested.connect(self.open_analysis_entry)
            self.analysis_window.explorer_requested.connect(self.open_analysis_explorer)
            self.analysis_window.popout_requested.connect(self.toggle_analysis_popout)
            self.analysis_window.character_changing.connect(self.save_navigation_position)
            self.analysis_window.character_changed.connect(self.analysis_changed)
            self.analysis_window.details.currentChanged.connect(self.analysis_detail_changed)

    def analysis_changed(self):
        if self._restoring_navigation or self._closing:
            return
        panel = self.analysis_window
        if panel.char != self.current_char:
            self.show_character(panel.char,activate=False)
        if self.analysis_popup:
            self.analysis_popup.setWindowTitle(panel.windowTitle())
        if self.tabs.currentIndex() == 2:
            self.record_navigation_page()

    def analysis_detail_changed(self, index):
        if not self._restoring_navigation and not self._closing and self.tabs.currentIndex() == 2:
            self.save_navigation_position()
            self.record_navigation_page()

    def toggle_analysis_popout(self):
        if self.analysis_popup and self.analysis_popup.isVisible():
            self.return_analysis()
            return
        self.ensure_analysis()
        if self.analysis_popup is None:
            self.analysis_popup = AnalysisPopup(self)
            self.analysis_popup.resize(800,740)
            self.analysis_popup.setMinimumSize(480,500)
            QVBoxLayout(self.analysis_popup)
            self.analysis_popup.return_requested.connect(self.return_analysis)
        self.analysis_window.canvas.pause()
        self.analysis_popup.layout().addWidget(self.analysis_window)
        self.analysis_window.popout_button.setText('Return to main window')
        self.analysis_placeholder.show()
        self.analysis_popup.setWindowTitle(self.analysis_window.windowTitle())
        self.analysis_window.show()
        self.analysis_popup.show()
        self.update_tool_space()
        self.analysis_popup.raise_()
        self.analysis_popup.activateWindow()

    def return_analysis(self):
        if self.analysis_window and self.analysis_popup:
            self.analysis_window.canvas.pause()
            self.analysis_layout.addWidget(self.analysis_window)
            self.analysis_placeholder.hide()
            self.analysis_window.popout_button.setText('Pop out ↗')
            self.analysis_popup.hide()
            self.analysis_window.show()
            if not self._closing:
                self.set_detail_tab(2)
                self.record_navigation_page()

    def open_analysis_entry(self, entry_id):
        self.show_entry(entry_id)
        self.raise_()
        self.activateWindow()

    def open_analysis_explorer(self, char):
        self.show_character(char)
        self.raise_()
        self.activateWindow()

    def update_save_label(self):
        saved = self.current_entry and self.db.is_favorite(self.current_entry["id"])
        self.save_button.setText("★  Saved" if saved else "☆  Save word")

    def save_current(self):
        if self.current_entry:
            self.db.toggle_favorite(self.current_entry["id"])
            self.update_save_label()
            if self.mode == "saved":
                self.show_saved()

    def show_saved(self):
        self.generation += 1
        self.timer.stop()
        self.navigate("saved")
        entries = self.db.favorites(lang=self.language.currentData(), **self.filter_kwargs())
        self.fill_results(entries)
        self.result_label.setText(f"{len(entries)} saved words")
        self.tabs.setCurrentIndex(0)
        if not entries:
            self.current_entry = None
            self.save_button.setEnabled(False)
            self.word_view.setHtml(html("<h2>No saved words match these filters.</h2><p>Reset the filters or save an entry with the ☆ button. Saved words stay on this device and can be exported as CSV.</p>"))
        self.record_navigation_page()

    def show_history(self):
        self.generation += 1
        self.timer.stop()
        self.navigate("history")
        self.results.clear()
        history = self.db.history()
        for query in history:
            item = QListWidgetItem(query)
            item.setData(Qt.ItemDataRole.UserRole, ("query", query))
            self.results.addItem(item)
        self.result_label.setText(f"{len(history)} recent searches · select one to search again")

    def export_saved(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export saved words", "SanLex-saved.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Language", "Word", "Reading", "English", "Other forms", "Source", "Entry ID"])
                for entry in self.db.favorites(lang=self.language.currentData(), **self.filter_kwargs()):
                    values = [entry["lang"], entry["headword"], entry["reading"], "; ".join(entry["glosses"]),
                              " / ".join(entry["forms"]), entry["source"], entry["id"]]
                    # Avoid spreadsheet formula execution when imported dictionary text is exported.
                    writer.writerow(["'" + str(v) if str(v).startswith(("=", "+", "-", "@")) else v for v in values])
            self.statusBar().showMessage(f"Saved words exported to {path}")
        except OSError as error:
            QMessageBox.warning(self, "Could not export", str(error))

    def open_data(self):
        if not self.data_dialog:
            self.data_dialog = DataDialog(self.db, self)
            self.data_dialog.data_changed.connect(self.refresh_library)
        self.data_dialog.show()
        self.data_dialog.raise_()
        self.data_dialog.activateWindow()

    def refresh_library(self):
        counts = self.db.counts()
        installed = self.db.sources()
        self.filter_panel.reload()
        self.library_label.setText(f"OFFLINE LIBRARY\n\n{counts.get('jp',0):,} Japanese entries\n{counts.get('cn',0):,} Chinese entries\n{counts.get('en',0):,} English entries\n{counts['characters']:,} characters\n{counts['structures']:,} structures")
        if not installed:
            self.statusBar().showMessage("Open Dictionaries & sources to install an offline dictionary")
        else:
            self.statusBar().showMessage("Offline library ready · data stays on this device")
        if hasattr(self, "char_view"):
            self.show_character(self.current_char, activate=False)
        if self.analysis_window and self.analysis_window.isVisible():
            self.analysis_window.model.script_conflict.cache_clear()
            self.analysis_window.refresh()

    def closeEvent(self, event):
        if self.data_dialog and self.data_dialog.worker and self.data_dialog.worker.isRunning():
            self.data_dialog.cancel()
            self.statusBar().showMessage("Cancelling dictionary installation safely. Close again when it finishes.")
            event.ignore()
            return
        self._closing = True
        self.timer.stop()
        self.generation += 1  # Reject queued results before closing the databases.
        for worker in self.workers:
            worker.requestInterruption()
            worker.wait()
        self.autocomplete.shutdown()
        if self.handwriting_window:
            self.handwriting_window.shutdown()
        if self.analysis_window:
            self.analysis_window.shutdown()
        if self.analysis_popup:
            self.analysis_popup.hide()
        self.db.close()
        event.accept()
