from PySide6 import QtWidgets, QtCore
from PySide6 import QtGui
from db_reservation_check.time_helper import convert_duration_format, get_time_diff
from db_reservation_check.gui.text_shimmer_anim import TextShimmerAnimation
from db_reservation_check.db_scraper import DBConnection, ReservationOption, ReservationInformation


class ColoredBackgroundDelegate(QtWidgets.QStyledItemDelegate):

    def paint(self, painter, option, index):
        color = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if color is not None:
            full_rect = option.rect  # type: QtCore.QRect
            full_rect.setHeight(full_rect.height() - 10)
            painter.fillRect(full_rect, color)
        super(ColoredBackgroundDelegate, self).paint(painter, option, index)


class CustomSortTreeWidgetItem(QtWidgets.QTreeWidgetItem):
    reservation_ok_icon = "\U00002705"
    reservation_partial_icon = "\U00002705 / \U0000274C"
    reservation_fail_icon = "\U0000274C"

    def __init__(self, *args, **kwargs):
        super(CustomSortTreeWidgetItem, self).__init__(*args, **kwargs)
        self.sortable = True

    def __lt__(self, other):
        if not self.sortable:
            return False
        if not other.sortable:
            return False
        column = self.treeWidget().sortColumn()
        text = self.text(column)
        other_text = other.text(column)

        if column == 0:
            start_time = text.split("-")[0].strip()
            other_start_time = other_text.split("-")[0].strip()
            return get_time_diff(start_time, other_start_time).total_seconds() > 0
        elif column == 1:
            text = convert_duration_format(text)
            other_text = convert_duration_format(other_text)
            return get_time_diff(text, other_text).total_seconds() > 0
        elif column == 4:  # prices

            def to_float(txt):
                digits_text = ""
                for char in txt:
                    if char.isdigit():
                        digits_text += char
                    if char in (",", ".") and "." not in digits_text:
                        digits_text += "."
                return float(digits_text)

            float1 = to_float(text)
            float2 = to_float(other_text)
            return float1 < float2
        elif column == 5:  # reservation
            weight = self._get_reservation_sort_score(text)
            other_weight = self._get_reservation_sort_score(other_text)
            return weight > other_weight
        return text < other_text

    def _get_reservation_sort_score(self, text):
        if self.reservation_partial_icon in text:
            return 2
        elif self.reservation_ok_icon in text:  # order matters since ok icon is also in partial icon
            return 1
        else:
            return 3


class StatusLabel(QtWidgets.QLabel):
    def __init__(self, text):
        super().__init__(text)
        # self.setFixedSize(200, 60)  # Set desired size for the label
        # self.setFont(QFont("Arial", 12, QFont.Bold))  # Set custom font

        self.background_color = QtGui.QColor(156, 34, 0)
        self.outline_color = QtGui.QColor(87, 19, 0)  # Custom outline color (red)
        self.font_color = QtGui.QColor(255, 255, 255)  # Custom font color (black)
        self.bordersize = 2

    def paintEvent(self, event):
        # Create the painter
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        # Create the path
        path = QtGui.QPainterPath()
        # Set painter colors to given values.
        pen = QtGui.QPen(self.outline_color, self.bordersize)
        painter.setPen(pen)
        brush = QtGui.QBrush(self.background_color)
        painter.setBrush(brush)

        rect = QtCore.QRectF(event.rect())
        # Slighly shrink dimensions to account for bordersize.
        rect.adjust(self.bordersize / 2, self.bordersize / 2, -self.bordersize / 2, -self.bordersize / 2)

        # Add the rect to path.
        path.addRoundedRect(rect, 10, 10)
        painter.setClipPath(path)

        # Fill shape, draw the border and center the text.
        painter.fillPath(path, painter.brush())
        painter.strokePath(path, painter.pen())
        painter.setPen(self.font_color)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, self.text())


