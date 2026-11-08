"""Persistent application settings, applied immediately."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QPushButton, QVBoxLayout

from .handwriting_window import handwriting_engine


class SettingsDialog(QDialog):
    handwriting_engine_changed = Signal(str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle('Settings · SanLex')
        self.setMinimumWidth(480)
        self.resize(540, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        heading = QLabel('Handwriting recognition')
        heading.setObjectName('pageTitle')
        layout.addWidget(heading)
        label = QLabel('Japanese handwriting recognizer')
        layout.addWidget(label)
        self.handwriting_engine = QComboBox()
        self.handwriting_engine.setAccessibleName('Japanese handwriting recognizer')
        self.handwriting_engine.addItem('SanLex custom (default)', 'custom')
        self.handwriting_engine.addItem('KanjiCanvas', 'kanjicanvas')
        self.handwriting_engine.setCurrentIndex(self.handwriting_engine.findData(handwriting_engine(db)))
        label.setBuddy(self.handwriting_engine)
        layout.addWidget(self.handwriting_engine)
        explanation = QLabel(
            'SanLex custom uses the bundled stroke shapes and covers 7,336 Japanese characters. '
            'KanjiCanvas uses its own stroke matching and covers 2,213 Japanese kanji. '
            'Try both with your handwriting; their results and coverage differ.\n\n'
            'Chinese modes always use SanLex custom. In All scripts, choosing KanjiCanvas '
            'combines its Japanese results with SanLex Chinese results. Both run entirely offline.\n\n'
            'Changes apply immediately and are remembered when you reopen SanLex.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        explanation.ensurePolished()
        explanation.setMinimumHeight(explanation.heightForWidth(self.minimumWidth() - 44))
        attribution = QLabel('<a href="https://github.com/asdfjkl/kanjicanvas">'
                             'KanjiCanvas · Dominik Klein and Seth Clydesdale · Source &amp; licence ↗</a>')
        attribution.setWordWrap(True)
        attribution.setOpenExternalLinks(True)
        layout.addWidget(attribution)
        layout.addStretch()
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.handwriting_engine.currentIndexChanged.connect(self.save_handwriting_engine)

    def save_handwriting_engine(self, index):
        backend = self.handwriting_engine.itemData(index)
        self.db.set_preference('handwriting-engine', backend)
        self.handwriting_engine_changed.emit(backend)
