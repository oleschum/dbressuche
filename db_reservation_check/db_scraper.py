import sys
import time
from copy import deepcopy
from enum import Enum
from urllib.parse import quote
from dataclasses import dataclass, field
import multiprocessing
import signal
import traceback
import platform
from typing import Union

from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db_reservation_check.time_helper import TimeCheckResult, connection_in_time_interval, convert_duration_format


class ReservationOption(Enum):
    STANDARD = "Standardbereich"
    FAMILIE = "Familienbereich"
    KLEINKIND = "Kleinkindabteil"
    NONE = "-"


@dataclass
class ReservationInformation:
    info_available: bool = False
    total_seats: int = 0
    total_seats_free: int = 0

    seat_info: dict = field(default_factory=lambda: {
        ReservationOption.STANDARD: {"free": 0, "total": 0, "wagon": set()},
        ReservationOption.KLEINKIND: {"free": 0, "total": 0, "wagon": set()},
        ReservationOption.FAMILIE: {"free": 0, "total": 0, "wagon": set()}
    })


class TravelClass(Enum):
    FIRST = 1
    SECOND = 2


class AgeGroups(Enum):
    CHILD_0_5 = 8
    CHILD_6_14 = 11
    ADULT_27_64 = 13
    ADULT_15_26 = 9
    SENIOR_65 = 12
    DOG = 14
    BIKE = 3


class BahnCardClass(Enum):
    NONE = "KLASSENLOS"
    KLASSE1 = "KLASSE_1"
    KLASSE2 = "KLASSE_2"


class BahnCard(Enum):
    NONE = 16
    BC25 = 17
    BC50 = 23
    BC100 = 24
    BC25_BUSINESS = 19
    BC50_BUSINESS = 18


@dataclass
class Passenger:
    age: int = 42
    age_group: AgeGroups = AgeGroups.ADULT_27_64
    bahn_card: BahnCard = BahnCard.NONE
    bahn_card_class: BahnCardClass = BahnCardClass.NONE


class SearchParameters:

    def __init__(self):
        self.travel_date = ""  # format dd.mm.yyyy
        self.earliest_dep_time = ""  # format HH:MM
        self.latest_dep_time = ""  # format HH:MM
        self.start_station = ""
        self.start_station_id = 0
        self.final_station = ""
        self.final_station_id = 0
        self.travel_class = TravelClass.SECOND
        self.passengers = [Passenger()]  # type: list[Passenger]
        self.reservation_category = ReservationOption.KLEINKIND
        self.only_direct_connections = False
        self.only_fast_connections = False
        self.search_started = ""  # format HH:MM:SS

    def convert_to_search_url(self) -> str:
        base_url = "https://www.bahn.de/buchung/fahrplan/suche#sts=true"
        so = quote(self.start_station)
        zo = quote(self.final_station)
        soid = quote("A=1@O={}@L={}".format(self.start_station, self.start_station_id))
        zoid = quote("A=1@O={}@L={}".format(self.final_station, self.final_station_id))
        soei = self.start_station_id
        zoei = self.final_station_id

        direct = "true" if self.only_direct_connections else "false"
        fast = "true" if self.only_fast_connections else "false"

        travellers = self._convert_passengers_to_url_params()
        date_time = self._convert_travel_date_to_url_params()

        url = (base_url + f"&so={so}&zo={zo}" +  # name of stations (only for visu)
               f"&kl={self.travel_class.value}" +  # travel class
               f"&r={travellers}" +  # passengers and bahn cards
               f"&soid={soid}&zoid={zoid}" +  # bahnhof IDs (IBNR) and names
               "&sot=ST&zot=ST" +  # stations for start and ziel
               f"&soei={soei}&zoei={zoei}" +  # stations IDs
               f"&d={direct}" +  # only direct connection
               f"&hd={date_time}" +  # travel date and time of outward journey
               "&hza=D" +  # given time is Depature (not A for Arrival)
               "&ar=false" +
               f"&s={fast}" +  # if true, only fastest connections are shown
               "&hz=%5B%5D" +
               "&fm=false" +  # fahrradmitnahme
               "&bp=false"  # bestprice
               )

        return url

    def _convert_passengers_to_url_params(self):
        # r= comma separated, ALTERSGRUPPE:BAHNCARD:KLASSE_BAHNCARD:ANZAHL_REISENDER:ALTER
        url = ""
        for passenger in self.passengers:
            url += "{}:{}:{}:1:{},".format(passenger.age_group.value, passenger.bahn_card.value,
                                           passenger.bahn_card_class.value, passenger.age)
        url = url[:-1]  # remove trailing comma
        return url

    def _convert_travel_date_to_url_params(self):
        # desired format for url is yyyy-mm-ddTHH:MM:SS
        day, month, year = self.travel_date.split(".")  # travel date has format dd.mm.yyyy
        return f"{year}-{month}-{day}T{self.earliest_dep_time}:00"


