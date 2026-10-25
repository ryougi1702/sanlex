"""Debounced, cancellable native completion popup for dictionary entry prefixes."""
import time

from PySide6.QtCore import QEvent,QModelIndex,QObject,QRect,Qt,QThread,QTimer,Signal
from PySide6.QtGui import QStandardItem,QStandardItemModel
from PySide6.QtWidgets import QCompleter

from .db import Dictionary
from .fonts import entry_font

ROW_ROLE=Qt.ItemDataRole.UserRole+1


class SuggestionWorker(QThread):
    result=Signal(int,object)

    def __init__(self,path,query,language,generation,filters,parent=None):
        super().__init__(parent)
        self.path,self.query,self.language=path,query,language
        self.generation,self.filters=generation,filters

    def run(self):
        db=None
        try:
            db=Dictionary(self.path,read_only=True)
            deadline=time.monotonic()+0.18
            db.conn.set_progress_handler(lambda:int(self.isInterruptionRequested() or time.monotonic()>deadline),1000)
            rows=db.autocomplete(self.query,self.language,10,**self.filters)
            if not self.isInterruptionRequested():
                self.result.emit(self.generation,rows)
        except Exception:
            if not self.isInterruptionRequested():
                self.result.emit(self.generation,[])
        finally:
            if db:
                db.close()


class EntryCompleter(QCompleter):
    def __init__(self,controller):
        super().__init__(controller)
        self.controller=controller

    def pathFromIndex(self,index):
        row=index.data(ROW_ROLE)
        if row:
            # QLineEdit may update its text before activated() is emitted. Retain
            # the payload across the consequent model invalidation.
            self.controller.pending=row
            return row['headword']
        return ''


class Autocomplete(QObject):
    selected=Signal(object)

    def __init__(self,edit,path,context,parent=None):
        super().__init__(parent)
        self.edit,self.path,self.context=edit,path,context
        self.generation=0
        self.workers=[]
        self.pending=None
        self.composing=False
        self.closing=False
        self.dismissed=True
        self.request_key=None
        self.model=QStandardItemModel(self)
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(130)
        self.timer.timeout.connect(self.start)
        self.edit.textChanged.connect(self.invalidate)
        self.edit.textEdited.connect(self.edited)
        self.completer=EntryCompleter(self)
        self.completer.setModel(self.model)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setMaxVisibleItems(10)
        self.completer.setWrapAround(False)
        self.completer.activated[QModelIndex].connect(self.accept)
        # Manage insertion ourselves: QLineEdit.setCompleter() rewrites text on
        # highlighting, which would invalidate this asynchronous model mid-click.
        self.completer.setWidget(self.edit)
        self.edit.installEventFilter(self)
        popup=self.completer.popup()
        popup.installEventFilter(self)
        popup.setAccessibleName('Dictionary suggestions')
        popup.setUniformItemSizes(True)
        popup.setTextElideMode(Qt.TextElideMode.ElideRight)
        popup.setStyleSheet('QListView {background:#fffef9;color:#25453e;border:1px solid #aabeb2;'
                            'font-size:14px;padding:3px;} QListView::item {padding:8px 10px;}'
                            'QListView::item:selected {background:#dfebe2;color:#163e32;}')

    def key(self):
        language,filters=self.context()
        return (self.edit.text(),language,tuple(filters['sources']),tuple(filters['directions']))

    def invalidate(self,*args):
        self.generation+=1
        self.timer.stop()
        for worker in self.workers:
            worker.requestInterruption()
        self.model.clear()
        self.completer.popup().hide()

    def schedule(self,*args):
        self.dismissed=False
        if not self.closing and not self.composing and self.edit.text().strip():
            self.timer.start(130)

    def edited(self,text):
        # Qt emits textEdited before textChanged. Arm after the latter has
        # invalidated the old query, and reject edits already submitted/dismissed.
        self.dismissed=False
        QTimer.singleShot(0,lambda:self.schedule() if self.edit.text()==text and not self.dismissed else None)

    def context_changed(self,*args):
        self.invalidate()
        if self.edit.hasFocus() and not self.dismissed:
            self.schedule()

    def start(self):
        if self.closing or self.composing or self.dismissed or not self.edit.hasFocus() or not self.edit.text().strip():
            return
        if len(self.workers)>=2:
            self.timer.start(40)
            return
        self.pending=None
        self.request_key=self.key()
        language,filters=self.context()
        worker=SuggestionWorker(self.path,self.edit.text().strip(),language,self.generation,filters,self)
        self.workers.append(worker)
        worker.result.connect(self.receive)
        worker.finished.connect(lambda w=worker:self.finished(w))
        worker.start()

    def receive(self,generation,rows):
        if self.closing or self.dismissed or self.composing or generation!=self.generation or self.request_key!=self.key() or not self.edit.hasFocus():
            return
        self.model.clear()
        for row in rows:
            reading=' · '+row['reading'] if row['reading'] and row['reading']!=row['headword'] else ''
            title=f"{row['headword']}{reading}    {row['lang'].upper()} → {row['definition_lang'].upper()}"
            if row['gloss']:
                title+='  — '+row['gloss']
            item=QStandardItem(title)
            item.setFont(entry_font(row['lang'], self.completer.popup().font()))
            item.setEditable(False)
            item.setData(row,ROW_ROLE)
            item.setToolTip(f"{row['headword']} · {row['source']}\n{row['gloss']}")
            self.model.appendRow(item)
        if rows:
            self.completer.setCompletionPrefix(self.edit.text())
            self.completer.complete(QRect(0,self.edit.height(),self.edit.width(),1))
            self.completer.popup().setCurrentIndex(QModelIndex())

    def finished(self,worker):
        if worker in self.workers:
            self.workers.remove(worker)
        worker.deleteLater()

    def accept(self,index):
        row=index.data(ROW_ROLE) if index.isValid() else None
        row=row or self.pending
        self.dismiss()
        if row:
            self.selected.emit(row)

    def dismiss(self):
        self.dismissed=True
        self.invalidate()

    def eventFilter(self,watched,event):
        if watched in (self.edit,self.completer.popup()) and event.type()==QEvent.Type.KeyPress:
            if event.key()==Qt.Key.Key_Escape:
                self.dismiss()
                return True
            if event.key() in (Qt.Key.Key_Up,Qt.Key.Key_Down) and self.completer.popup().isVisible():
                popup=self.completer.popup()
                current=popup.currentIndex()
                row=current.row() if current.isValid() else (-1 if event.key()==Qt.Key.Key_Down else popup.model().rowCount())
                row=max(0,min(popup.model().rowCount()-1,row+(1 if event.key()==Qt.Key.Key_Down else -1)))
                index=popup.model().index(row,0)
                popup.setCurrentIndex(index)
                popup.scrollTo(index)
                return True
            if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Tab) and self.completer.popup().isVisible():
                index=self.completer.popup().currentIndex()
                if index.isValid():
                    self.accept(index)
                    return True
                self.dismiss()
        if watched is self.edit:
            if event.type()==QEvent.Type.InputMethod:
                self.composing=bool(event.preeditString())
                if self.composing:
                    self.invalidate()
            elif event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Escape:
                self.dismiss()
            elif event.type()==QEvent.Type.FocusOut:
                if not self.completer.popup().isVisible():
                    self.dismiss()
            elif event.type()==QEvent.Type.Hide:
                self.dismiss()
        return super().eventFilter(watched,event)

    def shutdown(self):
        self.closing=True
        self.dismiss()
        for worker in list(self.workers):
            worker.wait()
