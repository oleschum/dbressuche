from PySide6 import QtWidgets, QtCore, QtGui
from db_reservation_check.db_scraper import BahnCard, BahnCardClass, AgeGroups, Passenger


class TravelerSelection(QtWidgets.QDockWidget):

    def __init__(self, *args, **kwargs):
        super(TravelerSelection, self).__init__(*args, **kwargs)
        self.setMinimumWidth(300)

        self.main_widget = QtWidgets.QWidget()
        self.v_layout = QtWidgets.QVBoxLayout()
        self.layout = QtWidgets.QGridLayout()
        self.layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.layout.addWidget(QtWidgets.QLabel("Altersgruppe"), 0, 0)
        self.layout.addWidget(QtWidgets.QLabel("Bahncard"), 0, 1)
        age_label = QtWidgets.QLabel("Alter")
        age_label.setToolTip("[Optional] genaues Alter: teilweise für Preisermittlung benötigt")
        self.layout.addWidget(age_label, 0, 2)

        self.add_button = QtWidgets.QPushButton("Hinzufügen")
        self.add_button.clicked.connect(self.add_traveler)
        self.v_layout.addWidget(self.add_button)
        self.v_layout.addLayout(self.layout)

        self.age_data = {
            "Kind (0-5)": {"group": AgeGroups.CHILD_0_5},
            "Kind (6-14)": {"group": AgeGroups.CHILD_6_14},
            "Person (15-26)": {"group": AgeGroups.ADULT_15_26},
            "Person (27-64)": {"group": AgeGroups.ADULT_27_64},
            "Senior (65+)": {"group": AgeGroups.SENIOR_65},
            "Hund": {"group": AgeGroups.DOG},
            "Fahrrad": {"group": AgeGroups.BIKE},
        }

        self.bahncard_data = {
            "Keine BC": {"class": BahnCardClass.NONE, "bc": BahnCard.NONE},
            "BC 25 - 2.Kl": {"class": BahnCardClass.KLASSE2, "bc": BahnCard.BC25},
            "BC 50 - 2.Kl": {"class": BahnCardClass.KLASSE2, "bc": BahnCard.BC50},
            "BC 100 - 2.Kl": {"class": BahnCardClass.KLASSE2, "bc": BahnCard.BC100},
            "BC 25 - 1.Kl": {"class": BahnCardClass.KLASSE1, "bc": BahnCard.BC25},
            "BC 50 - 1.Kl": {"class": BahnCardClass.KLASSE1, "bc": BahnCard.BC50},
            "BC 100 - 1.Kl": {"class": BahnCardClass.KLASSE1, "bc": BahnCard.BC100},
            "Business BC 25 - 1.Kl": {"class": BahnCardClass.KLASSE1, "bc": BahnCard.BC25_BUSINESS},
            "Business BC 25 - 2.Kl": {"class": BahnCardClass.KLASSE2, "bc": BahnCard.BC25_BUSINESS},
            "Business BC 50 - 1.Kl": {"class": BahnCardClass.KLASSE1, "bc": BahnCard.BC50_BUSINESS},
            "Business BC 50 - 2.Kl": {"class": BahnCardClass.KLASSE2, "bc": BahnCard.BC50_BUSINESS},
        }

        self.main_widget.setLayout(self.v_layout)
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.main_widget)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidget(self.scroll_area)

        self.traveler_count = 0
        self.add_traveler()
        # self.prev_search_dock = QtWidgets.QDockWidget("Vorherige Suchen", self)
        # self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.prev_search_dock)
        # self.prev_search_dock.hide()

    @property
    def row_count(self):
        return self.traveler_count + 1

    def add_traveler(self):
        age_cb = QtWidgets.QComboBox()

        for item_name, item_data in self.age_data.items():
            age_cb.addItem(item_name)
            age_cb.setItemData(age_cb.count() - 1, item_data)

        age_cb.setToolTip("Altersgruppe")
        age_cb.setMinimumWidth(120)
        age_cb.currentIndexChanged.connect(self.on_agegroup_changed)

        bahn_card_cb = QtWidgets.QComboBox()
        # bahn_card_cb.setMaximumWidth(120)
        bahn_card_cb.setMinimumWidth(80)
        for item_name, item_data in self.bahncard_data.items():
            bahn_card_cb.addItem(item_name)
            bahn_card_cb.setItemData(bahn_card_cb.count() - 1, item_data)
        bahn_card_cb.setToolTip("Bahncard")
        bahn_card_cb.setCurrentIndex(0)

        spin_box = QtWidgets.QSpinBox()
        spin_box.setToolTip("[Optional] genaues Alter: teilweise für Preisermittlung benötigt")
        spin_box.setRange(0, 120)
        spin_box.setMaximumWidth(60)
        spin_box.setMinimumWidth(60)

        remove_button = QtWidgets.QPushButton("-")
        remove_button.clicked.connect(self.remove_traveler)
        remove_button.setMaximumWidth(40)
        remove_button.setMinimumWidth(40)
        remove_button.setToolTip("Entfernen")

        if self.traveler_count == 0:
            remove_button.setEnabled(False)
        else:
            self._toggle_remove_button(True)

        # Add the widgets to the grid layout
        self.layout.addWidget(age_cb, self.row_count, 0)
        self.layout.addWidget(bahn_card_cb, self.row_count, 1)
        self.layout.addWidget(spin_box, self.row_count, 2)
        self.layout.addWidget(remove_button, self.row_count, 3)

        age_cb.setCurrentIndex(3)  # needed here so that callback func works properly (spin box needs to be in layout)

        # self.layout.setAlignment(age_cb, QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_widget.setLayout(self.layout)
        if not self.isVisible():
            self.show()

        self.traveler_count += 1

    def remove_traveler(self):
        if self.sender():
            row_index, _, _, _ = self.layout.getItemPosition(self.layout.indexOf(self.sender()))

            # Remove the widgets from the grid layout
            for column in range(self.layout.columnCount()):
                item = self.layout.itemAtPosition(row_index, column)
                if item is not None:
                    widget = item.widget()
                    self.layout.removeWidget(widget)
                    widget.deleteLater()  # Clean up the widget

            # Decrement the row count
            self.traveler_count -= 1
            # Shift the remaining widgets up
            for row in range(row_index + 1, self.row_count + 1):
                for column in range(self.layout.columnCount()):
                    item = self.layout.itemAtPosition(row, column)
                    if item is not None:
                        widget = item.widget()
                        self.layout.removeWidget(widget)
                        self.layout.addWidget(widget, row - 1, column)

            if self.traveler_count == 1:
                self._toggle_remove_button(False)

    def _toggle_remove_button(self, enabled):
        remove_button_0_item = self.layout.itemAtPosition(1, 3)
        if remove_button_0_item:
            remove_button_0 = remove_button_0_item.widget()
            remove_button_0.setEnabled(enabled)

    def get_passengers(self) -> list[Passenger]:
        passengers = []
        for row in range(1, self.traveler_count + 1):
            agegroup_cb = self.layout.itemAtPosition(row, 0).widget()  # type:QtWidgets.QComboBox
            bc_cb = self.layout.itemAtPosition(row, 1).widget()  # type:QtWidgets.QComboBox
            age_sb = self.layout.itemAtPosition(row, 2).widget()  # type:QtWidgets.QSpinBox

            idx = agegroup_cb.currentIndex()
            age_grp = agegroup_cb.itemData(idx)

            idx = bc_cb.currentIndex()
            bc_data = bc_cb.itemData(idx)

            age = age_sb.value()
            passengers.append(
                Passenger(age, age_group=age_grp["group"], bahn_card=bc_data["bc"], bahn_card_class=bc_data["class"]))
        return passengers

    def on_agegroup_changed(self, index):
        agegroup_cb = self.sender()
        if not agegroup_cb:
            return
        row_index, _, _, _ = self.layout.getItemPosition(self.layout.indexOf(agegroup_cb))
        age_sb = self.layout.itemAtPosition(row_index, 2).widget()  # type:QtWidgets.QSpinBox

        age_grp = agegroup_cb.itemData(index)
        age_grp = age_grp["group"]

        if age_grp == AgeGroups.CHILD_0_5:
            age_sb.setRange(0, 5)
            age_sb.setValue(3)
        elif age_grp == AgeGroups.CHILD_6_14:
            age_sb.setRange(6, 14)
            age_sb.setValue(10)
        elif age_grp == AgeGroups.ADULT_15_26:
            age_sb.setRange(15, 26)
            age_sb.setValue(18)
        elif age_grp == AgeGroups.ADULT_27_64:
            age_sb.setRange(27, 64)
            age_sb.setValue(28)
        elif age_grp == AgeGroups.SENIOR_65:
            age_sb.setRange(65, 110)
            age_sb.setValue(65)
        else:
            age_sb.setRange(0, 0)
            age_sb.setValue(0)
