"""Embedded, asynchronous multi-component character finder."""
from html import escape
import json
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from .db import Dictionary
from .fonts import REGIONAL_FONT_CSS, language_html
from .text import parse_components


def document(body):
    return '<html><head><style>body {color:#25453e;font-family:"Segoe UI";font-size:13px;}' + REGIONAL_FONT_CSS + \
        'td {padding:5px;} a {color:#286a55;text-decoration:none;}</style></head><body>' + body + '</body></html>'


def glyph_link(scheme, char, title=''):
    return language_html(f'<a href="{scheme}:{quote(char, safe="")}" title="{escape(title, quote=True)}" '
                         f'style="font-size:28px">{escape(char)}</a>', 'jp')


class ComponentWorker(QThread):
    result = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, path, generation, selected, recursive, limit, catalog, parent):
        super().__init__(parent)
        self.path, self.generation = path, generation
        self.selected, self.recursive, self.limit, self.catalog = selected, recursive, limit, catalog

    def run(self):
        db = None
        try:
            db = Dictionary(self.path, read_only=True)
            db.conn.set_progress_handler(lambda: int(self.isInterruptionRequested()), 1000)
            catalog = db.component_catalog() if self.catalog else None
            rows, more = db.find_by_components(self.selected, self.recursive, self.limit)
            if not self.isInterruptionRequested():
                self.result.emit(self.generation, {'catalog': catalog, 'rows': rows, 'more': more})
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(self.generation, str(error))
        finally:
            if db:
                db.close()


