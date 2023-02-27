import sys
import re
import time
from copy import deepcopy
from enum import Enum
import multiprocessing
import signal
import traceback
import platform

from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db_reservation_check.time_helper import compute_travel_time, TimeCheckResult, connection_in_time_interval


class ReservationOption(Enum):
    GROSSRAUM = "Großraum"
    ABTEIL = "Abteil"
    FAMILIE = "Familienbereich"
    KLEINKIND = "Kleinkindabteil"
    NONE = "-"


class SearchParameters:

    def __init__(self):
        self.travel_date = ""  # format dd.mm.yyyy
        self.earliest_dep_time = ""  # format HH:MM
        self.latest_dep_time = ""  # format HH:MM
        self.start_station = ""
        self.final_station = ""
        self.num_reservations = 1
        self.orig_num_reservations = 1  # dropdown selection, different due to non counted children below 5
        self.reservation_category = ReservationOption.KLEINKIND
        self.only_direct_connections = False
        self.search_started = ""  # format HH:MM:SS


class Train:

    def __init__(self):
        self.start_date = ""  # format DD.mm.YY
        self.start_time = ""  # format HH:MM
        self.end_time = ""  # format HH:MM
        self.travel_duration = ""  # format HH:MM
        self.start_station = ""
        self.final_station = ""
        self.id = ""  # e.g. "ICE 652"
        self.reservation_option = ReservationOption.NONE


