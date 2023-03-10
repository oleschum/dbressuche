import os
import json
import sys
import time
import multiprocessing
import threading
from PySide6 import QtWidgets, QtCore, QtGui
import qt_material

import db_reservation_check
from db_reservation_check.db_scraper import ReservationOption, DBReservationScraper, DBConnection, SearchParameters
from db_reservation_check.gui.toggle_button import AnimatedToggle
from db_reservation_check.gui.autocomplete_lineedit import AutocompleteLineEdit
from db_reservation_check.gui.color_calendar import ColorCalendarWidget
from db_reservation_check.gui.tree_widget import ColoredBackgroundDelegate, CustomSortTreeWidgetItem
from db_reservation_check.gui.text_shimmer_anim import TextShimmerAnimation
from db_reservation_check.gui.status_icon import SearchStatusIcon
from db_reservation_check.gui.card_view import CardView
from db_reservation_check.time_helper import weekday_from_str
from db_reservation_check.updater import is_up_to_date, internet_available

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

try:
    from ctypes import windll  # Only exists on Windows.

    myappid = u'com.yaf.dbreservation'
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except ImportError:
    pass


class ProcessListener(threading.Thread):
    def __init__(self, process_done_event: threading.Event, **kwargs):
        super(ProcessListener, self).__init__(**kwargs)
        self.process_done_event = process_done_event
        self.on_computation_done_callback = lambda: None
        self.db_connection_queue = None
        self.on_new_connection_callback = lambda: None
        self.status_queue = None
        self.on_new_status_callback = lambda: None
        self.my_stop_event = threading.Event()

    def run(self):
        while True and not self.my_stop_event.is_set():
            if self.db_connection_queue is not None and not self.db_connection_queue.empty():
                self.on_new_connection_callback()
            if self.status_queue is not None and not self.status_queue.empty():
                self.on_new_status_callback()
            if self.process_done_event.is_set():
                self.on_computation_done_callback()
                break
            time.sleep(0.2)


class InternetCheckWorker(QtCore.QThread):
    status_changed = QtCore.Signal(bool)

    def run(self):
        while True:
            self.status_changed.emit(internet_available())
            time.sleep(1)


class DependencyStatus:
    NO_INTERNET = -1
    MISSING_FIREFOX = 0
    SUCCESS = 1


class QueryResults:

    def __init__(self, search_params: SearchParameters, connections: list[DBConnection]):
        self.search_params = search_params
        self.connections = connections


