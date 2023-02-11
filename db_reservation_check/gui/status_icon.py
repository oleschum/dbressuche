from PySide6 import QtWidgets, QtCore, QtGui
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.join("..", os.path.dirname(__file__))))


class SearchStatusIcon(QtWidgets.QPushButton):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.success_icon_path = os.path.join(BASE_DIR, "assets", "success_icon.svg")
        self.fail_icon_path = os.path.join(BASE_DIR, "assets", "fail_icon.svg")
        self._size = 25
        self.setIcon(QtGui.QIcon(self.success_icon_path))
        self.setIconSize(QtCore.QSize(self._size, self._size))
        self.setFixedSize(QtCore.QSize(self._size, self._size))
        self.setStyleSheet(
            "QPushButton {background-color: #00ffffff; border-width: 0px; margin: 0px;}")
        self.setToolTip("Keine Fehler.")
        self.callback_func = None

    def setSuccess(self):
        self.setIcon(QtGui.QIcon(self.success_icon_path))
        self.setIconSize(QtCore.QSize(self._size, self._size))
        self.setFixedSize(QtCore.QSize(self._size, self._size))
        self.setToolTip("Keine Fehler.")
        try:
            self.clicked.disconnect(self.callback_func)
        except RuntimeError:
            pass

    def setFailure(self):
        self.setIcon(QtGui.QIcon(self.fail_icon_path))
        self.setIconSize(QtCore.QSize(self._size, self._size))
        self.setFixedSize(QtCore.QSize(self._size, self._size))
        self.setToolTip("Es sind Fehler aufgetreten. Für Details klicken.")
        self.clicked.connect(self.callback_func)
