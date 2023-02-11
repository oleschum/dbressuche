from PySide6 import QtWidgets, QtCore, QtGui


class TextShimmerAnimation(QtWidgets.QLabel):

    def __init__(self, parent, width, height):
        super(TextShimmerAnimation, self).__init__(parent)
        self.setFixedWidth(width)
        self.setFixedHeight(height)

        self.color1 = QtGui.QColor("#616161")
        self.color2 = QtGui.QColor("#8e8e8e")

        self._animation = QtCore.QVariantAnimation(self)

        self._animation.setStartValue(1e-5)
        self._animation.setEndValue(1 - 1e-5)
        self._animation.setDuration(1500)
        self._animation.valueChanged.connect(self._animate)
        self._animation.setLoopCount(-1)

    def _interpolate_color(self, color1: QtGui.QColor, color2: QtGui.QColor, value: float) -> QtGui.QColor:
        w1 = value
        w2 = 1 - w1
        r = color1.red() * w1 + w2 * color2.red()
        g = color1.green() * w1 + w2 * color2.green()
        b = color1.blue() * w1 + w2 * color2.blue()
        return QtGui.QColor(int(r), int(g), int(b))

    def _animate(self, value):
        if value > 0.33:
            pass
        value = min(value * 3, 1 - 1e-5)

        if value < 0.5:
            scaled_val = min(value / 0.5, 1 - 1e-5)
            qss = "background-color: " \
                  "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0," \
                  " stop:0 {color1}, stop:{value} {color2}, stop: 1.0 {color1});".format(color1=self.color1.name(),
                                                                                         color2=self.color2.name(),
                                                                                         value=scaled_val)
        else:
            scaled_val = min((value - 0.5) / 0.5, 1 - 1e-5)
            interpolated_color = self._interpolate_color(self.color1, self.color2, scaled_val)
            qss = "background-color: " \
                  "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0," \
                  " stop:0 {color1}, stop: 1.0 {interp_col});".format(color1=self.color1.name(),
                                                                      interp_col=interpolated_color.name())

        self.setStyleSheet(qss)

    def anim_start(self):
        self.setVisible(True)
        self._animation.start()

    def anim_stop(self):
        self._animation.stop()
        self.setVisible(False)
