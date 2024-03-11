import re
import requests
import http.client
import db_reservation_check

DEFAULT_VERSION = ("0", "0", "0")


def internet_available() -> bool:
    connection = http.client.HTTPSConnection("8.8.8.8", timeout=3)
    try:
        connection.request("HEAD", "/")
        return True
    except Exception:
        return False
    finally:
        connection.close()


def get_latest_version() -> tuple[str, str, str]:
    regex = "^v\d+\.\d+\.\d+$"
    repo_query = "https://api.github.com/repos/oleschum/dbressuche/releases/latest"
    try:
        response = requests.get(repo_query)
    except requests.exceptions.RequestException as e:
        return DEFAULT_VERSION

    if "tag_name" not in response.json():
        return DEFAULT_VERSION
    tag_name = response.json()["tag_name"]
    version = re.match(regex, tag_name)
    if version:
        version = version.group()
        version = version[1:]
        major, minor, patch = version.split(".")
        return major, minor, patch
    else:
        return DEFAULT_VERSION


def is_up_to_date():
    this_version = db_reservation_check.__version__.split(".")
    latest_version = get_latest_version()
    if latest_version == DEFAULT_VERSION:
        return True
    return all([x == y for x, y in zip(map(int, this_version), map(int, latest_version))])
