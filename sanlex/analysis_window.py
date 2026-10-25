"""Modeless character inspector with three independent regional views."""
from html import escape
import math
import re
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPalette
from PySide6.QtWidgets import (QApplication,QCheckBox,QComboBox,QDialog,QHBoxLayout,
    QLabel,QLineEdit,QPushButton,QScrollArea,QSlider,QSplitter,QTabBar,QTabWidget,QTextBrowser,QVBoxLayout,QWidget)

from .stroke_widget import StrokeCanvas
from .strokes import CharacterAnalysis, MODES, StrokeStore
from .text import is_han, radical_label
from .fonts import REGIONAL_FONT_CSS, font_style, language_html


def link(kind,value,label=None,large=False):
    return f'<a href="{kind}:{quote(value,safe="")}"' + (' style="font-size:29px"' if large else '') + '>' + escape(label or value) + '</a>'


def document(body, language='jp'):
    return '<html><head><style>body {' + font_style(language) + '''
        color:#203c36;background:#fffef9;font-size:14px;margin:12px;line-height:1.5;}
        h2 {font-size:18px;color:#214b40;margin:8px 0;} h3 {font-size:15px;margin:10px 0 3px;}
        p {margin:5px 0 10px;} a {color:#236e60;text-decoration:none;}
        .muted {color:#6d7b73;font-size:12px;} td {padding:5px;}''' + REGIONAL_FONT_CSS + '</style></head><body>' + body + '</body></html>'


class AnalysisPopup(QDialog):
    return_requested = Signal()

    def closeEvent(self, event):
        self.return_requested.emit()
        event.accept()

    def reject(self):
        self.close()