class Train:

    def __init__(self):
        # self.start_date = ""  # format DD.mm.YY
        self.start_time = ""  # format HH:MM
        self.end_time = ""  # format HH:MM
        self.travel_duration = ""  # format HH:MM
        self.start_station = ""
        self.final_station = ""
        self.id = ""  # e.g. "ICE 652"
        self.reservation_information = ReservationInformation()


class DBConnection:

    def __init__(self):

        self.start_time = ""  # format HH:MM
        self.end_time = ""  # format HH:MM
        self.travel_duration = ""  # format HH:MM
        self.start_station = ""
        self.final_station = ""
        self.trains = []  # type: list[Train]
        self.price_information = {}  # format ticket_name: price
        self.different_travel_date = False

    def __eq__(self, other: "DBConnection"):
        return self.travel_duration == other.travel_duration and self.start_time == other.start_time and \
               self.end_time == other.end_time and \
               self.start_station == other.start_station and self.final_station == other.final_station

    def __hash__(self):
        return hash(self.travel_duration + self.start_time + self.end_time + self.start_station + self.final_station)

    def __str__(self):
        train_id_str = ", ".join(self.train_ids)
        return f"{self.start_time} - {self.end_time} ({self.travel_duration}), " \
               f"{self.num_train_changes} (mit {train_id_str}), " \
               f"Reservierungsinfo: {[str(x.reservation_information.seat_info) for x in self.trains]}"

    @property
    def num_train_changes(self):
        if len(self.trains) > 0:
            return len(self.trains) - 1
        else:
            return 0

    @property
    def train_ids(self):
        return [x.id for x in self.trains]


def get_control():
    if platform.system().lower() == "darwin":
        return Keys.COMMAND
    else:
        return Keys.CONTROL