class ResultWidget(QtWidgets.QTreeWidget):

    def __init__(self, *args, **kwargs):
        super(ResultWidget, self).__init__(*args, **kwargs)
        self.setHeaderLabels(("Reisezeit", "Dauer", "Umstiege", "Züge", "Preis", "Reservierung"))
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setItemDelegate(ColoredBackgroundDelegate(self))
        column_widths = [150, 100, 200, 150, 150, 200]
        for i in range(self.columnCount()):
            self.setColumnWidth(i, column_widths[i])
        self.setSortingEnabled(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QTreeWidget.DragDropMode.InternalMove)
        header = self.header()
        header.setSectionsMovable(True)
        header.setDragEnabled(True)

        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_context_menu)

    def show_wait_symbol(self):
        data_columns = tuple(["" for _ in range(self.columnCount())])

        item = CustomSortTreeWidgetItem(data_columns)
        item.sortable = False
        self.insertTopLevelItem(0, item)

        for i in range(self.columnCount()):
            shimmer = TextShimmerAnimation(self, int(self.columnWidth(i) * 0.75), 15)
            self.setItemWidget(item, i, shimmer)
            shimmer.anim_start()

    def hide_wait_symbol(self):
        for idx in range(self.topLevelItemCount()):
            item = self.topLevelItem(idx)
            widget = self.itemWidget(item, 0)
            if isinstance(widget, TextShimmerAnimation):
                self.takeTopLevelItem(idx)

    def insert_connection(self, connection: DBConnection, search_params):
        travel_time_str = "{} - {}".format(connection.start_time, connection.end_time)
        desired_reservation = search_params.reservation_category
        num_travellers = len(search_params.passengers)
        reservation_states = [train.reservation_information.seat_info[desired_reservation]["free"] >= num_travellers for
                              train in connection.trains]
        if all(reservation_states):
            color = QtGui.QColor("#66bb6a")
            overall_reservation_icon = CustomSortTreeWidgetItem.reservation_ok_icon
            tooltip_reservation_main = "Reservierungswunsch erfüllbar"
        elif any(reservation_states):
            color = QtGui.QColor("#ffab91")
            overall_reservation_icon = CustomSortTreeWidgetItem.reservation_partial_icon
            tooltip_reservation_main = "Reservierungswunsch teilweise erfüllbar"
        else:
            color = QtGui.QColor("#e57373")
            overall_reservation_icon = CustomSortTreeWidgetItem.reservation_fail_icon
            tooltip_reservation_main = "Reservierungswunsch nicht erfüllbar"
        overall_trains = ", ".join([train.id for train in connection.trains])

        if connection.num_train_changes == 0:
            train = connection.trains[0]
            train_changes = "0 ({} - {})".format(train.start_station, train.final_station)
            overall_reservation_icon += " " + self._get_reservation_text(train.reservation_information, search_params)
            tooltip_reservation_main = self._get_reservation_tooltip(train.reservation_information)
        else:
            train_changes = str(connection.num_train_changes)

        names, prices = self._get_sorted_prices(connection.price_information)
        price_info = "ab {} ({})".format(prices[0], names[0])

        data_columns = (travel_time_str, connection.travel_duration, train_changes, overall_trains,
                        str(price_info), overall_reservation_icon)

        item = CustomSortTreeWidgetItem(data_columns)
        item.setToolTip(5, tooltip_reservation_main)
        item.setToolTip(4, self._get_price_tooltip(connection.price_information))

        if connection.num_train_changes > 0:
            for idx, train in enumerate(connection.trains):
                travel_time_str = "{} - {}".format(train.start_time, train.end_time)
                dur = train.travel_duration
                travel_dur_str = "{}h {}min".format(int(dur[:dur.find(":")]), int(dur[dur.find(":") + 1:]))

                reservation_info = self._get_reservation_text(train.reservation_information, search_params)

                data_columns = (
                    travel_time_str, travel_dur_str, "{} - {}".format(train.start_station, train.final_station),
                    train.id, "", reservation_info)
                subitem = CustomSortTreeWidgetItem(data_columns)
                subitem.sortable = False
                subitem.setToolTip(5, self._get_reservation_tooltip(train.reservation_information))
                item.addChild(subitem)
        for i in range(self.columnCount()):
            item.setData(i, QtCore.Qt.ItemDataRole.UserRole, color)
        self.addTopLevelItem(item)

    def _get_reservation_text(self, reservation_information: ReservationInformation,
                              search_params) -> str:
        if not reservation_information.info_available:
            return "Reservierung nicht möglich"
        seat_info = reservation_information.seat_info
        desired_reservation = search_params.reservation_category
        num_travellers = len(search_params.passengers)

        all_alternatives = {ReservationOption.KLEINKIND: [ReservationOption.KLEINKIND, ReservationOption.FAMILIE,
                                                          ReservationOption.STANDARD],
                            ReservationOption.FAMILIE: [ReservationOption.FAMILIE, ReservationOption.KLEINKIND,
                                                        ReservationOption.STANDARD],
                            ReservationOption.STANDARD: [ReservationOption.STANDARD, ReservationOption.FAMILIE,
                                                         ReservationOption.KLEINKIND]}

        alternatives = all_alternatives[desired_reservation]
        for alternative in alternatives:
            if seat_info[alternative]["free"] >= num_travellers:
                return "{} ({} von {} frei)".format(alternative.value, seat_info[alternative]["free"],
                                                    seat_info[alternative]["total"])

    def _get_reservation_tooltip(self, reservation_information: ReservationInformation) -> str:
        seat_info = reservation_information.seat_info
        if reservation_information.info_available:
            reservation_info = "Kleinkind {} von {} Plätzen frei in Wagen {},\n" \
                               "Familie {} von {} Plätzen frei in Wagen {},\n" \
                               "Standard {} von {} Plätzen frei in Wagen {}".format(
                seat_info[ReservationOption.KLEINKIND]["free"], seat_info[ReservationOption.KLEINKIND]["total"],
                ", ".join(seat_info[ReservationOption.KLEINKIND]["wagon"]),
                seat_info[ReservationOption.FAMILIE]["free"], seat_info[ReservationOption.FAMILIE]["total"],
                ", ".join(seat_info[ReservationOption.FAMILIE]["wagon"]),
                seat_info[ReservationOption.STANDARD]["free"], seat_info[ReservationOption.STANDARD]["total"],
                ", ".join(seat_info[ReservationOption.STANDARD]["wagon"]),
            )
        else:
            reservation_info = "Zu diesem Zug liegen entweder keine Informationen vor\n" \
                               "oder er lässt sich nicht reservieren"
        return reservation_info

    def _get_sorted_prices(self, price_info):
        names = list(price_info.keys())
        prices = list(price_info.values())
        int_prices = []
        for p in prices:
            if "," in p:
                int_prices.append(int(p.split(",")[0]))
            elif " " in p:
                int_prices.append(int(p.split(" ")[0]))
            elif "€" in p:
                int_prices.append(int(p.split("€")[0]))

        sort_idx = sorted(range(len(int_prices)), key=int_prices.__getitem__)
        return [names[sort_idx[idx]] for idx in range(len(names))], [prices[sort_idx[idx]] for idx in
                                                                     range(len(prices))]

    def _get_price_tooltip(self, price_info) -> str:
        tooltip = ""
        names, prices = self._get_sorted_prices(price_info)
        for idx in range(len(prices)):
            tooltip += "{}: {}\n".format(names[idx], prices[idx])
        tooltip = tooltip[:-1]

        return tooltip

    def show_header_context_menu(self, position):
        header = self.header()
        column_count = header.count()
        menu = QtWidgets.QMenu(self)

        # Create actions for each column
        for column_index in range(column_count):
            column_label = self.headerItem().text(column_index)
            action = QtGui.QAction(column_label, self)
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(column_index))
            action.setData(column_index)
            action.triggered.connect(self.toggle_column_visibility)
            menu.addAction(action)

        menu.exec(header.mapToGlobal(position))

    def toggle_column_visibility(self):
        action = self.sender()
        column_index = action.data()
        header = self.header()
        header.setSectionHidden(column_index, not action.isChecked())
