import os
import json
import random
import sys
import time
import multiprocessing
import threading
from PySide6 import QtWidgets, QtCore, QtGui
import qt_material

import db_reservation_check
from db_reservation_check.db_scraper import ReservationOption, DBReservationScraper, DBConnection, SearchParameters, \
    TravelClass
from db_reservation_check.gui.toggle_button import AnimatedToggle
from db_reservation_check.gui.autocomplete_lineedit import AutocompleteLineEdit
from db_reservation_check.gui.color_calendar import ColorCalendarWidget
from db_reservation_check.gui.tree_widget import ResultWidget
from db_reservation_check.gui.status_icon import SearchStatusIcon
from db_reservation_check.gui.traveler_selection import TravelerSelection
from db_reservation_check.gui.expander import Expander
from db_reservation_check.gui.past_searches import PastSearches, QueryResults
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


class DBScraperGui(QtWidgets.QMainWindow):
    new_connection = QtCore.Signal()
    new_status = QtCore.Signal()
    search_done = QtCore.Signal()
    dependency_check_done = QtCore.Signal()

    def __init__(self):
        super().__init__()

        self.station_data = {}
        self.load_data()
        self.found_connections = []  # type: list[DBConnection]
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

        self.start_station = AutocompleteLineEdit(list(self.station_data.keys()))
        self.start_station.setPlaceholderText("Von")
        self.start_station.setToolTip("Von")
        self.start_station.setMinimumHeight(self._widget_min_height)
        self.final_station = AutocompleteLineEdit(list(self.station_data.keys()))
        self.final_station.setPlaceholderText("Nach")
        self.final_station.setToolTip("Nach")
        self.final_station.setMinimumHeight(self._widget_min_height)

        self.switch_stations = QtWidgets.QPushButton()
        self.switch_stations.setIcon(QtGui.QIcon(os.path.join(BASE_DIR, "assets", "arrows.svg")))
        self.switch_stations.setIconSize(QtCore.QSize(30, 30))
        self.switch_stations.setFixedSize(QtCore.QSize(30, 30))
        self.switch_stations.setStyleSheet(
            "QPushButton {background-color: #00ffffff; border-width: 0px; margin: 0px;}")
        self.switch_stations.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
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
        self.earliest_time.setToolTip("Früheste Abfahrt")
        self.earliest_time.setTime(QtCore.QTime.currentTime())
        self.layout_grid.addWidget(self.earliest_time, 1, 3)

        self.layout_grid.addWidget(QtWidgets.QLabel("Reservierungswunsch"), 3, 1,
                                   alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.reservation_option = QtWidgets.QComboBox()
        self.reservation_option.setMinimumHeight(self._widget_min_height)
        self.reservation_option.setToolTip("Reservierungsoption")
        self.reservation_option.addItems([x.value for x in ReservationOption if x != ReservationOption.NONE])
        self.reservation_option.setCurrentIndex(2)
        self.layout_grid.addWidget(self.reservation_option, 3, 3)

        self.search_button = QtWidgets.QPushButton("Suchen")
        self.search_button.setMinimumHeight(self._widget_min_height)
        self.search_button.setStyleSheet("QPushButton {font-family: Martel; font-size:18px;}")
        self.search_button.clicked.connect(self.on_search_clicked)
        self.layout_grid.addWidget(self.search_button, 5, 0, 1, 4)

        ext_settings = Expander(parent=self, title="Erweiterte Einstellungen")

        ext_settings_layout = QtWidgets.QHBoxLayout()
        ext_settings_layout.addWidget(QtWidgets.QLabel("Späteste Abfahrt begrenzen"), stretch=0,
                                      alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.use_latest_time = AnimatedToggle(checked_color="#ec0016", pulse_checked_color="#44ec0016")
        self.use_latest_time.setSizePolicy(
            QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed))
        ext_settings_layout.addWidget(self.use_latest_time)
        self.latest_time = QtWidgets.QTimeEdit()
        self.latest_time.setMinimumHeight(self._widget_min_height)
        self.latest_time.setToolTip("Späteste Abfahrt")
        self.latest_time.setTime(
            QtCore.QTime(QtCore.QTime.currentTime().hour() + 1, QtCore.QTime.currentTime().minute()))
        self.latest_time.setEnabled(False)
        ext_settings_layout.addWidget(self.latest_time)

        self.use_latest_time.stateChanged.connect(lambda x: self.latest_time.setEnabled(x))

        ext_settings_layout.addWidget(QtWidgets.QLabel("Schnellste Verbindungen"), stretch=0,
                                      alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.only_fast_connections = AnimatedToggle(checked_color="#ec0016", pulse_checked_color="#44ec0016")
        self.only_fast_connections.setSizePolicy(
            QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed))
        ext_settings_layout.addWidget(self.only_fast_connections)

        ext_settings_layout.addWidget(QtWidgets.QLabel("Nur direkte Verbindungen"), stretch=0,
                                      alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.only_dircect_connections = AnimatedToggle(checked_color="#ec0016", pulse_checked_color="#44ec0016")
        self.only_dircect_connections.setSizePolicy(
            QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed))
        ext_settings_layout.addWidget(self.only_dircect_connections)

        ext_settings_layout.addWidget(QtWidgets.QLabel("Reisen in Klasse:"), stretch=0,
                                      alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.travel_class = QtWidgets.QComboBox(self)
        self.travel_class.addItems(["Erste Klasse", "Zweite Klasse"])
        self.travel_class.setItemData(0, TravelClass.FIRST)
        self.travel_class.setItemData(1, TravelClass.SECOND)
        self.travel_class.setCurrentIndex(1)
        ext_settings_layout.addWidget(self.travel_class)

        ext_settings.setContentLayout(ext_settings_layout)
        self.layout_grid.addWidget(ext_settings, 6, 0, 1, 4)

        self.result_widget = ResultWidget()

        self.layout_grid.addWidget(self.result_widget, 7, 0, 1, 4)

        self.no_connections_label = QtWidgets.QLabel("Keine reservierbaren\nVerbindungen gefunden")
        self.no_connections_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.no_connections_label.hide()

        self.layout_grid.addWidget(self.no_connections_label, 7, 0, 1, 4)

        self.layout_grid.setVerticalSpacing(10)
        self.vertical_layout.addLayout(self.layout_grid)
        self.vertical_layout.setContentsMargins(10, 10, 10, 0)

        self.traveler_selection = TravelerSelection("Reisende", self)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.traveler_selection)
        self.traveler_selection.show()

        self.prev_search_dock = PastSearches("Vorherige Suchen", self)
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
        view_menu.addAction(self.traveler_selection.toggleViewAction())

        help_menu = QtWidgets.QMenu("Hilfe")
        self.show_browser_action = QtGui.QAction("Webbrowser zeigen", self)
        self.show_browser_action.setCheckable(True)
        self.report_bug_action = QtGui.QAction("Fehler melden", self)
        self.report_bug_action.triggered.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://github.com/oleschum/dbressuche/issues")))
        self.about_action = QtGui.QAction("Über", self)
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
        width = 1224 + self.traveler_selection.minimumWidth()
        self.setGeometry((screen_size.width() - width) / 2, (screen_size.height() - height) / 2, width, height)

        self.resizeDocks((self.traveler_selection,), (400,), QtCore.Qt.Orientation.Horizontal)

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
        #self.internet_checker.start()

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
        search_params.start_station_id = self.station_data.get(search_params.start_station, {}).get("id", 0)
        search_params.final_station = self.final_station.text()
        search_params.final_station_id = self.station_data.get(search_params.final_station, {}).get("id", 0)
        search_params.reservation_category = ReservationOption(self.reservation_option.currentText())
        search_params.travel_class = self.travel_class.currentData()
        search_params.only_fast_connections = self.only_fast_connections.isChecked()
        search_params.only_direct_connections = self.only_dircect_connections.isChecked()
        search_params.passengers = self.traveler_selection.get_passengers()

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
            return "Neue Version verfügbar: <a href='{}'>Download</a>".format(gh_url)

    def on_internet_status_changed(self, status: bool):
        if status:
            self.search_button.setEnabled(True)
            self.internet_connection_label.setText("")
        else:
            self.search_button.setEnabled(False)
            self.internet_connection_label.setText("Kein Internet verfügbar.")

    def on_dependency_check_done(self):
        check_passed = self.dependency_check_queue.get(block=False)
        if self.dep_check_process_listener is not None:
            self.dep_check_process_listener.my_stop_event.set()
            self.dep_check_process_listener.join()
            self.dep_check_process_listener = None
        if check_passed == DependencyStatus.MISSING_FIREFOX:
            header_text = """<p align='center'><font size='5'><b>Entschuldige die Störung!</b></font></p>"""
            about_text = "<font size='3'>Zur Nutzung dieser Software muss der Firefox Browser installiert sein.<br>" \
                         "Es scheint, als sei dieser bei dir nicht vorhanden.<br>" \
                         "Bitte lade dir diesen herunter, installier ihn und starte dann das Programm neu." \
                         '<p align="center"><a href="https://www.mozilla.org/de/firefox/browsers/">Download</a></font></p>'
            self.show_error_dialog(header_text, about_text)
        elif check_passed == DependencyStatus.NO_INTERNET:
            header_text = """<p align='center'><font size='5'><b>Entschuldige die Störung!</b></font></p>"""
            about_text = "<font size='3'>Es scheint als hättest du gerade kein Internet.<br>" \
                         "Das tut mir leid.<br>" \
                         "Bitte prüfe deine Internetverbindung, bevor du eine Suche startest. </font>"
            self.show_error_dialog(header_text, about_text)

    def on_new_connection(self, result_queue: multiprocessing.Queue):
        connection = result_queue.get(block=False)  # type: DBConnection
        self.found_connections.append(connection)
        self.prev_search_dock.add_new_connection(connection)
        self.result_widget.insert_connection(connection, self.current_search_params)

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
                                  "Im Moment läuft noch eine Suche. Soll diese abgebrochen werden?",
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

        self.only_dircect_connections.setChecked(query.search_params.only_direct_connections)
        self.only_fast_connections.setChecked(query.search_params.only_fast_connections)

        self.reservation_option.setCurrentText(query.search_params.reservation_category.value)
        self.travel_class.setCurrentIndex(query.search_params.travel_class.value - 1)

    def on_search_done(self):
        self.reset_search_process()
        self.search_button.setText("Suchen")
        self.search_is_running = False
        self.result_widget.hide_wait_symbol()
        self.display_result_hint()
        self.search_status_label.setText(" - ")
        while not self.status_queue.empty():
            self.status_queue.get_nowait()

    def on_search_clicked(self):

        from db_reservation_check.db_scraper import Train, ReservationInformation, ReservationOption
        connection = DBConnection()
        connection.travel_duration = "02:23"
        connection.start_time = "08:23"
        connection.end_time = "19:23"
        connection.start_station = "Hannover"
        connection.final_station = "ASD"

        pce = random.randint(20, 200)
        connection.price_information={"Flexpreis": "159,95€", "Sparpreis": f"{pce},23€", "Super Sparpreis": "48,12€"}
        train = Train()
        train.travel_duration = "01:00"
        train.start_station = "asd1"
        train.final_station = "asd2"
        train.end_time = "12:00"
        train.start_time = "11:00"
        train.reservation_information = ReservationInformation()
        train.reservation_information.info_available = True
        train.reservation_information.total_seats = 213
        train.reservation_information.total_seats_free = 123
        train.reservation_information.seat_info[ReservationOption.STANDARD] = {"free": 120, "total": 220, "wagon": set(["1","2","3","4","5","6","7","8","9"])}
        train.reservation_information.seat_info[ReservationOption.KLEINKIND] = {"free": 1, "total": 5, "wagon": set(["9"])}
        train.reservation_information.seat_info[ReservationOption.FAMILIE] = {"free": 10, "total": 25,
                                                                                "wagon": set(["9"])}

        train2 = Train()
        train2.travel_duration = "11:00"
        train2.start_station = "asd3"
        train2.final_station = "asd4"
        train2.end_time = "14:00"
        train2.start_time = "15:00"
        train2.reservation_information = ReservationInformation()
        train2.reservation_information.info_available = True
        train2.reservation_information.total_seats = 213
        train2.reservation_information.total_seats_free = 123
        train2.reservation_information.seat_info[ReservationOption.STANDARD] = {"free": 120, "total": 220, "wagon": set(["1","2","3","4","5","6","7","8","9"])}
        train2.reservation_information.seat_info[ReservationOption.KLEINKIND] = {"free": 1, "total": 5, "wagon": set(["9"])}
        train2.reservation_information.seat_info[ReservationOption.FAMILIE] = {"free": 0, "total": 25,
                                                                              "wagon": set(["9"])}

        connection.trains = [train, train2]

        self.current_search_params = self.create_search_params()
        self.result_widget.insert_connection(connection, self.current_search_params)

        connection2 = connection
        connection2.trains = connection2.trains[1:]
        self.result_widget.insert_connection(connection2, self.current_search_params)

        return

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
            self.result_widget.clear()
            self.result_widget.show_wait_symbol()
            self.found_connections = []
            self.prev_search_dock.add_query(self.current_search_params, self.on_prev_search_clicked)

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
        Tipp: Häufig genügt es, die Suche nochmal zu starten, oder die Internetverbindung zu prüfen.</p>"""
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
        Alle Angaben ohne Gewähr.<br>
        Über diese Applikation sind keine Buchungen oder Reservierungen möglich.<br><br>
        
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
        dialog.setWindowTitle("Über")

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

    def load_data(self):
        with open(os.path.join(BASE_DIR, "data", "stations.json"), "r", encoding='utf-8') as f:
            self.station_data = json.load(f)
            # self.stations = sorted(json.load(f))

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

    def update_connection_list(self):
        self.result_widget.clear()
        for connection in self.found_connections:
            self.result_widget.insert_connection(connection, self.current_search_params)


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
        "color: {QTMATERIAL_SECONDARYTEXTCOLOR};".format(**os.environ) + "}" + \
        """
        QComboBox::item {
            margin-top: 0px;
            margin-bottom: 0px;
            margin-left: -8px;
            padding-left: -5px;
            min-height: 5px;
            height: 15px;
        }
        QTreeWidget::item::selected {
            background-color: none;
        }
        """

    stylesheet = app.styleSheet()
    app.setStyleSheet(stylesheet + s)
    app.setWindowIcon(QtGui.QIcon(os.path.join(BASE_DIR, "assets", "app_icon.ico")))

    window = DBScraperGui()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    start_gui()
