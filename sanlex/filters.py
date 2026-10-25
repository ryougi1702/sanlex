"""Word dictionary and headword/definition direction selectors."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)
from .importers import SOURCES

LANGUAGES = {'en': 'English', 'jp': 'Japanese', 'cn': 'Chinese'}
DIRECTIONS = [(origin, target) for origin in LANGUAGES for target in LANGUAGES]
WORD_SOURCES = ['jmdict', 'cedict', 'wiktionary-ja', 'wiktionary-zh']
SOURCE_NAMES = {'jmdict': 'JMdict', 'cedict': 'CC-CEDICT',
                'wiktionary-ja': 'Japanese Wiktionary', 'wiktionary-zh': 'Chinese Wiktionary'}


class FilterPanel(QWidget):
    changed = Signal()
    reset_requested = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName('filterPanel')
        self._updating = False
        self.preferences = db.preference('word-filters', {})
        self.source_checks = {}
        self.direction_checks = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName('count')
        layout.addWidget(self.summary)
        explanation = QLabel('Select dictionaries and directions. Both filters apply together.')
        explanation.setWordWrap(True)
        explanation.setObjectName('muted')
        layout.addWidget(explanation)
        reset = QPushButton('Reset all filters')
        reset.clicked.connect(self.reset_requested)
        layout.addWidget(reset)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName('filterPanel')
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.addLayout(self.group_header('Dictionary files', 'sources'))
        self.source_layout = QVBoxLayout()
        self.source_layout.setSpacing(2)
        content_layout.addLayout(self.source_layout)
        content_layout.addSpacing(8)
        self.corpus_check = QCheckBox('Tatoeba example sentences')
        self.corpus_check.toggled.connect(self.selection_changed)
        content_layout.addWidget(self.corpus_check)
        self.corpus_detail = QLabel()
        self.corpus_detail.setWordWrap(True)
        self.corpus_detail.setObjectName('muted')
        content_layout.addWidget(self.corpus_detail)
        content_layout.addSpacing(12)
        content_layout.addLayout(self.group_header('Translation direction', 'directions'))
        direction_help = QLabel('Headword language → definition language\nJP → JP = Japanese definitions\nUnavailable directions are greyed out.')
        direction_help.setWordWrap(True)
        direction_help.setObjectName('muted')
        content_layout.addWidget(direction_help)
        grid = QGridLayout()
        grid.setSpacing(1)
        for i, pair in enumerate(DIRECTIONS):
            check = QCheckBox(f'{pair[0].upper()} → {pair[1].upper()}')
            check.setStyleSheet('QCheckBox {font-size:12px;padding:4px 0px;spacing:4px;}'
                               'QCheckBox:disabled {color:#9aa299;}'
                               'QCheckBox::indicator:disabled {background:#e6e9e1;border:1px solid #d8dfd5;}')
            check.setAccessibleName(f'{LANGUAGES[pair[0]]} headwords with {LANGUAGES[pair[1]]} definitions')
            check.toggled.connect(self.selection_changed)
            self.direction_checks[pair] = check
            grid.addWidget(check, i // 3, i % 3)
        content_layout.addLayout(grid)
        content_layout.addSpacing(12)
        note = QLabel('These filters apply to words and related definitions/translations. Character readings, radicals and structures remain available from KANJIDIC2, Unihan and IDS.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        content_layout.addWidget(note)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.reload()

    def group_header(self, text, group):
        row = QHBoxLayout()
        title = QLabel(text)
        title.setObjectName('sourceTitle')
        row.addWidget(title, 1)
        for caption, selected in [('All', True), ('None', False)]:
            button = QPushButton(caption)
            button.setObjectName('example')
            button.setToolTip(f'{caption} {text.lower()}')
            button.clicked.connect(lambda checked=False, g=group, s=selected: self.select_group(g, s))
            row.addWidget(button)
        return row

    def reload(self):
        self._updating = True
        self.stats = self.db.source_directions()
        totals = {}
        for row in self.stats:
            totals[row['source']] = totals.get(row['source'], 0) + row['entries']
        self.source_totals = totals
        while item := self.source_layout.takeAt(0):
            if item.widget():
                item.widget().deleteLater()
        self.source_checks = {}
        for source in [*WORD_SOURCES, *sorted(set(totals) - set(WORD_SOURCES))]:
            container = QWidget()
            container.setObjectName('filterPanel')
            column = QVBoxLayout(container)
            column.setContentsMargins(0, 0, 0, 4)
            column.setSpacing(0)
            check = QCheckBox(SOURCE_NAMES.get(source, source))
            count = totals.get(source, 0)
            check.setEnabled(count > 0)
            check.setChecked(count > 0 and self.preferences.get('sources', {}).get(source, True))
            check.toggled.connect(self.selection_changed)
            self.source_checks[source] = check
            column.addWidget(check)
            filename = SOURCES.get(source, {}).get('filename', source)
            detail = QLabel(f'{filename}\n{count:,} word entries' if count else f'{filename} · not installed')
            detail.setWordWrap(True)
            detail.setObjectName('muted')
            check.setToolTip(detail.text())
            column.addWidget(detail)
            self.source_layout.addWidget(container)
        for pair, check in self.direction_checks.items():
            check.setChecked(self.preferences.get('directions', {}).get('>'.join(pair), True))
        corpus = self.db.sources().get('tatoeba')
        self.corpus_check.setEnabled(bool(corpus))
        self.corpus_check.setChecked(bool(corpus) and self.preferences.get('tatoeba',True))
        self.corpus_detail.setText(f"{corpus['entries']:,} offline sentences · separate from word dictionaries" if corpus else
                                  'Not installed · add through Dictionaries & sources')
        self._updating = False
        self.update_summary()

    def selected_sources(self):
        return tuple(source for source, check in self.source_checks.items() if check.isChecked())

    def selected_directions(self):
        return tuple(pair for pair, check in self.direction_checks.items() if check.isChecked())

    def signature(self):
        return (self.selected_sources(), self.selected_directions(),self.corpus_check.isChecked())

    def persist(self):
        self.preferences['sources'] = {**self.preferences.get('sources', {}),
                                      **{source: check.isChecked() for source, check in self.source_checks.items()
                                         if self.source_totals.get(source, 0)}}
        self.preferences['directions'] = {'>'.join(pair): check.isChecked() for pair, check in self.direction_checks.items()}
        if self.corpus_check.isEnabled():
            self.preferences['tatoeba'] = self.corpus_check.isChecked()
        self.db.set_preference('word-filters', self.preferences)

    def update_summary(self):
        selected = self.selected_sources()
        directions = self.selected_directions()
        files = 'All word dictionaries' if len(selected) == len(self.source_totals) else f"{len(selected)} {'dictionary' if len(selected) == 1 else 'dictionaries'}"
        pairs = 'All directions' if len(directions) == len(DIRECTIONS) else f"{len(directions)} {'direction' if len(directions) == 1 else 'directions'}"
        self.summary.setText(f'{files} · {pairs}')
        counts = {pair: 0 for pair in DIRECTIONS}
        for row in self.stats:
            if row['source'] in selected:
                pair = (row['lang'], row['definition_lang'])
                if pair in counts:
                    counts[pair] += row['entries']
        for pair, check in self.direction_checks.items():
            check.setEnabled(counts[pair] > 0)
            check.setToolTip(f'{LANGUAGES[pair[0]]} headwords → {LANGUAGES[pair[1]]} definitions\n'
                             f'{counts[pair]:,} entries in the selected dictionaries')

    def selection_changed(self):
        if not self._updating:
            self.update_summary()
            self.persist()
            self.changed.emit()

    def select_group(self, group, selected):
        self._updating = True
        checks = self.source_checks if group == 'sources' else self.direction_checks
        for key, check in checks.items():
            check.setChecked(selected and (group != 'sources' or self.source_totals.get(key, 0) > 0))
        self._updating = False
        self.selection_changed()

    def restore_selection(self, sources, directions, corpus=None):
        self._updating = True
        for source, check in self.source_checks.items():
            check.setChecked(source in sources)
        for pair, check in self.direction_checks.items():
            check.setChecked(pair in directions)
        if corpus is not None:
            self.corpus_check.setChecked(corpus and self.corpus_check.isEnabled())
        self._updating = False
        self.update_summary()

    def reset_selection(self):
        self._updating = True
        for source, check in self.source_checks.items():
            check.setChecked(self.source_totals.get(source, 0) > 0)
        for check in self.direction_checks.values():
            check.setChecked(True)
        self.corpus_check.setChecked(self.corpus_check.isEnabled())
        self._updating = False
        self.selection_changed()