class DBScraperGui(QtWidgets.QMainWindow):
    new_connection = QtCore.Signal()
    new_status = QtCore.Signal()
    search_done = QtCore.Signal()
    dependency_check_done = QtCore.Signal()

    def __init__(self):
        super().__init__()

        self.load_data()
        self.found_connections = []  # type: list[DBConnection]
        self.past_queries = []  # type: list[QueryResults]
        self.current_search_params = SearchParameters()
        self.search_is_running = False
        self.current_error = ""

        self.search_process = None
        self.process_listener = None
        self.dep_check_process_listener = None

        self.result_queue = multiprocessing.Queue()
        self.status_queue = multiprocessing.Queue()
        self.dependency_check_queue = multiprocessing.Queue()

        self.new_connection.connect(lambda: self.on_new_connection(self.result_queue))
        self.new_status.connect(self.on_new_status)
        self.search_done.connect(self.on_search_done)
        self.dependency_check_done.connect(self.on_dependency_check_done)

        self._widget_min_height = 48

        self.vertical_layout = QtWidgets.QVBoxLayout()
        self.layout_grid = QtWidgets.QGridLayout()

        self.start_station = AutocompleteLineEdit(self.stations)
        self.start_station.setPlaceholderText("Von")
        self.start_station.setToolTip("Von")
        self.start_station.setMinimumHeight(self._widget_min_height)
        self.final_station = AutocompleteLineEdit(self.stations)
        self.final_station.setPlaceholderText("Nach")
        self.final_station.setToolTip("Nach")
        self.final_station.setMinimumHeight(self._widget_min_height)

        self.switch_stations = QtWidgets.QPushButton()
        self.switch_stations.setIcon(QtGui.QIcon(os.path.join(BASE_DIR, "assets", "arrows.svg")))
        self.switch_stations.setIconSize(QtCore.QSize(30, 30))
        self.switch_stations.setFixedSize(QtCore.QSize(30, 30))
        self.switch_stations.setStyleSheet(
            "QPushButton {background-color: #00ffffff; border-width: 0px; margin: 0px;}")
        # self.switch_stations.setPixmap(QtGui.QPixmap("arrows.svg"))
        self.switch_stations.clicked.connect(self.on_switch_stations)

        self.layout_grid.addWidget(self.start_station, 0, 1)
        self.layout_grid.addWidget(self.switch_stations, 0, 2)
        self.layout_grid.addWidget(self.final_station, 0, 3)

        self.date_picker = QtWidgets.QDateEdit()
        self.date_picker.setCalendarPopup(True)
        self.date_picker.setMinimumHeight(self._widget_min_height)

        cal = ColorCalendarWidget()
        cal.setVerticalHeaderFormat(QtWidgets.QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.date_picker.setCalendarWidget(cal)
        self.date_picker.calendarWidget().setMinimumWidth(400)
        self.date_picker.calendarWidget().setMinimumHeight(300)
        self.date_picker.setToolTip("Reisedatum")

        weekend_format = self.date_picker.calendarWidget().weekdayTextFormat(QtCore.Qt.DayOfWeek.Saturday)
        weekend_format.setForeground(QtGui.QColor(os.environ.get("QTMATERIAL_SECONDARYTEXTCOLOR")))
        self.date_picker.calendarWidget().setWeekdayTextFormat(QtCore.Qt.DayOfWeek.Saturday, weekend_format)
        self.date_picker.calendarWidget().setWeekdayTextFormat(QtCore.Qt.DayOfWeek.Sunday, weekend_format)
        self.date_picker.setDate(QtCore.QDate.currentDate())
        self.date_picker.setMinimumDate(QtCore.QDate.currentDate())

        self.date_picker.setDisplayFormat("dddd, dd.MM.yyyy")
        self.date_picker.calendarWidget().setGridVisible(True)
        self.layout_grid.addWidget(self.date_picker, 1, 1)

        self.earliest_time = QtWidgets.QTimeEdit()
        self.earliest_time.setMinimumHeight(self._widget_min_height)
        self.earliest_time.setToolTip("Fr??heste Abfahrt")
        self.earliest_time.setTime(QtCore.QTime.currentTime())
        self.layout_grid.addWidget(self.earliest_time, 1, 3)

        # self.layout_grid.addWidget(QtWidgets.QLabel("Sp??teste Abfahrt"), 2, 1)
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(QtWidgets.QLabel("Sp??teste Abfahrt begrenzen"), stretch=0,
                          alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.use_latest_time = AnimatedToggle(checked_color="#ec0016", pulse_checked_color="#44ec0016", )
        self.use_latest_time.setSizePolicy(
            QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed))
        hlayout.addWidget(self.use_latest_time)
        self.layout_grid.addLayout(hlayout, 2, 1, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self.latest_time = QtWidgets.QTimeEdit()
        self.latest_time.setMinimumHeight(self._widget_min_height)
        self.latest_time.setToolTip("Sp??teste Abfahrt")
        self.latest_time.setTime(
            QtCore.QTime(QtCore.QTime.currentTime().hour() + 1, QtCore.QTime.currentTime().minute()))
        self.latest_time.setEnabled(False)

        self.use_latest_time.stateChanged.connect(lambda x: self.latest_time.setEnabled(x))

        self.layout_grid.addWidget(self.latest_time, 2, 3)

        # self.layout_grid.addWidget(QtWidgets.QLabel("Anzahl Personen\n(ohne Kleinkind)"), 3, 0)
        self.num_reservations = QtWidgets.QComboBox()
        self.num_reservations.setMinimumHeight(self._widget_min_height)
        self.num_reservations.setPlaceholderText("Anzahl Personen (ohne Kleinkind)")
        self.num_reservations.setToolTip("Anzahl Personen (ohne Kleinkind)")
        self.num_reservations.addItems(["1 Person", "2 Personen", "3 Personen", "4 Personen", "5 Personen"])
        self.layout_grid.addWidget(self.num_reservations, 3, 1)

        self.reservation_option = QtWidgets.QComboBox()
        self.reservation_option.setMinimumHeight(self._widget_min_height)
        self.reservation_option.setToolTip("Reservierungsoption")
        self.reservation_option.addItems([x.value for x in ReservationOption if x != ReservationOption.NONE])
        self.layout_grid.addWidget(self.reservation_option, 3, 3)
        self.search_button = QtWidgets.QPushButton("Suchen")
        self.search_button.setMinimumHeight(self._widget_min_height)
        self.search_button.setStyleSheet("QPushButton {font-family: Martel; font-size:18px;}")
        self.search_button.clicked.connect(self.on_search_clicked)
        self.layout_grid.addWidget(self.search_button, 5, 0, 1, 4)

        self.tree_widget = QtWidgets.QTreeWidget(self)
        self.tree_widget.setHeaderLabels(("Reisezeit", "Dauer", "Umstiege", "Z??ge", "Reservierung"))
        self.tree_widget.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.tree_widget.setItemDelegate(ColoredBackgroundDelegate(self))
        column_widths = [150, 100, 300, 200, 200]
        for i in range(self.tree_widget.columnCount()):
            self.tree_widget.setColumnWidth(i, column_widths[i])
        self.tree_widget.setSortingEnabled(True)

        self.layout_grid.addWidget(self.tree_widget, 6, 0, 1, 4)

        self.no_connections_label = QtWidgets.QLabel("Keine reservierbaren\nVerbindungen gefunden")
        self.no_connections_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.no_connections_label.hide()

        self.layout_grid.addWidget(self.no_connections_label, 6, 0, 1, 4)

        self.layout_grid.setVerticalSpacing(10)
        self.vertical_layout.addLayout(self.layout_grid)
        self.vertical_layout.setContentsMargins(10, 10, 10, 0)

        self.prev_search_dock = QtWidgets.QDockWidget("Vorherige Suchen", self)
        self.prev_search_dock.setMinimumWidth(300)
        tmp_widget = QtWidgets.QWidget()
        tmp_widget.setObjectName("main_widget_scrollarea")
        layout = QtWidgets.QVBoxLayout()
        layout.setObjectName("scroll_area_vertical_layout")
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        tmp_widget.setLayout(layout)
        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(tmp_widget)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # self.prev_search_dock.setWidget(tmp_widget)
        self.prev_search_dock.setWidget(scroll_area)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.prev_search_dock)
        self.prev_search_dock.hide()

        self.menu_bar = QtWidgets.QMenuBar()

        # Add menus to the menu bar
        file_menu = QtWidgets.QMenu("Datei")
        self.exit_action = QtGui.QAction("Beenden", self)
        self.exit_action.triggered.connect(lambda: sys.exit(0))
        file_menu.addAction(self.exit_action)

        view_menu = QtWidgets.QMenu("Ansicht")
        view_menu.addAction(self.prev_search_dock.toggleViewAction())

        help_menu = QtWidgets.QMenu("Hilfe")
        self.show_browser_action = QtGui.QAction("Webbrowser zeigen", self)
        self.show_browser_action.setCheckable(True)
        self.report_bug_action = QtGui.QAction("Fehler melden", self)
        self.report_bug_action.triggered.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://github.com/oleschum/dbressuche/issues")))
        self.about_action = QtGui.QAction("??ber", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.show_browser_action)
        help_menu.addAction(self.report_bug_action)
        help_menu.addAction(self.about_action)
        self.menu_bar.addMenu(file_menu)
        self.menu_bar.addMenu(view_menu)
        self.menu_bar.addMenu(help_menu)

        # Add the menu bar to the main window
        self.setMenuBar(self.menu_bar)

        screen_size = QtGui.QScreen.availableGeometry(QtWidgets.QApplication.primaryScreen())
        height = 768
        width = 1024 + self.prev_search_dock.minimumWidth()
        self.setGeometry((screen_size.width() - width) / 2, (screen_size.height() - height) / 2, width, height)

        self.setWindowTitle('Deutsche Bahn Reservierungssuche')
        self.search_status_icon = SearchStatusIcon()
        self.search_status_icon.callback_func = self.on_status_icon_clicked
        self.search_status_label = QtWidgets.QLabel(" - ")
        self.update_info_label = QtWidgets.QLabel("")
        self.update_info_label.setOpenExternalLinks(True)
        self.update_info_label.setText(self.get_update_hint())
        self.internet_connection_label = QtWidgets.QLabel("")
        self.statusBar().addWidget(self.search_status_icon)
        self.statusBar().addWidget(QtWidgets.QLabel("Aktuelle Suche:"))
        self.statusBar().addWidget(self.search_status_label)
        self.statusBar().addPermanentWidget(self.update_info_label)
        self.statusBar().addPermanentWidget(self.internet_connection_label)
        self.statusBar().setContentsMargins(0, 0, 0, 0)
        widget = QtWidgets.QWidget()
        widget.setLayout(self.vertical_layout)
        self.setCentralWidget(widget)

        self._check_dependencies()
        self.internet_checker = InternetCheckWorker(self)
        self.internet_checker.status_changed.connect(self.on_internet_status_changed)
        self.internet_checker.start()

    def _add_query(self):
        query = QueryResults(self.current_search_params, [])
        self.past_queries.append(query)
        self._add_query_widget(query)

    def _add_query_widget(self, query: QueryResults):
        card_view = CardView(self.prev_search_dock, query)
        headline_text = "{} -> {}".format(query.search_params.start_station, query.search_params.final_station)
        card_view.headline_label.setText(headline_text)
        weekday = weekday_from_str(query.search_params.travel_date)
        info_text = "Abfahrt {}, {}; {}".format(weekday, query.search_params.travel_date,
                                                query.search_params.earliest_dep_time)
        if query.search_params.latest_dep_time != "":
            info_text += " - {}".format(query.search_params.latest_dep_time)
        card_view.text_label1.setText(info_text)
        card_view.text_label2.setText("Gesucht um {}".format(query.search_params.search_started))
        scroll_area = self.prev_search_dock.widget()
        main_widget = scroll_area.findChild(QtWidgets.QWidget, name="main_widget_scrollarea")  # type: QtWidgets.QWidget
        layout = scroll_area.findChild(QtWidgets.QVBoxLayout,
                                       name="scroll_area_vertical_layout")  # type: QtWidgets.QVBoxLayout
        layout.insertWidget(0, card_view)
        layout.setAlignment(card_view, QtCore.Qt.AlignmentFlag.AlignTop)
        main_widget.setLayout(layout)
        if not self.prev_search_dock.isVisible():
            self.prev_search_dock.show()

        card_view.clicked.connect(self.on_prev_search_clicked)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.internet_checker.terminate()
        super().closeEvent(event)

    def create_search_params(self):
        search_params = SearchParameters()
        t = time.localtime()
        search_started = time.strftime("%H:%M:%S", t)
        search_params.search_started = search_started
        search_params.travel_date = self.date_picker.date().toString("dd.MM.yyyy")
        search_params.earliest_dep_time = self.earliest_time.time().toString("hh:mm")
        if self.use_latest_time.isChecked():
            search_params.latest_dep_time = self.latest_time.time().toString("hh:mm")
        else:
            search_params.latest_dep_time = ""
        search_params.start_station = self.start_station.text()
        search_params.final_station = self.final_station.text()
        if self.num_reservations.currentIndex() == -1:
            self.num_reservations.setCurrentIndex(0)
        search_params.num_reservations = self.num_reservations.currentIndex() + 1  # plus one for start counting at zero
        search_params.orig_num_reservations = self.num_reservations.currentIndex() + 1
        if self.reservation_option.currentText() == ReservationOption.KLEINKIND.value or \
                self.reservation_option.currentText() == ReservationOption.FAMILIE.value:
            search_params.num_reservations += 1
            search_params.num_reservations = min(search_params.num_reservations, 5)
        search_params.reservation_category = ReservationOption(self.reservation_option.currentText())
        return search_params

    def _check_dependencies(self):
        done_event = multiprocessing.Event()
        self._dependency_process = multiprocessing.Process(target=check_dependencies,
                                                           args=(self.dependency_check_queue, done_event))
        self._dependency_process.daemon = True
        self._dependency_process.start()

        self.dep_check_process_listener = ProcessListener(done_event)
        self.dep_check_process_listener.daemon = True
        self.dep_check_process_listener.on_computation_done_callback = self.dependency_check_done.emit

        self.dep_check_process_listener.start()

    def display_result_hint(self):
        if self.found_connections:
            self.no_connections_label.hide()
            return
        font = self.no_connections_label.font()
        font.setPointSize(32)
        self.no_connections_label.setFont(font)
        self.no_connections_label.show()

    def get_update_hint(self):
        if is_up_to_date():
            return ""
        else:
            gh_url = "https://github.com/oleschum/dbressuche/releases/latest/"
            return "Neue Version verf??gbar: <a href='{}'>Download</a>".format(gh_url)

    def on_internet_status_changed(self, status: bool):
        if status:
            self.search_button.setEnabled(True)
            self.internet_connection_label.setText("")
        else:
            self.search_button.setEnabled(False)
            self.internet_connection_label.setText("Kein Internet verf??gbar.")

    def on_dependency_check_done(self):
        check_passed = self.dependency_check_queue.get(block=False)
        if self.dep_check_process_listener is not None:
            self.dep_check_process_listener.my_stop_event.set()
            self.dep_check_process_listener.join()
            self.dep_check_process_listener = None
        if check_passed == DependencyStatus.MISSING_FIREFOX:
            header_text = """<p align='center'><font size='5'><b>Entschuldige die St??rung!</b></font></p>"""
            about_text = "<font size='3'>Zur Nutzung dieser Software muss der Firefox Browser installiert sein.<br>" \
                         "Es scheint, als sei dieser bei dir nicht vorhanden.<br>" \
                         "Bitte lade dir diesen herunter, installier ihn und starte dann das Programm neu." \
                         '<p align="center"><a href="https://www.mozilla.org/de/firefox/browsers/">Download</a></font></p>'
            self.show_error_dialog(header_text, about_text)
        elif check_passed == DependencyStatus.NO_INTERNET:
            header_text = """<p align='center'><font size='5'><b>Entschuldige die St??rung!</b></font></p>"""
            about_text = "<font size='3'>Es scheint als h??ttest du gerade kein Internet.<br>" \
                         "Das tut mir leid.<br>" \
                         "Bitte pr??fe deine Internetverbindung, bevor du eine Suche startest. </font>"
            self.show_error_dialog(header_text, about_text)

    def on_new_connection(self, result_queue: multiprocessing.Queue):
        connection = result_queue.get(block=False)  # type: DBConnection
        self.found_connections.append(connection)
        if len(self.past_queries) > 0:
            self.past_queries[-1].connections.append(connection)
        self.insert_connection(connection)

    def on_new_status(self):
        res = self.status_queue.get(block=False)
        if not self.search_is_running:
            return
        if any(x in res.lower() for x in {"traceback", "stacktrace", "selenium"}):
            self.current_error = res
            self.search_status_icon.setFailure()
        else:
            self.search_status_label.setText(res)

    def on_prev_search_clicked(self, query: QueryResults):
        if self.search_is_running:
            dialog = QtWidgets.QMessageBox()
            res = dialog.question(self, "Aktuelle Suche abbrechen?",
                                  "Im Moment l??uft noch eine Suche. Soll diese abgebrochen werden?",
                                  QtWidgets.QMessageBox.StandardButton.No, QtWidgets.QMessageBox.StandardButton.Yes)
            if res == QtWidgets.QMessageBox.StandardButton.No:
                return
            self.on_search_done()
            self.reset_status_icon()
        self.current_search_params = query.search_params
        self.found_connections = query.connections
        self.update_connection_list()
        self.display_result_hint()

        self.start_station.setText(query.search_params.start_station)
        self.final_station.setText(query.search_params.final_station)
        qdate = QtCore.QDate.fromString(query.search_params.travel_date, "dd.MM.yyyy")
        self.date_picker.setDate(qdate)

        qtime = QtCore.QTime.fromString(query.search_params.earliest_dep_time, "hh:mm")
        self.earliest_time.setTime(qtime)

        if query.search_params.latest_dep_time != "":
            self.use_latest_time.setChecked(True)
            qtime = QtCore.QTime.fromString(query.search_params.latest_dep_time, "hh:mm")
            self.latest_time.setTime(qtime)
        else:
            self.use_latest_time.setChecked(False)

        self.reservation_option.setCurrentText(query.search_params.reservation_category.value)
        self.num_reservations.setCurrentIndex(query.search_params.orig_num_reservations - 1)

    def on_search_done(self):
        self.reset_search_process()
        self.search_button.setText("Suchen")
        self.search_is_running = False
        self.hide_wait_symbol()
        self.display_result_hint()
        self.search_status_label.setText(" - ")
        while not self.status_queue.empty():
            self.status_queue.get_nowait()

    def on_search_clicked(self):
        if self.search_is_running:
            self.on_search_done()
            self.reset_status_icon()
        else:
            self.no_connections_label.hide()
            self.search_status_label.setText(" - ")
            self.reset_search_process()
            self.reset_status_icon()
            self.current_search_params = self.create_search_params()
            if self.current_search_params.start_station == "" or self.current_search_params.final_station == "":
                return
            self.search_is_running = True
            self.search_button.setText("Abbrechen")
            self.tree_widget.clear()
            self.show_wait_symbol()
            self.found_connections = []
            self._add_query()

            headless_mode = not self.show_browser_action.isChecked()
            done_event = multiprocessing.Event()
            self.search_process = multiprocessing.Process(target=search_reservations,
                                                          args=(self.current_search_params, self.result_queue,
                                                                self.status_queue, headless_mode, done_event))
            self.search_process.daemon = True
            self.search_process.start()
            self.setup_process_listener(done_event)
            self.process_listener.start()

    def on_status_icon_clicked(self):
        header_text = """<p align='center'><font size='5'><b>Oops, da ist etwas schief gegangen :(</b></font><br>
        Tipp: H??ufig gen??gt es, die Suche nochmal zu starten, oder die Internetverbindung zu pr??fen.</p>"""
        about_text = "<font size='3'>{}</font>".format(self.current_error.replace("\n", "<br>"))
        self.show_error_dialog(header_text, about_text)

    def on_switch_stations(self):
        tmp = self.start_station.text()
        self.start_station.setText(self.final_station.text())
        self.final_station.setText(tmp)

    def reset_search_process(self):
        self.stop_process_listener()
        if self.search_process is not None and self.search_process.is_alive():
            self.search_process.terminate()
            self.search_process = None
            self.current_search_params = SearchParameters()

    def reset_status_icon(self):
        self.search_status_icon.setSuccess()
        self.current_error = ""

    def show_about_dialog(self):
        dialog = QtWidgets.QDialog()
        version = db_reservation_check.__version__
        about_text = """
        <p align='center'><font size='5'><b>DB Reservierungssuche</b></font></p><br>
    
        <font size='3'>
        Diese Applikation steht in keinem Zusammenhang mit dem Unternehmen "Deutsche Bahn AG", 
        einer ihrer Tochtergesellschaften oder einer sonstigen offiziellen oder inoffiziellen 
        Stelle der Deutschen Bahn AG.<br>
        
        Es handelt sich bei diesem Programm um ein privates Hobbyprojekt.<br>
        Alle Angaben ohne Gew??hr.<br>
        ??ber diese Applikation sind keine Buchungen oder Reservierungen m??glich.<br><br>
        
        Erstellt von Ole Schumann, 2023.<br>""" + \
                     "Version {}<br>".format(version) + \
                     """Abbildungen wurden durch DALL-E (OpenAI) erstellt.</font> 
                     """
        text_label = QtWidgets.QLabel()
        text_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        text_label.setText(about_text)
        text_label.setWordWrap(True)
        text_label.setFixedWidth(500)

        image_label = QtWidgets.QLabel()
        pixmap = QtGui.QPixmap(os.path.join(BASE_DIR, "assets", "happy_train.png"))
        pixmap = pixmap.scaled(300, 300)
        image_label.setPixmap(pixmap)
        image_label.setFixedSize(300, 300)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(image_label)
        layout.addWidget(text_label)

        dialog.setLayout(layout)
        dialog.setWindowTitle("??ber")

        dialog.exec()

    def show_error_dialog(self, header_text, about_text):
        dialog = QtWidgets.QDialog()

        header_label = QtWidgets.QLabel(header_text)
        text_label = QtWidgets.QLabel()
        text_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        text_label.setOpenExternalLinks(True)
        text_label.setText(about_text)
        text_label.setWordWrap(True)
        text_label.setFixedWidth(500)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidget(text_label)
        scroll_area.setFixedHeight(300)

        # Create a label for the image
        image_label = QtWidgets.QLabel()
        pixmap = QtGui.QPixmap(os.path.join(BASE_DIR, "assets", "sad_train.png"))
        pixmap = pixmap.scaled(300, 300)
        image_label.setPixmap(pixmap)
        image_label.setFixedSize(300, 300)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(header_label)

        inner_layout = QtWidgets.QHBoxLayout()
        inner_layout.addWidget(image_label)
        inner_layout.addWidget(scroll_area)
        layout.addLayout(inner_layout)

        dialog.setLayout(layout)
        dialog.setWindowTitle("Fehler")

        dialog.exec()

    def show_wait_symbol(self):
        data_columns = tuple(["" for _ in range(self.tree_widget.columnCount())])

        item = CustomSortTreeWidgetItem(data_columns)
        item.sortable = False
        self.tree_widget.insertTopLevelItem(0, item)

        for i in range(self.tree_widget.columnCount()):
            shimmer = TextShimmerAnimation(self, int(self.tree_widget.columnWidth(i) * 0.75), 15)
            self.tree_widget.setItemWidget(item, i, shimmer)
            shimmer.anim_start()

    def hide_wait_symbol(self):
        for idx in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(idx)
            widget = self.tree_widget.itemWidget(item, 0)
            if isinstance(widget, TextShimmerAnimation):
                self.tree_widget.takeTopLevelItem(idx)

    def load_data(self):
        with open(os.path.join(BASE_DIR, "data", "stations.json"), "r", encoding='utf-8') as f:
            self.stations = sorted(json.load(f))

    def stop_process_listener(self):
        if self.process_listener is not None:
            self.process_listener.my_stop_event.set()
            self.process_listener.join()
            self.process_listener = None

    def setup_process_listener(self, done_event):
        self.process_listener = ProcessListener(done_event)
        self.process_listener.daemon = True
        self.process_listener.db_connection_queue = self.result_queue
        self.process_listener.on_new_connection_callback = self.new_connection.emit
        self.process_listener.status_queue = self.status_queue
        self.process_listener.on_new_status_callback = self.new_status.emit
        self.process_listener.on_computation_done_callback = self.search_done.emit

    def insert_connection(self, connection: DBConnection):
        travel_time_str = "{} - {}".format(connection.start_time, connection.end_time)
        desired_reservation = self.current_search_params.reservation_category
        reservation_states = [train.reservation_option == desired_reservation for train in connection.trains]
        if all(reservation_states):
            color = QtGui.QColor("#66bb6a")
            overall_reservation_icon = CustomSortTreeWidgetItem.reservation_ok_icon
        elif any(reservation_states):
            color = QtGui.QColor("#ffab91")
            overall_reservation_icon = CustomSortTreeWidgetItem.reservation_partial_icon
        else:
            color = QtGui.QColor("#e57373")
            overall_reservation_icon = CustomSortTreeWidgetItem.reservation_fail_icon
        overall_trains = ", ".join([train.id for train in connection.trains])

        if connection.num_train_changes == 0:
            train = connection.trains[0]
            train_changes = "0 ({} - {})".format(train.start_station, train.final_station)
            overall_reservation_icon += " " + train.reservation_option.value
        else:
            train_changes = str(connection.num_train_changes)
        data_columns = (travel_time_str, connection.travel_duration, train_changes, overall_trains,
                        overall_reservation_icon)

        item = CustomSortTreeWidgetItem(data_columns)

        if connection.num_train_changes > 0:
            for idx, train in enumerate(connection.trains):
                travel_time_str = "{} - {}".format(train.start_time, train.end_time)
                dur = train.travel_duration
                travel_dur_str = "{}h {}min".format(int(dur[:dur.find(":")]), int(dur[dur.find(":") + 1:]))
                data_columns = (
                    travel_time_str, travel_dur_str, "{} - {}".format(train.start_station, train.final_station),
                    train.id, train.reservation_option.value)
                subitem = CustomSortTreeWidgetItem(data_columns)
                subitem.sortable = False
                item.addChild(subitem)
        for i in range(self.tree_widget.columnCount()):
            item.setData(i, QtCore.Qt.ItemDataRole.UserRole, color)
        self.tree_widget.addTopLevelItem(item)

    def update_connection_list(self):
        self.tree_widget.clear()
        for connection in self.found_connections:
            self.insert_connection(connection)


def search_reservations(search_params, result_queue, status_queue, headless=False, done_event=None):
    scraper = DBReservationScraper(headless=headless, done_event=done_event)
    scraper.search_reservations(search_params, result_queue, status_queue)


def check_dependencies(result_queue: multiprocessing.Queue, done_event: multiprocessing.Event):
    browser = None
    if not internet_available():
        result_queue.put(DependencyStatus.NO_INTERNET)
        done_event.set()
        return
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.service import Service as FirefoxService
        from selenium.webdriver.firefox.options import Options
        import platform
        # no console window of geckodriver https://stackoverflow.com/a/71093078/3971621
        firefox_service = FirefoxService()
        if platform.system() == "Windows":
            from subprocess import CREATE_NO_WINDOW
            firefox_service.creation_flags = CREATE_NO_WINDOW

        browser_options = Options()
        browser_options.add_argument("-headless")
        browser = webdriver.Firefox(service=firefox_service, options=browser_options)
        browser.get("https://www.google.com")
        result_queue.put(DependencyStatus.SUCCESS)
        browser.quit()
    except Exception as e:
        if browser is not None:
            browser.quit()
        result_queue.put(DependencyStatus.MISSING_FIREFOX)
    finally:
        done_event.set()


def start_gui():
    app = QtWidgets.QApplication(sys.argv)
    QtGui.QFontDatabase.addApplicationFont(os.path.join(BASE_DIR, "font", "Martel-SemiBold.ttf"))
    qt_material.apply_stylesheet(app, theme=os.path.join(BASE_DIR, "theme", "db_theme.xml"),
                                 extra={'font_family': 'Martel'})

    s = "QPushButton {{" \
        "color: {QTMATERIAL_PRIMARYTEXTCOLOR};" \
        "text-transform: none;" \
        "background-color: {QTMATERIAL_PRIMARYCOLOR};" \
        "}}" \
        "QPushButton:pressed {{" \
        "background-color: {QTMATERIAL_PRIMARYLIGHTCOLOR};" \
        "}}" \
        "QPushButton:disabled {{" \
        "background-color: #777777;" \
        "}}".format(**os.environ) \
        + \
        """
        QDateTimeEdit,
        QSpinBox,
        QDoubleSpinBox,
        QTextEdit,
        QLineEdit,
        QComboBox
        {""" + \
        "color: {QTMATERIAL_SECONDARYTEXTCOLOR};".format(**os.environ) + "}"

    stylesheet = app.styleSheet()
    app.setStyleSheet(stylesheet + s)
    app.setWindowIcon(QtGui.QIcon(os.path.join(BASE_DIR, "assets", "app_icon.ico")))

    window = DBScraperGui()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    start_gui()
