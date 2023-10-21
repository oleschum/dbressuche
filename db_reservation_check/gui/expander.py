from PySide6 import QtCore, QtGui, QtWidgets


class Expander(QtWidgets.QWidget):
    def __init__(self, parent=None, title='', animationDuration=300):
        """
        References:
            # taken from: https://stackoverflow.com/a/56275050/3971621
        """
        super().__init__(parent=parent)

        self.animationDuration = animationDuration
        self.toggleAnimation = QtCore.QParallelAnimationGroup()
        self.contentArea = QtWidgets.QScrollArea()
        self.headerLine = QtWidgets.QFrame()
        self.toggleButton = QtWidgets.QToolButton()
        self.mainLayout = QtWidgets.QGridLayout()

        self.toggleButton.setStyleSheet("QToolButton { border: none; }")
        self.toggleButton.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggleButton.setArrowType(QtCore.Qt.RightArrow)
        self.toggleButton.setText(str(title))
        self.toggleButton.setCheckable(True)
        self.toggleButton.setChecked(False)

        self.headerLine.setFrameShape(QtWidgets.QFrame.HLine)
        self.headerLine.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.headerLine.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)

        self.contentArea.setStyleSheet("QScrollArea { border: none; }")
        self.contentArea.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        # start out collapsed
        self.contentArea.setMaximumHeight(0)
        self.contentArea.setMinimumHeight(0)
        # let the entire widget grow and shrink with its content
        self.toggleAnimation.addAnimation(QtCore.QPropertyAnimation(self, b"minimumHeight"))
        self.toggleAnimation.addAnimation(QtCore.QPropertyAnimation(self, b"maximumHeight"))
        self.toggleAnimation.addAnimation(QtCore.QPropertyAnimation(self.contentArea, b"maximumHeight"))

        self.mainLayout.setVerticalSpacing(0)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.addWidget(self.toggleButton, 0, 0, 1, 1, QtCore.Qt.AlignLeft)
        self.mainLayout.addWidget(self.headerLine, 0, 2, 1, 1)
        self.mainLayout.addWidget(self.contentArea, 1, 0, 1, 3)
        self.setLayout(self.mainLayout)

        def start_animation(checked):
            arrow_type = QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow
            direction = QtCore.QAbstractAnimation.Direction.Forward if checked else QtCore.QAbstractAnimation.Direction.Backward
            self.toggleButton.setArrowType(arrow_type)
            self.toggleAnimation.setDirection(direction)
            self.toggleAnimation.start()

        self.toggleButton.clicked.connect(start_animation)

    def setContentLayout(self, contentLayout):
        self.contentArea.destroy()
        self.contentArea.setLayout(contentLayout)
        collapsedHeight = self.sizeHint().height() - self.contentArea.maximumHeight()
        contentHeight = contentLayout.sizeHint().height()
        for i in range(self.toggleAnimation.animationCount() - 1):
            expandAnimation = self.toggleAnimation.animationAt(i)
            expandAnimation.setDuration(self.animationDuration)
            expandAnimation.setStartValue(collapsedHeight)
            expandAnimation.setEndValue(collapsedHeight + contentHeight)
        contentAnimation = self.toggleAnimation.animationAt(self.toggleAnimation.animationCount() - 1)
        contentAnimation.setDuration(self.animationDuration)
        contentAnimation.setStartValue(0)
        contentAnimation.setEndValue(contentHeight)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Expander Example")

        mainWidget = QtWidgets.QWidget()
        self.setCentralWidget(mainWidget)

        layout = QtWidgets.QVBoxLayout(mainWidget)
        layout.setContentsMargins(0, 0, 0, 0)

        expander = Expander(parent=mainWidget, title="Expandable Section")
        contentLayout = QtWidgets.QVBoxLayout()
        contentLayout.addWidget(QtWidgets.QLabel("Content 1"))
        contentLayout.addWidget(QtWidgets.QLabel("Content 2"))
        expander.setContentLayout(contentLayout)

        layout.addWidget(expander)


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    mainWindow = MainWindow()
    mainWindow.show()
    app.exec()
