from PySide6 import QtWidgets, QtCore
from db_reservation_check.db_scraper import SearchParameters, DBConnection
from db_reservation_check.gui.card_view import CardView
from db_reservation_check.time_helper import weekday_from_str


class QueryResults:

    def __init__(self, search_params: SearchParameters, connections: list[DBConnection]):
        self.search_params = search_params
        self.connections = connections


class PastSearches(QtWidgets.QDockWidget):

    def __init__(self, *args, **kwargs):
        super(PastSearches, self).__init__(*args, **kwargs)
        self.setMinimumWidth(300)
        self.setMinimumHeight(400)
        self.main_widget = QtWidgets.QWidget()
        #tmp_widget.setObjectName("main_widget_scrollarea")
        self.layout = QtWidgets.QVBoxLayout()
        #layout.setObjectName("scroll_area_vertical_layout")
        self.layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_widget.setLayout(self.layout)
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.main_widget)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # self.prev_search_dock.setWidget(tmp_widget)
        self.setWidget(self.scroll_area)

        self.current_query = None


    def remove_query(self):
        delete_button = self.sender()
        if delete_button:
            card_view = delete_button.parentWidget() # type: CardView
            self.layout.removeWidget(card_view)
            card_view.deleteLater()

    def add_new_connection(self, connection: DBConnection):
        if self.current_query is not None:
            self.current_query.connections.append(connection)

    def add_query(self, search_params, on_click_callback):
        query = QueryResults(search_params, [])
        self.current_query = query
        self.add_query_widget(query, on_click_callback)

    def add_query_widget(self, query: QueryResults, callback):
        card_view = CardView(self, query)
        card_view.close_btn.clicked.connect(self.remove_query)
        headline_text = "{} -> {}".format(query.search_params.start_station, query.search_params.final_station)
        card_view.headline_label.setText(headline_text)
        weekday = weekday_from_str(query.search_params.travel_date)
        info_text = "Abfahrt {}, {}; {}".format(weekday, query.search_params.travel_date,
                                                query.search_params.earliest_dep_time)
        if query.search_params.latest_dep_time != "":
            info_text += " - {}".format(query.search_params.latest_dep_time)
        card_view.text_label1.setText(info_text)
        card_view.text_label2.setText("Gesucht um {}".format(query.search_params.search_started))
        self.layout.insertWidget(0, card_view)
        self.layout.setAlignment(card_view, QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_widget.setLayout(self.layout)
        if not self.isVisible():
            self.show()

        card_view.clicked.connect(callback)
