import multiprocessing
from db_reservation_check.gui.db_reservation_gui import start_gui


def main():
    start_gui()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