class ComponentSearch(QWidget):
    character_selected = Signal(str)
    state_changed = Signal()
    details_requested = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setObjectName('componentSearch')
        self.setStyleSheet('QWidget#componentSearch {background:#fffef9;}')
        self.path = path
        self.selected = []
        self.catalog = None
        self.limit, self.palette_limit = 80, 120
        self.generation = 0
        self.workers = []
        self.pending = self.closing = self.restoring = False
        self.needs_search = False
        self._wanted_strokes = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.start_search)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        heading = QHBoxLayout()
        heading.addWidget(QLabel('Find by components'), 1)
        details = QPushButton('← Details')
        details.clicked.connect(self.details_requested)
        heading.addWidget(details)
        layout.addLayout(heading)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('Add components, e.g. 木 + 目')
        self.input.setAccessibleName('Components to add')
        self.input.setMaxLength(64)
        self.input.returnPressed.connect(self.add_input)
        row.addWidget(self.input, 1)
        add = QPushButton('Add')
        add.clicked.connect(self.add_input)
        row.addWidget(add)
        clear = QPushButton('Clear')
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        layout.addLayout(row)
        self.selection = QLabel('No components selected')
        self.selection.setWordWrap(True)
        self.selection.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                               Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.selection.setToolTip('Click a selected component to remove it.')
        self.selection.linkActivated.connect(lambda url: self.toggle(unquote(url.split(':', 1)[1])))
        layout.addWidget(self.selection)
        options = QHBoxLayout()
        self.nested = QCheckBox('Include nested parts')
        self.nested.setChecked(True)
        self.nested.toggled.connect(self.selection_changed)
        options.addWidget(self.nested)
        options.addStretch()
        self.strokes = QComboBox()
        self.strokes.setAccessibleName('Filter component palette by stroke count')
        self.strokes.addItem('Any recorded strokes', 'all')
        self.strokes.setToolTip('Recorded KANJIDIC2 / Unihan counts; regional component glyphs can differ.')
        self.strokes.currentIndexChanged.connect(self.palette_changed)
        options.addWidget(self.strokes)
        layout.addLayout(options)
        self.palette = QTextBrowser()
        self.palette.setAccessibleName('Choose character components')
        self.palette.setOpenLinks(False)
        self.palette.anchorClicked.connect(lambda url: self.toggle(unquote(url.toString().split(':', 1)[1])))
        self.palette.setMinimumHeight(95)
        self.palette.setStyleSheet('QTextBrowser {padding:4px;}')
        self.palette_more = QPushButton('More components')
        self.palette_more.setToolTip('Show 120 more components')
        self.palette_more.clicked.connect(self.more_components)
        self.palette_more.hide()
        self.status = QLabel('Choose one or more components to find characters.')
        self.status.setWordWrap(True)
        self.results = QTextBrowser()
        self.results.setAccessibleName('Characters matching every selected component')
        self.results.setOpenLinks(False)
        self.results.anchorClicked.connect(lambda url: self.character_selected.emit(unquote(url.toString().split(':', 1)[1])))
        self.results.setStyleSheet('QTextBrowser {padding:4px;}')
        self.more = QPushButton('More matches')
        self.more.setToolTip('Show 80 more characters')
        self.more.clicked.connect(self.more_results)
        self.more.hide()
        browsers = QHBoxLayout()
        for title, view, more in (('Choose parts', self.palette, self.palette_more),
                                  ('Matching characters', self.results, self.more)):
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            column.addWidget(view, 1)
            column.addWidget(more)
            browsers.addLayout(column, 1)
        layout.addLayout(browsers, 1)
        layout.addWidget(self.status)
        note = QLabel('Matches contain every selected part. Uses IDS across regions; shapes can vary. Word filters do not restrict this search.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#687d7c;font-size:12px;')
        layout.addWidget(note)

    def activate(self):
        if self.catalog is None or self.needs_search:
            self.schedule()

    def reload(self):
        self.generation += 1
        self.timer.stop()
        for worker in self.workers:
            worker.requestInterruption()
        self.catalog = None
        self.pending = False
        self.needs_search = True
        if self.isVisible():
            self.schedule()

    def add_input(self):
        try:
            selected = parse_components([*self.selected, self.input.text()])
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.input.clear()
        self.selected = selected
        self.selection_changed()

    def toggle(self, char):
        try:
            self.selected = parse_components([c for c in self.selected if c != char] if char in self.selected else [*self.selected, char])
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.selection_changed()

    def clear(self):
        self.selected = []
        self.input.clear()
        self.selection_changed()

    def render_selection(self):
        self.selection.setText(' &nbsp; + &nbsp; '.join(
            f'<a href="remove:{quote(c, safe="")}" style="color:#286a55;font-size:20px">{escape(c)} ×</a>'
            for c in self.selected) or 'No components selected')

    def selection_changed(self):
        if self.restoring:
            return
        self.limit = 80
        self.render_selection()
        self.render_palette()
        self.schedule()

    def schedule(self):
        if self.closing:
            return
        self.generation += 1
        for worker in self.workers:
            worker.requestInterruption()
        self.pending = True
        self.needs_search = False
        if self.catalog is None:
            self.palette.setHtml(document('Loading component palette…'))
            self.palette_more.hide()
        self.status.setText('Searching components…' if self.selected else 'Choose one or more components to find characters.')
        self.results.clear()
        self.more.hide()
        self.timer.start(0)
        self.state_changed.emit()

    def start_search(self):
        if self.closing:
            return
        if len(self.workers) >= 2:
            self.timer.start(40)
            return
        worker = ComponentWorker(self.path, self.generation, tuple(self.selected), self.nested.isChecked(),
                                 self.limit, self.catalog is None, self)
        self.workers.append(worker)
        worker.result.connect(self.receive)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda w=worker: self.finished(w))
        worker.start()

    def receive(self, generation, payload):
        if self.closing or generation != self.generation:
            return
        self.pending = False
        if payload['catalog'] is not None:
            self.catalog = payload['catalog']
            wanted = self._wanted_strokes if self._wanted_strokes is not None else self.strokes.currentData()
            self._wanted_strokes = None
            blocked = self.strokes.blockSignals(True)
            self.strokes.clear()
            self.strokes.addItem('Any recorded strokes', 'all')
            for count in sorted({r['strokes'] for r in self.catalog if r['strokes'] is not None}):
                self.strokes.addItem(f'{count} strokes', count)
            self.strokes.addItem('Unknown stroke count', 'unknown')
            self.strokes.setCurrentIndex(max(0, self.strokes.findData(wanted)))
            self.strokes.blockSignals(blocked)
        self.render_palette()
        rows = payload['rows']
        cells = []
        for row in rows:
            uni, kan = json.loads(row['unihan'] or '{}'), json.loads(row['kanjidic'] or '{}')
            title = uni.get('kDefinition') or '; '.join(kan.get('meanings', [])) or 'Open character details'
            reading = ' · '.join([*kan.get('on', []), *kan.get('kun', [])])
            cells.append(glyph_link('character', row['parent'], title + (' · ' + reading if reading else '')))
        self.results.setHtml(document(self.grid(cells, 4)))
        if not self.catalog:
            self.status.setText('No component data installed. Install IDS in Dictionaries & sources.')
        elif not self.selected:
            self.status.setText('Choose one or more components to find characters.')
        elif rows:
            self.status.setText(f"{len(rows)} characters shown · contains {' + '.join(self.selected)}" +
                                (' · including nested parts' if self.nested.isChecked() else ' · direct parts only'))
        else:
            self.status.setText('No recorded matches contain every selected part. Remove a part or enable nested parts; regional forms and data coverage can differ.')
        self.more.setVisible(payload['more'])
        self.state_changed.emit()

    @staticmethod
    def grid(cells, columns):
        rows = ['<tr>' + ''.join(f'<td align="center" width="{100 // columns}%">{c}</td>' for c in cells[i:i+columns]) + '</tr>'
                for i in range(0, len(cells), columns)]
        return '<table width="100%">' + ''.join(rows) + '</table>'

    def render_palette(self):
        if self.catalog is None:
            return
        count = self.strokes.currentData()
        rows = [r for r in self.catalog if count == 'all' or (r['strokes'] is None if count == 'unknown' else r['strokes'] == count)]
        cells = []
        for row in rows[:self.palette_limit]:
            title = f"{row['char']} · {row['uses']} recorded parent characters"
            title += f" · {row['strokes']} strokes" if row['strokes'] is not None else ' · stroke count unavailable'
            cell = glyph_link('part', row['char'], title)
            cells.append('<span style="background-color:#dfebe2">' + cell + ' ✓</span>' if row['char'] in self.selected else cell)
        self.palette.setHtml(document(self.grid(cells, 4) if cells else 'No components with this stroke count.'))
        self.palette_more.setVisible(len(rows) > self.palette_limit)

    def palette_changed(self):
        if self.restoring:
            return
        self.palette_limit = 120
        self.render_palette()
        self.state_changed.emit()

    def more_components(self):
        position = self.palette.verticalScrollBar().value()
        self.palette_limit += 120
        self.render_palette()
        self.palette.verticalScrollBar().setValue(position)
        self.state_changed.emit()

    def more_results(self):
        self.limit += 80
        self.schedule()

    def failed(self, generation, message):
        if not self.closing and generation == self.generation:
            self.pending = False
            self.status.setText('Component search failed: ' + message)
            self.state_changed.emit()

    def finished(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)
        worker.deleteLater()

    def snapshot(self):
        return {'selected': list(self.selected), 'nested': self.nested.isChecked(), 'input': self.input.text(),
                'limit': self.limit, 'palette_limit': self.palette_limit, 'strokes': self.strokes.currentData(),
                'html': self.results.toHtml(), 'status': self.status.text(), 'more': not self.more.isHidden(),
                'scroll': self.results.verticalScrollBar().value(), 'palette_scroll': self.palette.verticalScrollBar().value(),
                'pending': self.pending or self.needs_search}

    def restore(self, state, active=True):
        self.timer.stop()
        self.generation += 1
        for worker in self.workers:
            worker.requestInterruption()
        self.restoring = True
        try:
            self.selected = list(state['selected'])
            self.nested.setChecked(state['nested'])
            self.input.setText(state['input'])
            self.limit, self.palette_limit = state['limit'], state['palette_limit']
            self.strokes.setCurrentIndex(max(0, self.strokes.findData(state['strokes'])))
            self._wanted_strokes = state['strokes'] if self.catalog is None else None
            self.render_selection()
            self.render_palette()
            self.results.setHtml(state['html'])
            self.status.setText(state['status'])
            self.more.setVisible(state['more'])
            self.pending = False
            self.needs_search = state['pending']
        finally:
            self.restoring = False
        generation = self.generation

        def scroll():
            if self.generation == generation:
                self.results.verticalScrollBar().setValue(state['scroll'])
                self.palette.verticalScrollBar().setValue(state['palette_scroll'])
        QTimer.singleShot(0, scroll)
        if active and (state['pending'] or self.catalog is None):
            self.schedule()

    def shutdown(self):
        self.closing = True
        self.generation += 1
        self.timer.stop()
        for worker in self.workers:
            worker.requestInterruption()
        for worker in self.workers:
            worker.wait()
