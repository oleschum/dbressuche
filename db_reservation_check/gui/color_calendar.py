import os
from PySide6 import QtWidgets, QtCore, QtGui


class ColorCalendarWidget(QtWidgets.QCalendarWidget):

    def paintCell(self, painter: QtGui.QPainter, rect: QtCore.QRect, date: QtCore.QDate) -> None:
        if not self.minimumDate() <= date <= self.maximumDate():
            background = QtGui.QColor(os.environ.get("QTMATERIAL_SECONDARYDARKCOLOR"))
            foreground = QtGui.QColor(os.environ.get("QTMATERIAL_SECONDARYCOLOR"))
            painter.setBrush(background)
            painter.setPen(QtGui.QPen(background))
            painter.drawRect(rect)
            painter.setPen(QtGui.QPen(foreground))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             str(date.day()))
        elif date.month() != self.monthShown():
            background = QtGui.QColor(os.environ.get("QTMATERIAL_SECONDARYDARKCOLOR"))
            foreground = QtGui.QColor(os.environ.get("QTMATERIAL_SECONDARYTEXTCOLOR"))
            foreground.setAlpha(100)
            painter.setBrush(background)
            painter.setPen(QtGui.QPen(background))
            painter.drawRect(rect)
            painter.setPen(QtGui.QPen(foreground))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             str(date.day()))
        else:
            super().paintCell(painter, rect, date)
