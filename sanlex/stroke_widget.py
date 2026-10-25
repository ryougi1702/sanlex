"""Native Qt stroke animation using AnimCJK outlines and median polylines."""
import math
import re

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


def outline_path(text):
    tokens = re.findall(r'[MQCZ]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',text)
    path, index, command = QPainterPath(), 0, None
    arity = {'M':2,'Q':4,'C':6}
    while index < len(tokens):
        if tokens[index] in ('M','Q','C','Z'):
            command = tokens[index]
            index += 1
        if command == 'Z':
            path.closeSubpath()
            command = None
            continue
        if command not in arity:
            raise ValueError('Unsupported stroke path')
        size = arity[command]
        values = [float(n) for n in tokens[index:index+size]]
        if len(values) != size:
            raise ValueError('Incomplete stroke path')
        index += size
        if command == 'M':
            path.moveTo(*values)
        elif command == 'Q':
            path.quadTo(*values)
        else:
            path.cubicTo(*values)
    return path


def partial_median(points, fraction):
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(*points[0])
    lengths = [math.dist(a,b) for a,b in zip(points,points[1:])]
    remaining = sum(lengths) * max(0,min(1,fraction))
    for a,b,length in zip(points,points[1:],lengths):
        if length <= remaining:
            path.lineTo(*b)
            remaining -= length
        else:
            t = remaining / length if length else 0
            path.lineTo(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)
            break
    return path


class StrokeCanvas(QWidget):
    position_changed = Signal(float)
    playing_changed = Signal(bool)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(235,235)
        self.setAccessibleName('Animated character stroke order')
        self.paths, self.medians = [], []
        self.char, self.mode = '', 'ja'
        self.position = 0.0
        self.speed = 1.0
        self.grid, self.numbers, self.shadow, self.loop = True, True, True, False
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.clock = QElapsedTimer()

    def load(self,char,mode,graphics):
        self.pause()
        self.char, self.mode = char, mode
        self.paths = [outline_path(d) for d in graphics['strokes']] if graphics else []
        self.medians = graphics['medians'] if graphics else []
        self.set_position(len(self.paths))

    def set_position(self,position):
        self.position = max(0,min(float(len(self.paths)),position))
        self.position_changed.emit(self.position)
        self.update()

    def play(self):
        if not self.paths:
            return
        if self.position >= len(self.paths):
            self.set_position(0)
        self.clock.start()
        self.timer.start()
        self.playing_changed.emit(True)

    def pause(self):
        self.timer.stop()
        self.playing_changed.emit(False)

    def step(self,delta):
        self.pause()
        boundary = math.ceil(self.position - 1e-6) if delta < 0 else math.floor(self.position + 1e-6)
        self.set_position(boundary + delta)

    def tick(self):
        delta = min(self.clock.restart(),100) / 1000 * self.speed / 0.85
        self.set_position(self.position + delta)
        if self.position >= len(self.paths):
            if self.loop:
                self.set_position(0)
            else:
                self.pause()

    def hideEvent(self,event):
        self.pause()
        super().hideEvent(event)

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(),self.height()) - 10
        x, y = (self.width()-size)/2, (self.height()-size)/2
        painter.fillRect(QRectF(x,y,size,size),QColor('#fffef9'))
        painter.setPen(QPen(QColor('#d7ded7'),1))
        painter.drawRect(QRectF(x,y,size,size))
        if self.grid:
            painter.setPen(QPen(QColor('#dce2da'),1,Qt.PenStyle.DashLine))
            for offset in (0.25,0.5,0.75):
                painter.drawLine(QPointF(x+size*offset,y),QPointF(x+size*offset,y+size))
                painter.drawLine(QPointF(x,y+size*offset),QPointF(x+size,y+size*offset))
        if not self.paths:
            family = {'ja':'Yu Mincho','hans':'Microsoft YaHei','hant':'Microsoft JhengHei'}[self.mode]
            painter.setFont(QFont(family,int(size*0.46)))
            painter.setPen(QColor('#b6c2b8'))
            painter.drawText(QRectF(x,y,size,size),Qt.AlignmentFlag.AlignCenter,self.char)
            return
        painter.translate(x,y)
        painter.scale(size/1024,size/1024)
        # AnimCJK's graphics files use the Make Me a Hanzi coordinate convention.
        painter.translate(0,900)
        painter.scale(1,-1)
        for i,path in enumerate(self.paths):
            if self.shadow:
                painter.fillPath(path,QColor('#e4e7df'))
            if i+1 <= self.position:
                painter.fillPath(path,QColor('#183b36'))
            elif i < self.position and i < len(self.medians):
                painter.save()
                painter.setClipPath(path)
                painter.setPen(QPen(QColor('#c26b36'),140,Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(partial_median(self.medians[i],self.position-i))
                painter.restore()
        if self.numbers:
            painter.scale(1,-1)
            painter.setFont(QFont('Segoe UI',27,QFont.Weight.Bold))
            for i,points in enumerate(self.medians):
                if not points:
                    continue
                px,py = points[0]
                point = QPointF(px-12,-py-14)
                painter.setPen(QPen(QColor('#fffef9'),6))
                label = QPainterPath()
                label.addText(point,painter.font(),str(i+1))
                painter.drawPath(label)
                painter.fillPath(label,QColor('#a55b30'))
