from PySide6 import QtCore, QtGui, QtWidgets


class CardView(QtWidgets.QWidget):
    clicked = QtCore.Signal(object)

    def __init__(self, parent=None, data=None):
        super().__init__(parent)

        self.data = data

        # Add a background color to ensure that the drop shadow effect is visible
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QtGui.QColor(255, 255, 255))
        self.setPalette(pal)

        self._set_shadow(10, (0, 3))

        self.headline_label = QtWidgets.QLabel("Headline", self)
        self.headline_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.headline_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.text_label1 = QtWidgets.QLabel("Extra Information 1", self)
        self.text_label1.setStyleSheet("font-size: 12px;")

        self.text_label2 = QtWidgets.QLabel("Extra Information 2", self)
        self.text_label2.setStyleSheet("font-size: 10px;")

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.headline_label)
        self.layout.addWidget(self.text_label1)
        self.layout.addWidget(self.text_label2)
        self.layout.addStretch()
        self.setLayout(self.layout)

        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover)

        self.setMinimumHeight(self.layout.sizeHint().height())

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.rect().contains(event.localPos().toPoint()):
            self.clicked.emit(self.data)
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(224, 224, 224))
        brush = QtGui.QBrush(QtGui.QColor(255, 255, 255))
        painter.setPen(pen)
        painter.setBrush(brush)
        rect = QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = min(rect.width(), rect.height()) / 12
        painter.drawRoundedRect(rect, radius, radius)

    def minimumSizeHint(self):
        return QtCore.QSize(0, self.layout.sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_size = event.size()
        self.resize(new_size.width(), self.minimumHeight())

    def _set_shadow(self, radius: float, offset: tuple[float, float]):
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(radius)
        shadow.setColor(QtGui.QColor(0, 0, 0, 100))
        shadow.setOffset(offset[0], offset[1])
        self.setGraphicsEffect(shadow)

    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.HoverEnter:
            self._set_shadow(20, (0, 6))
            return True
        elif event.type() == QtCore.QEvent.Type.HoverLeave:
            self._set_shadow(10, (0, 3))
            return True
        return super().event(event)
