from PySide6 import QtWidgets, QtCore, QtGui


class AutocompleteLineEdit(QtWidgets.QLineEdit):
    def __init__(self, completion_entries, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.completions = set(completion_entries)
        completer = QtWidgets.QCompleter(completion_entries)
        completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completer)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        prev_text = self.text()
        super().keyPressEvent(event)
        new_text = self.text()
        self.completer().setCompletionPrefix(new_text)
        if self.completer().completionCount() == 0:
            self.setText(prev_text)
            self.completer().setCompletionPrefix(prev_text)
        return

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        if self.text() != "" and self.text() not in self.completions:
            self.setText(self.completer().currentCompletion())
        super().focusOutEvent(event)
