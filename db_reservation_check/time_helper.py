from datetime import datetime, timedelta


class TimeCheckResult:
    OK = 0
    DATE_TOO_EARLY = 1
    DATE_TOO_LATE = 2
    START_TOO_EARLY = 3
    START_TOO_LATE = 4


def get_time_diff(time1: str, time2: str, fmt="%H:%M") -> timedelta:
    """
    Compute the difference between the two time time1 and time2, i.e. time1 - time2
    :param time1:
    :param time2:
    :param fmt:
    :return: difference as a timedelta object.
    """
    return datetime.strptime(time1, fmt) - datetime.strptime(time2, fmt)


def convert_duration_format(text: str) -> str:
    """
    Input format is expected to be of form "10h 34min".
    Output format is "10:34"
    :param text: input time as string in format "xxh yymin"
    :return: time as string in format hh:mm
    """
    if "min" in text and "h" in text:
        h = text[:text.find("h")].strip()
        mins = text[text.find("h") + 1:text.find("min")].strip()
        text = "{}:{}".format(h, mins)
    return text


def compute_travel_time(start_time: str, end_time: str, fmt="%H:%M") -> tuple[int, int, int]:
    time_delta = get_time_diff(end_time, start_time, fmt)
    if time_delta.days < 0:  # assume midnight has passed and assume that end_time is always later than start_time
        time_delta = timedelta(days=0, seconds=time_delta.seconds)
    m, s = divmod(time_delta.total_seconds(), 60)
    h, m = divmod(m, 60)
    return int(h), int(m), int(s)


def connection_in_time_interval(connection, search_params) -> int:
    date_connection = datetime.strptime(connection.start_date, "%d.%m.%y").date()
    date_search = datetime.strptime(search_params.travel_date, "%d.%m.%y").date()
    if date_connection < date_search:
        return TimeCheckResult.DATE_TOO_EARLY
    if date_connection > date_search:
        return TimeCheckResult.DATE_TOO_LATE

    time_diff = get_time_diff(connection.start_time, search_params.earliest_dep_time)
    if time_diff.total_seconds() < 0:
        # this means that start time of the connection is earlier than wanted earliest departure time
        return TimeCheckResult.START_TOO_EARLY

    if search_params.latest_dep_time != "":
        time_diff = get_time_diff(connection.start_time, search_params.latest_dep_time)
        if time_diff.total_seconds() > 0:
            # this means that start time of the connection is later than wanted latest departure time
            return TimeCheckResult.START_TOO_LATE
    return TimeCheckResult.OK
