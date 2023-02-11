from PySide6 import QtWidgets, QtCore
from db_reservation_check.time_helper import convert_duration_format, get_time_diff


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
        elif column == 4:
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
