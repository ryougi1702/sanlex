"""Native drawing pad and asynchronous, local handwriting candidates."""
import threading

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout,
    QLabel, QListView, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from .handwriting import HandwritingRecognizer
from .strokes import MODES


class HandwritingCanvas(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setAccessibleName('Handwriting drawing pad')
        self.setToolTip('Draw one character with a mouse, pen or touch. Lift between strokes.')
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self.strokes = []
        self.current = None
        self.input_kind = None

    def drawing_rect(self):
        side = min(self.width(), self.height()) - 12
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def point(self, position):
        rect = self.drawing_rect()
        return (max(0, min(1, (position.x() - rect.x()) / rect.width())),
                max(0, min(1, (position.y() - rect.y()) / rect.height())))

    def begin(self, position, kind):
        if self.current is not None or not self.drawing_rect().contains(position):
            return
        self.input_kind = kind
        self.current = [self.point(position)]
        self.changed.emit()  # Invalidate candidates before the pen is lifted.
        self.update()

    def move(self, position, kind):
        if self.current is not None and self.input_kind == kind:
            point = self.point(position)
            if point != self.current[-1]:
                self.current.append(point)
            self.update()

    def end(self, position, kind):
        if self.current is None or self.input_kind != kind:
            return
        self.move(position, kind)
        self.strokes.append(self.current)
        self.current, self.input_kind = None, None
        self.changed.emit()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin(event.position(), 'mouse')

    def mouseMoveEvent(self, event):
        self.move(event.position(), 'mouse')

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.end(event.position(), 'mouse')

    def tabletEvent(self, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.TabletPress:
            self.begin(event.position(), 'pen')
        elif event.type() == QEvent.Type.TabletMove:
            self.move(event.position(), 'pen')
        elif event.type() == QEvent.Type.TabletRelease:
            self.end(event.position(), 'pen')
        event.accept()

    def event(self, event):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd):
            points = event.points()
            if points:
                position = points[0].position()
                if event.type() == QEvent.Type.TouchBegin:
                    self.begin(position, 'touch')
                elif event.type() == QEvent.Type.TouchEnd:
                    self.end(position, 'touch')
                else:
                    self.move(position, 'touch')
            event.accept()
            return True
        if event.type() == QEvent.Type.TouchCancel:
            self.current, self.input_kind = None, None
            self.changed.emit()
            self.update()
            return True
        return super().event(event)

    def undo(self):
        self.current, self.input_kind = None, None
        if self.strokes:
            self.strokes.pop()
        self.changed.emit()
        self.update()

    def clear(self):
        self.strokes = []
        self.current, self.input_kind = None, None
        self.changed.emit()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.drawing_rect()
        painter.fillRect(rect, QColor('#fffef9'))
        painter.setPen(QPen(QColor('#c7d3cd'), 1))
        painter.drawRect(rect)
        painter.setPen(QPen(QColor('#dce2da'), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(rect.center().x(), rect.top()), QPointF(rect.center().x(), rect.bottom()))
        painter.drawLine(QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        if not self.strokes and self.current is None:
            painter.setPen(QColor('#8a9a91'))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, 'Draw one character here')
        painter.setPen(QPen(QColor('#183b36'), 4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for stroke in [*self.strokes, *([self.current] if self.current is not None else [])]:
            points = [QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height()) for x, y in stroke]
            if len(points) == 1:
                painter.drawPoint(points[0])
            else:
                path = QPainterPath(points[0])
                for point in points[1:]:
                    path.lineTo(point)
                painter.drawPath(path)


class RecognitionWorker(QThread):
    ready = Signal(object)
    result = Signal(int, object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.condition = threading.Condition()
        self.pending = None
        self.generation = 0

    def invalidate(self, generation):
        with self.condition:
            self.generation = generation
            self.pending = None

    def submit(self, generation, strokes, mode):
        with self.condition:
            self.generation = generation
            self.pending = (generation, strokes, mode)
            self.condition.notify()

    def run(self):
        try:
            recognizer = HandwritingRecognizer(cancelled=self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            self.ready.emit(recognizer.counts)
            while not self.isInterruptionRequested():
                with self.condition:
                    self.condition.wait_for(lambda: self.pending is not None or self.isInterruptionRequested())
                    if self.isInterruptionRequested():
                        return
                    generation, strokes, mode = self.pending
                    self.pending = None
                rows = recognizer.recognize(strokes, mode, cancelled=lambda:
                    self.isInterruptionRequested() or generation != self.generation)
                if generation == self.generation and not self.isInterruptionRequested():
                    self.result.emit(generation, rows)
        except Exception as error:
            self.failed.emit(str(error))

    def shutdown(self):
        self.requestInterruption()
        with self.condition:
            self.condition.notify()
        self.wait()


class HandwritingWindow(QDialog):
    lookup_requested = Signal(str, str)
    insert_requested = Signal(str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Handwriting lookup · SanLex')
        self.setModal(False)
        self.resize(760, 600)
        self.setMinimumSize(660, 530)
        self.db = db
        self.generation = 0
        self.counts = None
        self.error = None
        layout = QVBoxLayout(self)
        title = QLabel('Write the character you want to look up')
        title.setStyleSheet('font-size:20px;font-weight:600;color:#214b40;')
        layout.addWidget(title)
        intro = QLabel('One kanji / hanzi at a time. Lift between strokes; usual stroke order works best.\n'
                       'Recognition stays on this device. Matches are suggestions; cursive writing may be missed.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.mode = QComboBox()
        self.mode.addItem('All scripts', 'all')
        for key, (name, _) in MODES.items():
            self.mode.addItem(name, key)
        index = self.mode.findData(db.preference('handwriting-mode', 'all'))
        self.mode.setCurrentIndex(max(0, index))
        self.mode.setAccessibleName('Handwriting recognition script')
        layout.addWidget(self.mode)
        self.coverage = QLabel('Loading offline handwriting templates…')
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.canvas = HandwritingCanvas()
        left.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        self.undo_button = QPushButton('Undo stroke')
        self.undo_button.clicked.connect(self.canvas.undo)
        self.clear_button = QPushButton('Clear')
        self.clear_button.clicked.connect(self.canvas.clear)
        controls.addWidget(self.undo_button)
        controls.addWidget(self.clear_button)
        left.addLayout(controls)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.status = QLabel('Draw a character to see possible matches.')
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        self.candidates = QListWidget()
        self.candidates.setAccessibleName('Handwriting candidates')
        self.candidates.setViewMode(QListView.ViewMode.IconMode)
        self.candidates.setResizeMode(QListView.ResizeMode.Adjust)
        self.candidates.setMovement(QListView.Movement.Static)
        self.candidates.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidates.setGridSize(QSize(68, 65))
        self.candidates.setFont(QFont('Microsoft YaHei', 25))
        self.candidates.setStyleSheet("QListWidget {background:#fffef9;font-size:32px;font-family:'Microsoft YaHei';} "
                                     'QListWidget::item {padding:3px;margin:1px;}')
        self.candidates.setMinimumWidth(240)
        self.candidates.currentItemChanged.connect(self.selection_changed)
        self.candidates.itemActivated.connect(lambda *_: self.lookup())
        right.addWidget(self.candidates, 1)
        self.lookup_button = QPushButton('Look up character')
        self.lookup_button.setObjectName('primary')
        self.lookup_button.clicked.connect(self.lookup)
        self.insert_button = QPushButton('Insert into search')
        self.insert_button.setToolTip('Insert at the search cursor, replacing any selected text. Write more characters to build a word.')
        self.insert_button.clicked.connect(self.insert)
        right.addWidget(self.lookup_button)
        right.addWidget(self.insert_button)
        body.addLayout(right, 1)
        layout.addLayout(body, 1)
        hint = QLabel('Select a match, then look it up or insert it at the search cursor. Double-click a match to look it up.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(320)
        self.timer.timeout.connect(self.recognize)
        self.worker = RecognitionWorker(self)
        self.worker.ready.connect(self.loaded)
        self.worker.result.connect(self.receive)
        self.worker.failed.connect(self.failed)
        self.canvas.changed.connect(self.changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.selection_changed()
        self.changed()
        self.worker.start()

    def mode_changed(self):
        self.db.set_preference('handwriting-mode', self.mode.currentData())
        self.update_coverage()
        self.changed()

    def loaded(self, counts):
        self.counts = counts
        self.update_coverage()
        self.changed()

    def update_coverage(self):
        if self.counts is None:
            return
        mode = self.mode.currentData()
        detail = 'Traditional Chinese has a smaller template set. Try All scripts if a match is missing.' if mode == 'hant' else 'Coverage is limited to the bundled stroke pack.'
        self.coverage.setText(f'{self.counts[mode]:,} characters · Offline shape matching. {detail}')

    def changed(self):
        self.generation += 1
        self.worker.invalidate(self.generation)
        self.timer.stop()
        self.candidates.clear()
        self.selection_changed()
        self.undo_button.setEnabled(bool(self.canvas.strokes))
        self.clear_button.setEnabled(bool(self.canvas.strokes) or self.canvas.current is not None)
        count = len(self.canvas.strokes)
        if self.error:
            self.status.setText(self.error)
        elif self.canvas.current is not None:
            self.status.setText('Drawing…')
        elif not count:
            self.status.setText('Draw a character to see possible matches.')
        elif self.counts is None:
            self.status.setText(f'{count} strokes · Loading offline templates…')
        else:
            self.status.setText(f'{count} strokes · Finding matches…')
            self.timer.start()

    def recognize(self):
        if self.isVisible() and self.canvas.strokes and self.canvas.current is None and not self.error:
            self.worker.submit(self.generation, [list(s) for s in self.canvas.strokes], self.mode.currentData())

    def receive(self, generation, rows):
        if generation != self.generation or not self.isVisible():
            return
        self.candidates.clear()
        for row in rows:
            item = QListWidgetItem(row['char'])
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(f"{row['char']} · {MODES[row['mode']][0]} template · possible match")
            self.candidates.addItem(item)
        self.status.setText(f'{len(self.canvas.strokes)} strokes · Select a possible match.' if rows else
                            'No matches. Try All scripts or clear and redraw the character.')

    def selection_changed(self, *args):
        selected = self.candidates.currentItem() is not None
        self.lookup_button.setEnabled(selected)
        self.insert_button.setEnabled(selected)

    def lookup(self):
        item = self.candidates.currentItem()
        if item:
            row = item.data(Qt.ItemDataRole.UserRole)
            self.lookup_requested.emit(row['char'], row['mode'])

    def insert(self):
        item = self.candidates.currentItem()
        if item:
            self.insert_requested.emit(item.data(Qt.ItemDataRole.UserRole)['char'])
            self.canvas.clear()

    def failed(self, message):
        self.error = 'Handwriting unavailable: ' + message
        self.coverage.setText(self.error)
        self.changed()

    def hideEvent(self, event):
        self.timer.stop()
        self.generation += 1
        self.worker.invalidate(self.generation)
        if self.canvas.current is not None:
            self.canvas.current, self.canvas.input_kind = None, None
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.changed()

    def shutdown(self):
        self.timer.stop()
        self.hide()
        self.worker.shutdown()
