from PySide6 import QtWidgets, QtCore, QtGui
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

class UrlDialog(QtWidgets.QDialog):

    def __init__(self, *args, **kwargs):
        super(UrlDialog, self).__init__(*args, **kwargs)
        self.url_label = QtWidgets.QTextEdit()
        self.url_label.setText("")
        #self.url_label.setWordWrap(True)
        self.url_label.setFixedWidth(500)

        image_label = QtWidgets.QLabel()
        pixmap = QtGui.QPixmap(os.path.join(BASE_DIR, "assets", "happy_train.png"))
        pixmap = pixmap.scaled(300, 300)
        image_label.setPixmap(pixmap)
        image_label.setFixedSize(300, 300)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(image_label)
        layout.addWidget(self.url_label)

        self.setLayout(layout)
        self.setWindowTitle("Such-Url")



# dialog = QtWidgets.QDialog()
#         version = db_reservation_check.__version__
#         about_text = """
#         <p align='center'><font size='5'><b>DB Reservierungssuche</b></font></p><br>
#
#         <font size='3'>
#         Diese Applikation steht in keinem Zusammenhang mit dem Unternehmen "Deutsche Bahn AG",
#         einer ihrer Tochtergesellschaften oder einer sonstigen offiziellen oder inoffiziellen
#         Stelle der Deutschen Bahn AG.<br>
#
#         Es handelt sich bei diesem Programm um ein privates Hobbyprojekt.<br>
#         Alle Angaben ohne Gewähr.<br>
#         Über diese Applikation sind keine Buchungen oder Reservierungen möglich.<br><br>
#
#         Erstellt von Ole Schumann, 2023.<br>""" + \
#                      "Version {}<br>".format(version) + \
#                      """Abbildungen wurden durch DALL-E (OpenAI) erstellt.</font>
#                      """
#         text_label = QtWidgets.QLabel()
#         text_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
#         text_label.setText(about_text)
#         text_label.setWordWrap(True)
#         text_label.setFixedWidth(500)
#
#         image_label = QtWidgets.QLabel()
#         pixmap = QtGui.QPixmap(os.path.join(BASE_DIR, "assets", "happy_train.png"))
#         pixmap = pixmap.scaled(300, 300)
#         image_label.setPixmap(pixmap)
#         image_label.setFixedSize(300, 300)
#
#         layout = QtWidgets.QHBoxLayout()
#         layout.addWidget(image_label)
#         layout.addWidget(text_label)
#
#         dialog.setLayout(layout)
#         dialog.setWindowTitle("Über")
#
#         dialog.exec()