class DBConnection:

    def __init__(self):

        self.start_time = ""  # format HH:MM
        self.end_time = ""  # format HH:MM
        self.travel_duration = ""  # format HH:MM
        self.start_station = ""
        self.final_station = ""
        self.trains = []  # type: list[Train]
        self._start_date = ""  # format DD.mm.YY

    def __eq__(self, other: "DBConnection"):
        return self.travel_duration == other.travel_duration and self.start_time == other.start_time and \
               self.end_time == other.end_time and \
               self.start_station == other.start_station and self.final_station == other.final_station

    def __hash__(self):
        return hash(self.travel_duration + self.start_time + self.end_time + self.start_station + self.final_station)

    def __str__(self):
        train_id_str = ", ".join(self.train_ids)
        return f"{self.start_date} {self.start_time} - {self.end_time} ({self.travel_duration}), " \
               f"{self.num_train_changes} (mit {train_id_str}), " \
               f"Reservierungsoptionen: {[x.reservation_option.value for x in self.trains]}"

    @property
    def num_train_changes(self):
        if len(self.trains) > 0:
            return len(self.trains) - 1
        else:
            return 0

    @property
    def train_ids(self):
        return [x.id for x in self.trains]

    @property
    def start_date(self) -> str:
        if len(self.trains) == 0:
            return self._start_date
        else:
            return self.trains[0].start_date

    @start_date.setter
    def start_date(self, date: str):
        self._start_date = date


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

    def search_reservations(self, search_params: SearchParameters, result_queue: multiprocessing.Queue = None,
                            status_queue: multiprocessing.Queue = None):
        status_queue.put("Starte Suche...")

        # no console window of geckodriver https://stackoverflow.com/a/71093078/3971621
        firefox_service = FirefoxService()
        if platform.system() == "Windows":
            from subprocess import CREATE_NO_WINDOW
            firefox_service.creation_flags = CREATE_NO_WINDOW

        self.browser = webdriver.Firefox(service=firefox_service, options=self.browser_options)

        all_parsed_connections = []

        try:
            while True and not self.killed:
                status_queue.put("Lade Bahn Website...")
                self.browser.get(self.url)
                status_queue.put("Cookies...")
                self._accept_cookies()
                status_queue.put("Trage Suchparameter ein...")
                self._move_to_search()
                self._fill_in_route(search_params)
                self._fill_in_date_time(search_params)
                self._set_travelers(search_params)
                status_queue.put("Suche Züge...")
                self._click_search_reservation()

                # check for unique from/to fields or select most probable one from dropdown
                self._check_unique_stations()

                later_trains_clickable = True
                parsed_connections, latest_connection_found = self._parse_current_connections(search_params)
                while not latest_connection_found and later_trains_clickable:
                    status_queue.put("Suche nach weiteren Zügen...")
                    later_trains_clickable = self._include_later_trains()
                    parsed_connections, latest_connection_found = self._parse_current_connections(search_params)

                parsed_connections = [x for x in parsed_connections if x[1] not in all_parsed_connections]
                all_parsed_connections += [x[1] for x in parsed_connections]

                status_queue.put("Suche nach freien Plätzen...")
                _, reload_needed = self._append_reservations_to_connections(deepcopy(parsed_connections), search_params,
                                                                            result_queue)
                if reload_needed:
                    status_queue.put("Neuladen der Ergebnisse nach Alterseingabe")
                    # revert adding of previously parsed connections to all_parsed_connections
                    prev_parsed_connections = [x[1] for x in parsed_connections]
                    all_parsed_connections = [x for x in all_parsed_connections if x not in prev_parsed_connections]
                    # parse again
                    WebDriverWait(self.browser, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@id='resultsOverviewContainer']/div")))
                    status_queue.put("Suche nach weiteren Zügen...")
                    parsed_connections, latest_connection_found = self._parse_current_connections(search_params)
                    parsed_connections = [x for x in parsed_connections if x[1] not in all_parsed_connections]
                    all_parsed_connections += [x[1] for x in parsed_connections]
                    status_queue.put("Suche nach freien Plätzen...")
                    self._append_reservations_to_connections(deepcopy(parsed_connections), search_params,
                                                             result_queue)

                if latest_connection_found or len(parsed_connections) == 0:
                    status_queue.put("Späteste Verbindung gefunden.")
                    break
                else:
                    current_latest_connection = parsed_connections[-1][1]
                    search_params.earliest_dep_time = current_latest_connection.start_time
        except Exception as e:
            if status_queue is not None:
                status_queue.put(traceback.format_exc())
        finally:
            status_queue.put("Fertig!")
            self.browser.quit()
            if self.done_event is not None:
                self.done_event.set()

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

    def _append_reservations_to_connections(self, connections: list[tuple[int, DBConnection]],
                                            search_params: SearchParameters,
                                            result_queue: multiprocessing.Queue) -> tuple[list[DBConnection], bool]:
        connection_containers = "//div[@id='resultsOverviewContainer']/div"
        output_connections = []

        for idx, connection in connections:
            # Since elements go stale after we follow one connection, we have to query
            # the elements again after each reservation check.
            try:
                containers = WebDriverWait(self.browser, 10).until(
                    EC.visibility_of_all_elements_located((By.XPATH, connection_containers)))
            except:
                return [], False
            connection_element = containers[idx]
            trains, reload_needed = self._check_reservation(connection_element, search_params)
            if reload_needed:
                return [], True
            if len(trains) != 0:
                connection.trains = trains
                output_connections.append(connection)
                if result_queue is not None:
                    result_queue.put(connection, block=False)
        return output_connections, False

    def _check_for_age_input(self, search_params: SearchParameters):
        try:
            elements = self.browser.find_elements(By.CSS_SELECTOR,
                                                  "div[class='travellerRow'] div[class^='travellerAgeDiv'] input[id^='travellerAge']")
            if len(elements) == 0:
                return False
        except:
            return False  # no age field needed

        try:
            for idx, el in enumerate(elements):  # type: WebElement
                el.click()
                if idx == 1 and (search_params.reservation_category == ReservationOption.KLEINKIND or
                                 search_params.reservation_category == ReservationOption.FAMILIE):
                    el.send_keys("3")
                else:
                    el.send_keys("42")

            refresh_btn = self.browser.find_element(By.CSS_SELECTOR, "input[class^='submit-btn']")
            refresh_btn.click()
        except:
            return False
        return True

    def _check_unique_stations(self):

        # Idea: wait until top progressbar is loaded
        #  -> Then check at which stage we are. If we are still in "search" stage, check for error message
        #  -> finally resubmit search

        x_path_progressbar = '//ul[@id="hfs_progressbar"]'
        try:
            progressbar = WebDriverWait(self.browser, 10).until(
                EC.visibility_of_element_located((By.XPATH, x_path_progressbar)))  # type: WebElement

            active_element = progressbar.find_element(By.CSS_SELECTOR, "li[class*='active']")  # type: WebElement
            if "Suche" in active_element.text:
                # we are still in the search process -> click search button again
                search_btn = self.browser.find_element(By.CSS_SELECTOR, "input[id='searchConnectionButton']")
                search_btn.click()
        except Exception as e:
            return

    def _check_reservation(self, connection_block: WebElement,
                           search_params: SearchParameters) -> tuple[list[Train], bool]:
        """
        Perform the reservation check for a single connection.
         - click on the reservation button
         - check if age is needed for reservation --> return and reload page
         - input names
         - input reservation wish
         - parse response and create Train objects for this connection
        :param connection_block: html WebElement for one single connection
        :param search_params: Search parameters, needed to insert reservation wish.
        :return: - a list of trains with reservations added to them
                 - a bool indicating whether a reload of the connection page is needed (e.g. due to age fields)
        """

        try:
            # check for no fares (reservation not possible)
            nofares = connection_block.find_element(By.CSS_SELECTOR,
                                                    "div[class='connectionAction']  a[class='layer_nofares']")
            return [], False
        except:
            pass  # nothing to worry, we don't want to find this element usually

        try:
            button = connection_block.find_element(By.CSS_SELECTOR,
                                                   "div[class='connectionAction']  a[class='buttonbold']")

            button.click()
        except:
            return [], False

        refresh_needed = self._check_for_age_input(search_params)
        if refresh_needed:
            return [], True

        # we are now on the "ticket & reservierung page" and are possibly asked for login details
        # enter data and continue as guest

        wait = WebDriverWait(self.browser, 10)
        first_name_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id^='vorname']")))

        first_name_input.send_keys(get_control() + "a")
        first_name_input.send_keys(Keys.DELETE)
        first_name_input.send_keys("Bahnchef")

        last_name_input = self.browser.find_element(By.CSS_SELECTOR, "input[id^='nachname']")
        last_name_input.send_keys(get_control() + "a")
        last_name_input.send_keys(Keys.DELETE)
        last_name_input.send_keys("Lutz")

        guest_button = self.browser.find_element(By.CSS_SELECTOR,
                                                 "div[class='button-abschnitt'] input[id^='button.weiter.anonym']")
        guest_button.click()

        # we are now at the page where we can select the seat category
        reservation_wish_to_label = {
            ReservationOption.GROSSRAUM: "label[for='abteilart-standard-1']",
            ReservationOption.ABTEIL: "label[for='abteilart-standard-3']",
            ReservationOption.KLEINKIND: "label[for='abteilart-kleinkind-4']",
            ReservationOption.FAMILIE: "label[for='abteilart-kleinkind-5']",
            ReservationOption.NONE: "label[for='abteilart-standard-0']"
        }
        try:
            radio_btn = self.browser.find_element(By.CSS_SELECTOR,
                                                  reservation_wish_to_label[search_params.reservation_category])
            radio_btn.click()
        except:
            return [], False

        # click continue button
        button = self.browser.find_element(By.CSS_SELECTOR, "input[id='buchenwunsch-button-weiter-id']")
        button.click()

        # we are now on the page where it is shown if our wish can be fulfilled

        # get the individual sections: one section for each train
        sections = self.browser.find_elements(By.CSS_SELECTOR,
                                              "section[class^='reservierungs-details']")  # type: list[WebElement]
        # parse date from heading
        heading_text = self.browser.find_element(By.CSS_SELECTOR, "div[class*='container'] h3").text
        # assume that date is in format DD.MM.YYYY and is last part of heading
        travel_date = heading_text[-10:]
        trains = []
        for sec in sections:
            train = self._create_train_from_reservation_html(sec)
            train.start_date = travel_date
            trains.append(train)

        # go back
        self.browser.find_element(By.CSS_SELECTOR, "a[id='header.bahnbuchen.step2.button']").click()
        return trains, False

    def _click_search_reservation(self):
        search_xpath = '//*[@id="reservationButton"]'
        self.browser.find_element(By.XPATH, search_xpath).click()

    def _create_connection_from_html(self, connection_block: WebElement) -> DBConnection:
        start_time = connection_block.find_elements(By.CSS_SELECTOR,
                                                    "div[class='connectionTimeSoll']  span[class='timeDep']")[0].text
        end_time = connection_block.find_elements(By.CSS_SELECTOR,
                                                  "div[class='connectionTimeSoll']  span[class='timeArr']")[0].text

        duration = connection_block.find_elements(By.CSS_SELECTOR,
                                                  "div[class='connectionTimeSoll']  div[class='duration']")[0].text
        if duration.startswith("|"):
            duration = duration[1:]

        try:
            start_station = connection_block.find_elements(By.CSS_SELECTOR,
                                                           "div[class=connectionRoute] div[class*='first']")[0].text
        except:
            start_station = ""
        try:
            final_station = connection_block.find_elements(By.CSS_SELECTOR,
                                                           "div[class=connectionRoute] div[class*='Dest']")[0].text
        except:
            final_station = ""

        connection = DBConnection()
        connection.start_time = start_time
        connection.end_time = end_time
        connection.travel_duration = duration
        connection.start_station = start_station
        connection.final_station = final_station

        return connection

    def _create_train_from_reservation_html(self, section: WebElement) -> Train:
        train = Train()
        train.id = section.find_element(By.CSS_SELECTOR, "div[class='fs-sidebar c-number']").text

        # parse connection
        start_text = section.find_element(By.CSS_SELECTOR, "div[class='verbindung-start']  span[class='label']").text
        colon_idx = start_text.find(":")
        train.start_time = start_text[colon_idx - 2:colon_idx + 3]
        train.start_station = start_text[colon_idx + 3:].strip()

        end_text = section.find_element(By.CSS_SELECTOR, "div[class='verbindung-end']  span[class='label']").text
        colon_idx = end_text.find(":")
        train.end_time = end_text[colon_idx - 2:colon_idx + 3]
        train.final_station = end_text[colon_idx + 3:].strip()

        def parse_reservation_table(text: str):
            if ": Abteil" in text:
                train.reservation_option = ReservationOption.ABTEIL
            elif "Familie" in text:
                train.reservation_option = ReservationOption.FAMILIE
            elif "Großraum" in text or "Grossraum" in text:
                train.reservation_option = ReservationOption.GROSSRAUM
            elif "Kleinkind" in text:
                train.reservation_option = ReservationOption.KLEINKIND
            else:
                train.reservation_option = ReservationOption.NONE

        # parse reservation option
        try:
            wish_fulfilled = section.find_element(By.CSS_SELECTOR, "table[title='Wünsche erfüllbar']").text
            parse_reservation_table(wish_fulfilled)
        except:
            try:
                # check if alternative places are used
                alternative = section.find_element(By.CSS_SELECTOR, "table[title='alternative Plätze']").text
                parse_reservation_table(alternative)
            except:
                train.reservation_option = ReservationOption.NONE
        travel_duration = compute_travel_time(train.start_time, train.end_time)
        train.travel_duration = "{:0>2}:{:0>2}".format(travel_duration[0], travel_duration[1])
        return train

    def _fill_in_route(self, search_params: SearchParameters):
        start_xpath = '//*[@id="locS0"]'
        end_xpath = '//*[@id="locZ0"]'

        start_input_box = self.browser.find_element(By.XPATH, start_xpath)
        start_input_box.click()
        start_input_box.send_keys(search_params.start_station)

        end_input_box = self.browser.find_element(By.XPATH, end_xpath)
        end_input_box.click()
        end_input_box.send_keys(search_params.final_station)

    def _fill_in_date_time(self, search_params: SearchParameters):
        date_path = '//*[@id="REQ0JourneyDate"]'
        time_path = '//*[@id="REQ0JourneyTime"]'

        def set(path, val):
            elem = self.browser.find_element(By.XPATH, path)
            elem.click()
            elem.send_keys(get_control() + "a")
            elem.send_keys(Keys.DELETE)
            elem.send_keys(val)

        set(date_path, search_params.travel_date)
        set(time_path, search_params.earliest_dep_time)

    def _get_date_from_datedivider(self, element: WebElement) -> str:
        pattern = re.compile(r"\d{2}\.\d{2}\.\d{2}", re.IGNORECASE)  # search for date in format DD.mm.YY
        res = pattern.search(element.text)
        if res:
            # convert DD.mm.YY format into DD.mm.YYYY format
            date_str = res.group()
            return date_str[:-2] + "20" + date_str[-2:]
        else:
            return ""

    def _include_later_trains(self):
        try:
            later_btn = self.browser.find_element(By.CSS_SELECTOR, "div[class='timeButton']  a[class='later']")
            later_btn.click()
            return True
        except:
            return False

    def _move_to_search(self):
        path = '//*[@id="qf-search-city"]'
        search_btn = self.browser.find_element(By.XPATH, path)
        search_btn.click()

    def _parse_current_connections(self, search_params: SearchParameters) -> \
            tuple[list[tuple[int, DBConnection]], bool]:
        connection_containers = "//div[@id='resultsOverviewContainer']/div"

        try:
            containers = WebDriverWait(self.browser, 10).until(
                EC.visibility_of_all_elements_located((By.XPATH, connection_containers)))
        except:
            return [], False

        latest_connection_found = False
        relevant_connections = []
        current_date = search_params.travel_date
        for idx, element in enumerate(containers):
            if "dateDivider" in element.get_attribute("class"):
                new_date = self._get_date_from_datedivider(element)
                if new_date != "":
                    current_date = new_date
            if "overview_update" in element.get_attribute("id"):
                connection = self._create_connection_from_html(element)
                connection.start_date = current_date
                in_time = connection_in_time_interval(connection, search_params)
                if in_time == TimeCheckResult.OK:
                    relevant_connections.append((idx, connection))
                if in_time == TimeCheckResult.START_TOO_LATE or in_time == TimeCheckResult.DATE_TOO_LATE:
                    # we can assume that the data we get from the homepage is sorted by departure time
                    latest_connection_found = True
                    break

        return relevant_connections, latest_connection_found

    def _set_travelers(self, search_params: SearchParameters):
        num_travelers_xpath = "/html/body/div/div[3]/form/div[1]/div[1]/fieldset[4]/div/div[2]/select/option[{}]".format(
            search_params.num_reservations)

        self.browser.find_element(By.XPATH, num_travelers_xpath).click()

        if search_params.reservation_category == ReservationOption.KLEINKIND or \
                search_params.reservation_category == ReservationOption.FAMILIE:
            age_second_traveler_path = "/html/body/div/div[3]/form/div[1]/div[1]/fieldset[4]/div/div[4]/div[3]/div/div[2]/div/select/option[1]"
            self.browser.find_element(By.XPATH, age_second_traveler_path).click()


def main():
    search_params = SearchParameters()
    search_params.start_station = "Hannover Hbf"
    search_params.final_station = "Stuttgart Hbf"
    search_params.earliest_dep_time = "10:00"
    search_params.latest_dep_time = "21:47"
    search_params.travel_date = "01.01.2023"
    search_params.reservation_category = ReservationOption.KLEINKIND
    search_params.num_reservations = 2

    scraper = DBReservationScraper(False)
    scraper.search_reservations(search_params)


if __name__ == '__main__':
    main()
