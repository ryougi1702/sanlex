"""Embedded, asynchronous multi-component character finder."""
from html import escape
import json
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSize
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                              QListView, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)

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
    insert_requested = Signal(str)
    close_requested = Signal()
    state_changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setObjectName('componentSearch')
        self.setStyleSheet('QWidget#componentSearch {background:#fffef9;} QPushButton {padding:5px 7px;} '
                          'QComboBox {padding:5px 7px;min-width:90px;} QLabel {font-size:12px;} '
                          'QLineEdit {padding:6px;font-size:14px;}')
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
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        title = QLabel('Search by components')
        title.setStyleSheet('font-size:15px;font-weight:600;color:#214b40;')
        title.setToolTip('Choose parts on the left, then select a match to look up or insert. '
                         'Matches contain every selected part. IDS structures and stroke counts can vary by region; word filters do not restrict this search.')
        heading.addWidget(title, 1)
        self.hide_button = QPushButton('Hide ×')
        self.hide_button.setAccessibleName('Hide component search panel')
        self.hide_button.clicked.connect(self.close_requested)
        heading.addWidget(self.hide_button)
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
        self.selection = title
        self.selection.setWordWrap(True)
        self.selection.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                               Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.selection.setToolTip('Click a selected component to remove it.')
        self.selection.linkActivated.connect(lambda url: self.toggle(unquote(url.split(':', 1)[1])))
        options = QHBoxLayout()
        self.nested = QCheckBox('Nested parts')
        self.nested.setToolTip('Include parts inside other components, such as 木 inside 相 inside 想.')
        self.nested.setChecked(True)
        self.nested.toggled.connect(self.selection_changed)
        options.addWidget(self.nested)
        options.addStretch()
        self.strokes = QComboBox()
        self.strokes.setAccessibleName('Filter component palette by stroke count')
        self.strokes.addItem('All stroke counts', 'all')
        self.strokes.setToolTip('Recorded KANJIDIC2 / Unihan counts; regional component glyphs can differ.')
        self.strokes.currentIndexChanged.connect(self.palette_changed)
        options.addWidget(self.strokes)
        layout.addLayout(options)
        self.palette = QTextBrowser()
        self.palette.setAccessibleName('Choose character components')
        self.palette.setOpenLinks(False)
        self.palette.anchorClicked.connect(lambda url: self.toggle(unquote(url.toString().split(':', 1)[1])))
        self.palette.setMinimumSize(110, 48)
        self.palette.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.palette.setStyleSheet('QTextBrowser {padding:4px;}')
        self.palette_more = QPushButton('More')
        self.palette_more.setToolTip('Show 120 more components')
        self.palette_more.clicked.connect(self.more_components)
        self.palette_more.hide()
        self.status = QLabel('Choose one or more components to find characters.')
        self.status.setWordWrap(True)
        self.results = QListWidget()
        self.results.setAccessibleName('Characters matching every selected component')
        self.results.setViewMode(QListView.ViewMode.IconMode)
        self.results.setResizeMode(QListView.ResizeMode.Adjust)
        self.results.setMovement(QListView.Movement.Static)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setGridSize(QSize(43, 43))
        self.results.setStyleSheet("QListWidget {background:#fffef9;font-size:27px;font-family:'Yu Gothic UI','Microsoft YaHei';} "
                                   'QListWidget::item {padding:2px;margin:1px;}')
        self.results.setMinimumSize(110, 48)
        self.results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.results.currentItemChanged.connect(self.candidate_changed)
        self.results.itemActivated.connect(lambda *_: self.lookup())
        self.more = QPushButton('More')
        self.more.setToolTip('Show 80 more characters')
        self.more.clicked.connect(self.more_results)
        self.more.hide()
        browsers = QHBoxLayout()
        for title, view, more in (('Parts', self.palette, self.palette_more),
                                  ('Matches', self.results, self.more)):
            column = QVBoxLayout()
            caption = QHBoxLayout()
            caption.addWidget(QLabel(title), 1)
            caption.addWidget(more)
            column.addLayout(caption)
            column.addWidget(view, 1)
            if view is self.results:
                actions = QHBoxLayout()
                self.lookup_button = QPushButton('Look up')
                self.lookup_button.setObjectName('primary')
                self.lookup_button.clicked.connect(self.lookup)
                self.insert_button = QPushButton('Insert')
                self.insert_button.setToolTip('Insert at the search cursor, replacing selected text, and clear the selected parts.')
                self.insert_button.clicked.connect(self.insert)
                actions.addWidget(self.lookup_button)
                actions.addWidget(self.insert_button)
                column.addLayout(actions)
            browsers.addLayout(column, 1)
        layout.addLayout(browsers, 1)
        layout.addWidget(self.status)
        self.candidate_changed()

    def candidate_changed(self, *_):
        enabled = self.results.currentItem() is not None
        self.lookup_button.setEnabled(enabled)
        self.insert_button.setEnabled(enabled)

    def lookup(self):
        item = self.results.currentItem()
        if item:
            self.character_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def insert(self):
        item = self.results.currentItem()
        if item:
            self.insert_requested.emit(item.data(Qt.ItemDataRole.UserRole))
            self.clear()

    def fill_candidates(self, rows, selected=None):
        self.results.clear()
        for row in rows:
            item = QListWidgetItem(row['char'])
            item.setData(Qt.ItemDataRole.UserRole, row['char'])
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(row['tooltip'])
            self.results.addItem(item)
            if row['char'] == selected:
                self.results.setCurrentItem(item)
        self.candidate_changed()

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
            f'<a href="remove:{quote(c, safe="")}" style="color:#286a55;font-size:16px">{escape(c)} ×</a>'
            for c in self.selected) or 'Search by components')

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
            self.strokes.addItem('All stroke counts', 'all')
            for count in sorted({r['strokes'] for r in self.catalog if r['strokes'] is not None}):
                self.strokes.addItem(f'{count} strokes', count)
            self.strokes.addItem('Unknown strokes', 'unknown')
            self.strokes.setCurrentIndex(max(0, self.strokes.findData(wanted)))
            self.strokes.blockSignals(blocked)
        self.render_palette()
        rows = payload['rows']
        candidates = []
        for row in rows:
            uni, kan = json.loads(row['unihan'] or '{}'), json.loads(row['kanjidic'] or '{}')
            title = uni.get('kDefinition') or '; '.join(kan.get('meanings', [])) or 'Open character details'
            reading = ' · '.join([*kan.get('on', []), *kan.get('kun', [])])
            candidates.append({'char': row['parent'], 'tooltip': title + (' · ' + reading if reading else '')})
        self.fill_candidates(candidates)
        if not self.catalog:
            self.status.setText('No component data installed. Install IDS in Dictionaries & sources.')
        elif not self.selected:
            self.status.setText('Choose one or more components to find characters.')
        elif rows:
            self.status.setText(f"{len(rows)} matches" +
                                (' · including nested parts' if self.nested.isChecked() else ' · direct parts only'))
        else:
            self.status.setText('No matches. Remove a part or enable nested parts.')
        self.more.setVisible(payload['more'])
        self.state_changed.emit()

    @staticmethod
    def grid(cells, columns):
        rows = ['<tr>' + ''.join(f'<td align="center">{c}</td>' for c in cells[i:i+columns]) + '</tr>'
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
        self.palette.setHtml(document(self.grid(cells, 3) if cells else 'No components with this stroke count.'))
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
                'candidates': [{'char': self.results.item(i).text(), 'tooltip': self.results.item(i).toolTip()}
                               for i in range(self.results.count())],
                'candidate': self.results.currentItem().text() if self.results.currentItem() else None,
                'status': self.status.text(), 'more': not self.more.isHidden(),
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
            self.fill_candidates(state['candidates'], state['candidate'])
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

    def hideEvent(self, event):
        self.timer.stop()
        self.generation += 1
        for worker in self.workers:
            worker.requestInterruption()
        self.needs_search = self.needs_search or self.pending
        self.pending = False
        super().hideEvent(event)