class DBReservationScraper:

    def __init__(self, headless=True, done_event=None):
        self.browser_options = Options()
        if headless:
            self.browser_options.add_argument("-headless")
        self.browser = None
        self.url = "https://www.bahn.de/"
        self.killed = False
        self.done_event = done_event
        self.parsed_connections = []  # type: list[DBConnection]
        self.search_params = None
        self.status_queue = None
        self.result_queue = None
        self._n_conn_parsed_again = 0
        self._all_connections_found = False
        self.retry_counter = 0
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args):
        self.killed = True
        if self.browser is not None:
            self.browser.quit()
            if self.done_event is not None:
                self.done_event.set()
            sys.exit(0)
        self.killed = True

    def _setup_ff_service(self):
        # no console window of geckodriver https://stackoverflow.com/a/71093078/3971621
        firefox_service = FirefoxService()
        if platform.system() == "Windows":
            from subprocess import CREATE_NO_WINDOW
            firefox_service.creation_flags = CREATE_NO_WINDOW
        return firefox_service

    def search_reservations(self, search_params: SearchParameters, result_queue: multiprocessing.Queue = None,
                            status_queue: multiprocessing.Queue = None) -> list[DBConnection]:
        status_queue.put("Starte Suche...")

        firefox_service = self._setup_ff_service()
        self.browser = webdriver.Firefox(service=firefox_service, options=self.browser_options)

        self.parsed_connections = []
        self.search_params = search_params
        self.status_queue = status_queue
        self.result_queue = result_queue

        url = search_params.convert_to_search_url()
        self.browser.get(url)
        status_queue.put("Cookies...")
        self._accept_cookies()

        self._all_connections_found = False
        self.retry_counter = 0
        try:
            while not self._all_connections_found and not self.killed:
                connections_html = self._locate_connection_list()
                if not connections_html:
                    self._all_connections_found = True
                    break

                self._n_conn_parsed_again = 0
                for connection_html in connections_html:
                    status_queue.put("Verarbeite Verbindungen...")
                    # likely the first or second element in connections_html will cause us to click on a "weiter" button
                    # to check reservation options and then later do browser.back() and we will start a new iteration
                    connection = self.process_connection(connection_html)
                    if connection:
                        self.parsed_connections.append(connection)
                        if result_queue:
                            result_queue.put(connection, block=False)
                            status_queue.put("Neue Verbindunge gefunden!")
                        break

                    if self._all_connections_found:
                        status_queue.put("Alle Verbindungen gefunden!")
                        break

                if self._n_conn_parsed_again == len(connections_html):
                    if not self._include_later_trains():
                        status_queue.put("Alle Verbindungen gefunden!")
                        self._all_connections_found = True
                    else:
                        status_queue.put("Suche weitere Verbindungen...")
        except Exception as e:
            if status_queue is not None:
                status_queue.put(traceback.format_exc())
        finally:
            status_queue.put("Fertig!")
            self.browser.quit()
            if self.done_event is not None:
                self.done_event.set()

        return self.parsed_connections

    def process_connection(self, connection_html: WebElement) -> Union[DBConnection, bool]:
        connection = self._create_connection_from_html(connection_html)
        conn_in_time = connection_in_time_interval(connection, self.search_params, check_date=False)
        if connection.different_travel_date or conn_in_time == TimeCheckResult.START_TOO_LATE:
            self._all_connections_found = True
            return False

        if connection in self.parsed_connections:
            self._n_conn_parsed_again += 1
            return False

        connection = self._add_price_and_reservation_info(connection, connection_html)
        return connection

    def _accept_cookies(self):
        try:
            time.sleep(2)
            css_selector = "button[class^='btn btn--secondary js-accept-essential-cookies']"
            wait = WebDriverWait(self.browser, 5)
            div0 = self.browser.find_element(By.CSS_SELECTOR, "div")
            shadow_root = self.browser.execute_script("return arguments[0].shadowRoot.children", div0)
            wait.until(EC.element_to_be_clickable(shadow_root[2].find_element(By.CSS_SELECTOR, css_selector)))
            shadow_root[2].find_element(By.CSS_SELECTOR, css_selector).click()
        except:
            # cookies already accepted or dialog not found
            pass

    def _get_next_btn_for_connection(self, connection_html: WebElement) -> Union[WebElement, None]:
        try:
            next_btn = connection_html.find_element(By.CSS_SELECTOR,
                                                    'div[class*="reiseloesung__item-right"] '
                                                    'button[class*="reiseloesung-button-container__btn-waehlen"]')
            return next_btn
        except Exception as e:
            return None

    def _add_price_and_reservation_info(self, connection: DBConnection, connection_html: WebElement):
        next_button = self._get_next_btn_for_connection(connection_html)
        if next_button:
            next_button.click()
            # time.sleep(2)
            connection = self._parse_reservation_page(connection)
            self.browser.back()  # get us back to connection overview page
        else:
            # no button for booking --> no reservation and price info
            self._mark_not_bookable(connection)
        return connection

    def _parse_prices(self, price_cards: list[WebElement], connection: DBConnection) -> bool:
        select_offer_button = None
        for card in price_cards:
            try:
                price = card.find_element(By.CSS_SELECTOR, "span[class*=angebot-zusammenfassung__preis").text
                offer_name = card.find_element(By.CSS_SELECTOR, "h3[class*=name").text
                connection.price_information[offer_name] = price
            except Exception as e:
                pass
            if not select_offer_button:
                try:
                    select_offer_button = card.find_element(By.CSS_SELECTOR, "button[class*=__btn")
                except:
                    pass
        if select_offer_button:
            select_offer_button.click()
            return True
        return False

    def _select_seat_reservation_checkbox(self) -> Union[WebElement, None]:
        try:
            reservation_div = self.browser.find_element(By.CSS_SELECTOR, "div[id*=reservierung")
            reservation_cb = reservation_div.find_element(By.CSS_SELECTOR, "input")
            reservation_cb.click()
            return reservation_div
        except:
            return None

    def _parse_train_reservation(self, connection: DBConnection, train: WebElement, train_idx: int):
        try:
            # wait until iframe is invisible. Needed if previous iFrame is not yet closed
            WebDriverWait(self.browser, 10).until(EC.invisibility_of_element_located((By.CSS_SELECTOR,
                                                                                      "iframe[class*=db-web")))

            select_seats_button = WebDriverWait(train, 1).until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button")))
            select_seats_button.click()
        except Exception as e:
            return False

        try:
            frame = self.browser.find_element(By.CSS_SELECTOR, "iframe[class*=db-web")
            self.browser.switch_to.frame(frame)
            wagon_list = WebDriverWait(self.browser, 10).until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "div[class*=Wagenliste")))
            all_wagons = wagon_list.find_elements(By.CSS_SELECTOR, "div[class*=Wagenteil")
        except Exception as e:
            # we may have opened an iframe --> make sure to close it
            try:
                self.browser.switch_to.default_content()
                close_btn = self.browser.find_element(By.CSS_SELECTOR,
                                                      "button[class*=db-web-plugin-dialog__close-button")
                close_btn.click()
            except:
                pass
            return False

        reservation_info = ReservationInformation()
        reservation_info.info_available = True
        for wagon in all_wagons:
            try:
                wagon_nr = wagon.get_attribute("data-wagen-nr")
            except:
                continue

            # this is much faster than calling get_attribute for each seat
            # https://stackoverflow.com/questions/43047606/python-selenium-get-attribute-of-elements-in-the-list-effectively
            seat_labels = self.browser.execute_script(f"""
                var result = []; 
                var div = document.querySelector('div[data-wagen-nr="{wagon_nr}"]');
                if (div) {{
                    var buttons = div.querySelectorAll('button[class*="PlatzElement"]');
                    for (var i = 0; i < buttons.length; i++) {{
                        result.push(buttons[i].getAttribute('aria-label'));
                    }}
                }}
                return result;
            """)

            for label in seat_labels:
                reservation_info.total_seats += 1

                if " Kindern" in label or "travellers with children" in label:
                    sub_field = ReservationOption.FAMILIE
                elif "Kleinkindern" in label or "travellers with young children" in label:
                    sub_field = ReservationOption.KLEINKIND
                else:
                    sub_field = ReservationOption.STANDARD
                reservation_info.seat_info[sub_field]["total"] += 1
                if "verfügbar." in label or "available" in label:
                    reservation_info.total_seats_free += 1
                    reservation_info.seat_info[sub_field]["free"] += 1
                    reservation_info.seat_info[sub_field]["wagon"].add(wagon_nr)
        connection.trains[train_idx].reservation_information = reservation_info
        self.browser.switch_to.default_content()
        close_btn = self.browser.find_element(By.CSS_SELECTOR, "button[class*=db-web-plugin-dialog__close-button")
        close_btn.click()
        return True

    def _parse_reservation_page(self, connection: DBConnection) -> DBConnection:
        try:
            price_cards = WebDriverWait(self.browser, 10).until(EC.visibility_of_all_elements_located(
                (By.CSS_SELECTOR, "div[class*=angebot-container__card")))
        except:
            return connection

        success = self._parse_prices(price_cards, connection)
        if not success:
            return connection

        reservation_div = self._select_seat_reservation_checkbox()
        if not reservation_div:
            return connection

        trains = reservation_div.find_elements(By.CSS_SELECTOR, 'div[class="platzreservierungAbschnitt _abschnitt"')

        for idx, train in enumerate(trains):
            self._parse_train_reservation(connection, train, idx)

        return connection

    def _locate_connection_list(self) -> Union[list[WebElement], bool]:
        try:
            connection_div = WebDriverWait(self.browser, 10).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, 'div[class*="reiseloesung-list-page__wrapper"')))
            connections_html = connection_div.find_elements(By.CSS_SELECTOR,
                                                            'li[class^=verbindung-list__result-item')
            return connections_html
        except:  # early exit, no connections found
            return False

    def _mark_not_bookable(self, connection: DBConnection):
        connection.price_information = {}
        for train in connection.trains:
            train.reservation_information = ReservationInformation()
            train.reservation_information.info_available = False  #

    def _create_connection_from_html(self, connection_html: WebElement) -> DBConnection:
        start_time = connection_html.find_element(By.CSS_SELECTOR,
                                                  "div[class*='reiseplan__uebersicht-uhrzeit-von'] time").text

        end_time = connection_html.find_element(By.CSS_SELECTOR,
                                                "div[class*='reiseplan__uebersicht-uhrzeit-nach'] time").text

        duration = connection_html.find_element(By.CSS_SELECTOR,
                                                "span[class='dauer-umstieg__dauer']").text
        start_station = connection_html.find_element(By.CSS_SELECTOR,
                                                     "span[class='test-reise-beschreibung-start-value']").text
        final_station = connection_html.find_element(By.CSS_SELECTOR,
                                                     "span[class='test-reise-beschreibung-ziel-value']").text

        connection = DBConnection()
        try:
            date_shift_heading = connection_html.find_element(By.CSS_SELECTOR,
                                                              "div[class='reiseloesung-heading']")
            connection.different_travel_date = True
        except:
            # date_shift_heading is only found for dateshifts. If we have not found it, everything is ok
            connection.different_travel_date = False

        connection.start_time = start_time
        connection.end_time = end_time
        connection.travel_duration = convert_duration_format(duration)
        connection.start_station = start_station
        connection.final_station = final_station

        self._add_trains(connection, connection_html)

        return connection

    def _add_trains(self, connection: DBConnection, connection_html: WebElement):

        try:
            details_btn = connection_html.find_element(By.CSS_SELECTOR,
                                                       "div[class*='reiseplan__details'] button")
            span_open_close = details_btn.find_element(By.CSS_SELECTOR,
                                                       "span[class='util__offscreen']").text
            if span_open_close != "schließe":
                details_btn.click()

            train_list_html = connection_html.find_elements(By.CSS_SELECTOR,
                                                            "div[class='verbindungs-abschnitt']")
        except Exception as e:
            return

        for train_html in train_list_html:
            train = Train()

            try:
                depature_time = train_html.find_element(By.CSS_SELECTOR,
                                                        "time[class*='verbindungs-halt__zeit-abfahrt']").text
                css_start_station = 'verbindungs-halt-bahnhofsinfos__name--abfahrt'
                start_station = train_html.find_element(By.CSS_SELECTOR,
                                                        f"span[class*={css_start_station}], a[class*={css_start_station}]").text

                # verbindungs-halt-bahnhofsinfos__name--ankunft

                duration = train_html.find_element(By.CSS_SELECTOR,
                                                   "span[class*='verbindungs-transfer__dauer--desktop']").text

                try:
                    train_id = train_html.find_element(By.CSS_SELECTOR,
                                                       "span[class='test-zugnummer-label__text']").text
                except:
                    train_id = train_html.find_element(By.CSS_SELECTOR,
                                                       "div[class*='test-zugnummer-label'] ri-transport-chip")
                    train_id = train_id.get_attribute("transport-text")

                end_time = train_html.find_element(By.CSS_SELECTOR,
                                                   "time[class*='verbindungs-halt__zeit-ankunft']").text

                css_final_station = 'verbindungs-halt-bahnhofsinfos__name--ankunft'
                final_station = train_html.find_element(By.CSS_SELECTOR,
                                                        f"span[class*={css_final_station}], a[class*={css_final_station}]").text

                train.start_station = start_station
                train.start_time = depature_time
                train.travel_duration = convert_duration_format(duration)
                train.id = train_id
                train.end_time = end_time
                train.final_station = final_station
            except Exception as e:
                continue

            connection.trains.append(train)

    def _include_later_trains(self):

        search_params = deepcopy(self.search_params)
        start_time = self.parsed_connections[-1].start_time
        # last_digit = int(start_time[-1]) + 1
        # start_time = start_time[:-1] + str(last_digit)
        search_params.earliest_dep_time = start_time
        new_url = search_params.convert_to_search_url()
        if new_url == self.browser.current_url:
            self.retry_counter += 1
        else:
            self.retry_counter = 0
        self.browser.get(new_url)
        time.sleep(2)

        if self.retry_counter > 3:
            return False
        return True