class AnalysisWindow(QDialog):
    entry_requested = Signal(str)
    explorer_requested = Signal(str)
    character_changed = Signal()
    character_changing = Signal()
    popout_requested = Signal()

    def __init__(self,db,filter_provider,parent=None,*,embedded=False):
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle('Character analysis · SanLex')
        self.setModal(False)
        self.resize(850,850)
        self.setMinimumSize(420,380) if embedded else self.setMinimumSize(700,770)
        self.db, self.filter_provider = db, filter_provider
        self.store = StrokeStore()
        self.model = CharacterAnalysis(db,self.store)
        self.root_char, self.char = '', ''
        self.mode = db.preference('character-analysis-mode','ja')
        if self.mode not in MODES:
            self.mode = 'ja'
        self.history, self.history_index = [], -1
        self.word_limit, self.parent_limit = 40,100
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8) if embedded else layout.setContentsMargins(16,12,16,12)
        if embedded:
            self.setStyleSheet('QPushButton {padding:5px 7px;} QTabBar::tab {padding:8px 9px;}'
                               'QTextBrowser {padding:7px;} QCheckBox {padding:2px;spacing:4px;}')
        row = QHBoxLayout()
        self.back = QPushButton('← Back')
        self.forward = QPushButton('Forward →')
        self.back.clicked.connect(lambda: self.travel(-1))
        self.forward.clicked.connect(lambda: self.travel(1))
        row.addWidget(self.back)
        row.addWidget(self.forward)
        if embedded:
            self.back.hide()
            self.forward.hide()
        self.input = QLineEdit()
        self.input.setMaximumWidth(90)
        self.input.setStyleSheet('QLineEdit {padding:6px;font-size:19px;}')
        self.input.setMaxLength(2)  # Qt counts UTF-16 units; extension-plane Han use two.
        self.input.setAccessibleName('Character to analyse')
        self.input.returnPressed.connect(self.explore_input)
        row.addWidget(self.input)
        explore = QPushButton('Analyse')
        explore.clicked.connect(self.explore_input)
        row.addWidget(explore)
        row.addStretch()
        copy = QPushButton('Copy')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.char))
        row.addWidget(copy)
        atlas = QPushButton('Full explorer')
        atlas.clicked.connect(lambda: self.explorer_requested.emit(self.char))
        row.addWidget(atlas)
        self.popout_button = QPushButton('Pop out ↗')
        self.popout_button.setAccessibleName('Pop out character analysis')
        self.popout_button.clicked.connect(self.popout_requested)
        self.popout_button.setVisible(embedded)
        if embedded:
            row.addWidget(self.popout_button)
        layout.addLayout(row)
        self.modes = QTabBar()
        self.modes.setExpanding(True)
        for key,(title,_) in MODES.items():
            self.modes.addTab({'hans':'Simplified', 'hant':'Traditional', 'ja':'Japanese'}[key] if embedded else title)
            self.modes.setTabToolTip(self.modes.count()-1,title)
        self.modes.setCurrentIndex(list(MODES).index(self.mode))
        self.modes.currentChanged.connect(self.mode_changed)
        layout.addWidget(self.modes)
        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel('Character form'))
        self.variants = QComboBox()
        self.variants.setMinimumWidth(125)
        self.variants.setStyleSheet('QComboBox {padding:4px 8px;min-height:23px;}')
        self.variants.setAccessibleName('Regional character form')
        self.variants.currentIndexChanged.connect(self.variant_changed)
        variant_row.addWidget(self.variants)
        self.variant_note = QLabel()
        self.variant_note.setWordWrap(True)
        self.variant_note.setObjectName('muted')
        variant_row.addWidget(self.variant_note,1)
        if embedded:
            self.variant_note.hide()
        layout.addLayout(variant_row)
        upper = QHBoxLayout()
        drawing = QVBoxLayout()
        self.canvas = StrokeCanvas()
        self.canvas.setFixedSize(180,180) if embedded else self.canvas.setFixedSize(240,240)
        drawing.addWidget(self.canvas,0,Qt.AlignmentFlag.AlignHCenter)
        controls = QHBoxLayout()
        self.restart = QPushButton('↺')
        self.previous = QPushButton('◀')
        self.play = QPushButton('Play')
        self.next = QPushButton('▶')
        self.finish = QPushButton('End')
        for button,tip in [(self.restart,'Restart from the first stroke'),(self.previous,'Previous stroke'),
                           (self.play,'Play or pause animation'),(self.next,'Next stroke'),(self.finish,'Show all strokes')]:
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setStyleSheet('QPushButton {padding:6px 9px;}')
            controls.addWidget(button)
        self.restart.clicked.connect(lambda: (self.canvas.pause(),self.canvas.set_position(0)))
        self.previous.clicked.connect(lambda: self.canvas.step(-1))
        self.play.clicked.connect(self.toggle_play)
        self.next.clicked.connect(lambda: self.canvas.step(1))
        self.finish.clicked.connect(lambda: (self.canvas.pause(),self.canvas.set_position(len(self.canvas.paths))))
        drawing.addLayout(controls)
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setAccessibleName('Stroke playback position')
        self.progress.sliderPressed.connect(self.canvas.pause)
        self.progress.valueChanged.connect(lambda value: self.canvas.set_position(value/100) if not self._loading else None)
        drawing.addWidget(self.progress)
        settings = QHBoxLayout()
        self.counter = QLabel()
        settings.addWidget(self.counter)
        settings.addStretch()
        settings.addWidget(QLabel('Speed'))
        self.speed = QComboBox()
        self.speed.setStyleSheet('QComboBox {padding:3px 6px;min-height:20px;}')
        for label,value in [('0.5×',0.5),('1×',1.0),('1.5×',1.5),('2×',2.0)]:
            self.speed.addItem(label,value)
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(lambda: setattr(self.canvas,'speed',self.speed.currentData()))
        settings.addWidget(self.speed)
        drawing.addLayout(settings)
        upper.addLayout(drawing)
        self.info = self.browser()
        upper.addWidget(self.info,1)
        stroke_page = QWidget()
        palette = stroke_page.palette()
        palette.setColor(QPalette.ColorRole.Window,QColor('#fffef9'))
        palette.setColor(QPalette.ColorRole.WindowText,QColor('#202c32'))
        stroke_page.setPalette(palette)
        stroke_page.setAutoFillBackground(True)
        stroke_layout = QVBoxLayout(stroke_page)
        stroke_layout.setContentsMargins(0,0,0,0)
        stroke_layout.addLayout(upper)
        options = QHBoxLayout()
        for title,field,checked in [('Grid','grid',True),('Stroke numbers','numbers',True),
                                    ('Outline guide','shadow',True),('Loop','loop',False)]:
            check = QCheckBox(title)
            check.setChecked(checked)
            check.toggled.connect(lambda value,f=field: (setattr(self.canvas,f,value),self.canvas.update()))
            options.addWidget(check)
        options.addStretch()
        self.nested = QCheckBox('Include nested parts')
        self.nested.toggled.connect(self.refresh_parents)
        if not embedded:
            options.addWidget(self.nested)
        stroke_layout.addLayout(options)
        self.availability = QLabel()
        self.availability.setWordWrap(True)
        self.availability.setObjectName('muted')
        stroke_layout.addWidget(self.availability)
        stroke_layout.addStretch()
        self.details = QTabWidget()
        self.details.setMinimumHeight(140 if embedded else 200)
        self.parts, self.part_of, self.words = self.browser(), self.browser(), self.browser()
        self.parts.setAccessibleName('Parts of this character')
        self.part_of.setAccessibleName('Characters this is part of')
        self.parts_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.parts_splitter.setChildrenCollapsible(False)
        for view in (self.parts,self.part_of):
            view.setMinimumWidth(150)
            self.parts_splitter.addWidget(view)
        self.parts_splitter.setStretchFactor(0,1)
        self.parts_splitter.setStretchFactor(1,1)
        self.parts_splitter.setSizes([400,400])
        self.parts_splitter.setHandleWidth(7)
        self.parts_splitter.setStyleSheet('QSplitter::handle {background:#d7ded7;}')
        self.details.addTab(self.parts_splitter,'Parts / Part of')
        self.details.addTab(self.words,'Words containing this character')
        if embedded:
            stroke_scroll = QScrollArea()
            stroke_scroll.setWidgetResizable(True)
            stroke_scroll.setWidget(stroke_page)
            self.details.insertTab(0,stroke_scroll,'Strokes / readings')
            self.details.setTabText(1,'Parts / Part of')
            self.details.setTabText(2,'Words')
            parts_page = QWidget()
            parts_layout = QVBoxLayout(parts_page)
            parts_layout.setContentsMargins(0,0,0,0)
            parts_layout.addWidget(self.nested)
            self.details.removeTab(1)
            parts_layout.addWidget(self.parts_splitter,1)
            self.details.insertTab(1,parts_page,'Parts / Part of')
            self.details.setCurrentIndex(0)
        else:
            layout.addWidget(stroke_page)
        layout.addWidget(self.details,1)
        attribution = QLabel('Stroke shapes: AnimCJK © FM&SH / Arphic · No warranty · Redistributable under the Arphic Public License. '
                             'Data, licences and original files are included in the application folder.')
        attribution.setWordWrap(True)
        attribution.setObjectName('muted')
        if embedded:
            attribution.setToolTip(attribution.text())
            attribution.setText('AnimCJK · Offline strokes · Source and licences in Dictionaries & sources')
        layout.addWidget(attribution)
        self.canvas.position_changed.connect(self.position_changed)
        self.canvas.playing_changed.connect(lambda playing: self.play.setText('Pause' if playing else 'Play'))
        for shortcut,callback in ([] if embedded else [('Alt+Left',lambda:self.travel(-1)),('Alt+Right',lambda:self.travel(1))]):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def browser(self):
        browser = QTextBrowser()
        browser.setOpenLinks(False)
        browser.anchorClicked.connect(self.handle_link)
        return browser

    def reject(self):
        if not self.embedded:
            super().reject()

    def explore_input(self):
        char = self.input.text().strip()
        if is_han(char):
            self.show_character(char)
        else:
            self.input.setToolTip('Enter one kanji or hanzi.')

    def show_character(self,char,mode=None,selected=None,record_history=True):
        if not is_han(char):
            return
        mode = mode or self.mode
        if mode not in MODES:
            mode = 'ja'
        variants = self.model.variants(char,mode)
        selected = selected if selected in variants else variants[0]
        changed = (self.root_char,self.mode,self.char) != (char,mode,selected)
        if changed:
            self.character_changing.emit()
            self.word_limit, self.parent_limit = 40,100
        self._loading = True
        self.root_char, self.mode, self.char = char,mode,selected
        self.modes.setCurrentIndex(list(MODES).index(mode))
        self.input.setText(char)
        self.variants.clear()
        for candidate in variants:
            self.variants.addItem(f'{candidate} · U+{ord(candidate):04X}',candidate)
        self.variants.setCurrentIndex(variants.index(selected))
        self.variants.setEnabled(len(variants)>1)
        self.variant_note.setText('Multiple forms are recorded; choose the intended character.' if len(variants)>1 else
                                 (f'From {char}: {MODES[mode][0]} form.' if char != selected else 'Same character codepoint; regional glyphs and stroke order may differ.'))
        self.variants.setToolTip(self.variant_note.text())
        self.setWindowTitle(f'{selected} · {MODES[mode][0]} · Character analysis · SanLex')
        self._loading = False
        self.db.set_preference('character-analysis-mode',mode)
        self.refresh()
        state = (char,mode,selected)
        if record_history and (self.history_index<0 or self.history[self.history_index] != state):
            self.history = self.history[:self.history_index+1] + [state]
            self.history = self.history[-100:]
            self.history_index = len(self.history)-1
        self.back.setEnabled(self.history_index>0)
        self.forward.setEnabled(self.history_index<len(self.history)-1)
        self.character_changed.emit()

    def snapshot(self):
        return {'root': self.root_char, 'mode': self.mode, 'char': self.char,
                'detail': self.details.currentIndex(), 'nested': self.nested.isChecked(),
                'word_limit': self.word_limit, 'parent_limit': self.parent_limit,
                'position': self.canvas.position,
                'scrolls': [view.verticalScrollBar().value() for view in (self.info,self.parts,self.part_of,self.words)]}

    def restore(self, state):
        self.nested.setChecked(state['nested'])
        self.show_character(state['root'],state['mode'],state['char'],record_history=False)
        self.word_limit, self.parent_limit = state['word_limit'],state['parent_limit']
        self.refresh_words()
        self.refresh_parents()
        self.details.setCurrentIndex(state['detail'])
        self.canvas.set_position(state['position'])
        for view,position in zip((self.info,self.parts,self.part_of,self.words),state['scrolls']):
            view.verticalScrollBar().setValue(position)

    def mode_changed(self,index):
        if not self._loading and self.root_char:
            self.show_character(self.root_char,list(MODES)[index])

    def variant_changed(self,index):
        if not self._loading and self.root_char and index>=0:
            self.show_character(self.root_char,self.mode,self.variants.currentData())

    def travel(self,delta):
        index = self.history_index+delta
        if 0 <= index < len(self.history):
            self.history_index = index
            self.show_character(*self.history[index],record_history=False)

    def refresh(self):
        if not self.char:
            return
        record = self.store.record(self.char,self.mode)
        self.progress.setMaximum(len(record['graphics']['strokes'])*100 if record else 0)
        self.canvas.load(self.char,self.mode,record['graphics'] if record else None)
        for control in (self.restart,self.previous,self.play,self.next,self.finish,self.progress,self.speed):
            control.setEnabled(bool(record))
        self.availability.setText((f"{len(self.canvas.paths)} strokes · AnimCJK · {MODES[self.mode][1]} · Installed offline" if record else
            f'No {MODES[self.mode][0]} stroke animation is installed for {self.char}. The grey character is a font preview. '
            'Traditional Chinese animation coverage is smaller.' if self.mode=='hant' else
            f'No {MODES[self.mode][0]} stroke animation is installed for {self.char}. The grey character is a font preview.'))
        self.refresh_info(record)
        self.refresh_parts()
        self.refresh_parents()
        self.refresh_words()

    def refresh_info(self,record):
        data = self.db.character(self.char)
        uni,kan = data['unihan'],data['kanjidic']
        meta = record['metadata'] if record else {}
        body = f'<p class="muted">{escape(MODES[self.mode][1])} · U+{ord(self.char):04X}</p><h2>{escape(self.char)}</h2>'
        meanings = '; '.join(kan.get('meanings',[])) if self.mode=='ja' else uni.get('kDefinition','')
        body += '<p>' + escape(meanings or meta.get('definition') or uni.get('kDefinition') or 'No definition in installed character data.') + '</p>'
        if self.mode=='ja':
            fields = [('On readings',' · '.join(kan.get('on',[])) or uni.get('kJapaneseOn')),
                      ('Kun readings',' · '.join(kan.get('kun',[])) or uni.get('kJapaneseKun')),
                      ('Name readings',' · '.join(kan.get('nanori',[]))),
                      ('School grade',kan.get('grade')),('Frequency rank',kan.get('frequency'))]
        else:
            fields = [('Mandarin',uni.get('kMandarin')),('Cantonese',uni.get('kCantonese'))]
        for label,value in fields:
            if value:
                body += f'<h3>{label}</h3><p>{escape(str(value))}</p>'
        radical = meta.get('radical') or (' / '.join(radical_label(n) for n in kan.get('radicals',[])) if self.mode=='ja' else '')
        if radical:
            body += '<h3>Dictionary radical</h3><p>' + escape(radical) + '</p>'
        if uni.get('kRSUnicode'):
            body += '<p class="muted">Unicode radical / additional strokes: ' + escape(uni['kRSUnicode']) + '</p>'
        if self.mode!='ja':
            body += '<p class="muted">Readings and meanings: Unicode Unihan. Mandarin readings apply across both Chinese tabs.</p>'
        body += '<p class="muted"><a href="https://github.com/parsimonhi/animCJK">AnimCJK source &amp; coverage</a></p>'
        self.info.setHtml(document(body, self.mode))

    def refresh_parts(self):
        parts = self.model.components(self.char,self.mode)
        body = '<h2>Parts</h2><p>' + (' &nbsp; '.join(link('char',c,large=True) for c in parts) or 'No parts recorded for this form.') + '</p>'
        for expression,source in self.model.structures(self.char,self.mode):
            body += '<p>' + escape(expression) + ' <span class="muted">' + escape(source) + '</span></p>'
        body += '<h3>Related character forms</h3>'
        uni = self.db.character(self.char)['unihan']
        for field,label in [('kSimplifiedVariant','Simplified'),('kTraditionalVariant','Traditional'),('kSemanticVariant','Semantic')]:
            chars = list(dict.fromkeys(chr(int(code,16)) for code in re.findall(r'U\+([0-9A-Fa-f]+)',uni.get(field,''))))
            if chars:
                body += '<p>' + label + ': ' + ' · '.join(link('char',c,large=True) for c in chars) + '</p>'
        body += '<p class="muted">Click a part to analyse it. Parts describe written structure; they are distinct from dictionary radicals. '
        body += 'Japanese and Chinese variants are not always interchangeable. Shared IDS structures are labelled when no regional decomposition is available.</p>'
        self.parts.setHtml(document(body, self.mode))

    def refresh_parents(self):
        if not self.char:
            return
        parents,more = self.model.parents(self.char,self.mode,self.nested.isChecked(),self.parent_limit)
        body = '<h2>Part of</h2><p>' + (' &nbsp; '.join(link('char',c,c+(' ↗' if not direct else ''),True) for c,direct in parents) or 'No parent characters recorded for this regional form.') + '</p>'
        body += '<p class="muted">Regional AnimCJK structures, with matching or shared IDS structures for other characters. ↗ = nested relationship.</p>'
        if more:
            body += '<p>' + link('parentsmore',self.char,'Show 100 more characters') + '</p>'
        self.part_of.setHtml(document(body, self.mode))

    def refresh_words(self):
        if not self.char:
            return
        words = self.model.words(self.char,self.mode,self.word_limit+1,**self.filter_provider())
        body = '<p class="muted">' + ('Japanese' if self.mode=='ja' else MODES[self.mode][0]) + ' words containing ' + escape(self.char) + ' · Current dictionary and direction filters apply.</p>'
        if words:
            body += '<table width="100%">'
            for word in words[:self.word_limit]:
                body += '<tr><td>' + language_html(link('entry',word['id'],word['display_word']) + '<br><span class="muted">' + escape(word['reading']) + '</span>', word['lang']) + '</td><td>'
                body += language_html(escape('; '.join(word['glosses'][:2])[:250]), word['definition_lang']) + '<br><span class="muted">' + escape(word['source']) + ' · '
                body += word['lang'].upper() + ' → ' + word['definition_lang'].upper() + '</span></td></tr>'
            body += '</table>'
        else:
            body += '<p>No matching words in the selected dictionaries and directions.</p>'
        if len(words)>self.word_limit:
            body += '<p>' + link('wordsmore',self.char,'Show 40 more word entries') + '</p>'
        self.words.setHtml(document(body, self.mode))

    def toggle_play(self):
        self.canvas.pause() if self.canvas.timer.isActive() else self.canvas.play()

    def position_changed(self,value):
        self.progress.blockSignals(True)
        self.progress.setValue(round(value*100))
        self.progress.blockSignals(False)
        self.counter.setText(f'{math.ceil(value)} / {len(self.canvas.paths)} strokes')

    def handle_link(self,url):
        kind = url.scheme()
        value = unquote(url.toString().split(':',1)[1])
        if kind=='char':
            self.show_character(value)
        elif kind=='entry':
            self.entry_requested.emit(value)
        elif kind=='parentsmore':
            self.parent_limit += 100
            self.refresh_parents()
        elif kind=='wordsmore':
            self.word_limit += 40
            self.refresh_words()
        elif kind=='https':
            QDesktopServices.openUrl(url)

    def hideEvent(self,event):
        self.canvas.pause()
        super().hideEvent(event)

    def shutdown(self):
        self.canvas.pause()
        self.close()
        self.store.close()
