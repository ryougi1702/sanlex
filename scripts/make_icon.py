"""Create the Windows app icon using Qt's native system font renderer."""
from pathlib import Path
import struct
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


def make_icon(destination: Path):
    app = QApplication.instance() or QApplication([])
    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#173e34'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 256, 256, 48, 48)
    painter.setPen(QColor('#f2e5bf'))
    painter.setFont(QFont('Yu Gothic', 125, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, '言')
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, 'PNG')
    png = bytes(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(struct.pack('<HHH', 0, 1, 1) +
        struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png), 22) + png)


if __name__ == '__main__':
    make_icon(Path(__file__).resolve().parents[1] / 'assets/icon.ico')
