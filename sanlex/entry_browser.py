"""Entry text with optional character analysis in its native context menu."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextBrowser

from .text import is_han


class EntryBrowser(QTextBrowser):
    analysis_requested = Signal(str)

    def character_at(self, position):
        cursor = self.cursorForPosition(position)
        rect = self.cursorRect(cursor)
        if rect.top() > position.y() or rect.left() > position.x():
            cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
        start = self.cursorRect(cursor)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        end = self.cursorRect(cursor)
        text = cursor.selectedText()
        if not text or not is_han(text[0]) or not start.top() <= position.y() <= start.bottom():
            return None
        right = end.left() if start.top() == end.top() else self.viewport().width()
        return text[0] if start.left() <= position.x() < right else None

    def create_context_menu(self, position):
        menu = self.createStandardContextMenu(position)
        char = self.character_at(position)
        if char:
            menu.addSeparator()
            action = menu.addAction(f'Analyse {char}')
            action.triggered.connect(lambda: self.analysis_requested.emit(char))
        return menu

    def contextMenuEvent(self, event):
        menu = self.create_context_menu(event.pos())
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()