def main():
    search_params = SearchParameters()
    search_params.start_station = "Celle"
    search_params.start_station_id = 8000064  # 8596001=BASEL
    search_params.final_station_id = 8000152
    search_params.final_station = "Hannover Hbf"  # soei=8000152&zoei=
    search_params.earliest_dep_time = "08:49"
    search_params.latest_dep_time = "10:59"
    search_params.travel_date = "14.12.2023"
    search_params.reservation_category = ReservationOption.KLEINKIND

    p1 = Passenger(age=29, age_group=AgeGroups.ADULT_27_64, bahn_card=BahnCard.BC25,
                   bahn_card_class=BahnCardClass.KLASSE2)
    p2 = Passenger(age=3, age_group=AgeGroups.CHILD_0_5)
    search_params.passengers = [p1, p2]

    scraper = DBReservationScraper(headless=False)
    status_queue = multiprocessing.Queue()
    results = scraper.search_reservations(search_params, status_queue=status_queue)
    for con in results:
        print("-" * 80)
        print(con.start_station, con.final_station, con.start_time, con.end_time)
        for train in con.trains:
            print("Train:", train.start_station, train.end_time, train.start_time, train.end_time,
                  train.reservation_information.info_available, train.reservation_information.seat_info)
            print("/" * 20)


if __name__ == '__main__':
    main()
