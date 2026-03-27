import collections

import urwid


class OutputView(urwid.ListBox):
    """Log output view with per-process and total scrollback caps.

    Lines are stored in both a global deque and per-process deques so that
    filter switching is O(1) rebuild from the relevant deque.  Total memory
    may exceed MAX_TOTAL_LINES when many processes are active (bounded by
    MAX_TOTAL_LINES + num_processes * MAX_PER_PROCESS).
    """

    MAX_TOTAL_LINES = 50000
    MAX_PER_PROCESS = 10000

    def __init__(self):
        self._walker = urwid.SimpleFocusListWalker([])
        super().__init__(self._walker)
        self._all_lines = collections.deque(maxlen=self.MAX_TOTAL_LINES)
        self._per_process = {}
        self._filter = None

    def add_line(self, process_name, text):
        """Append a line of output, respecting the current filter."""
        entry = (process_name, text)
        self._all_lines.append(entry)

        if process_name not in self._per_process:
            self._per_process[process_name] = collections.deque(
                maxlen=self.MAX_PER_PROCESS)
        self._per_process[process_name].append(text)

        if self._filter is None or self._filter == process_name:
            self._append_widget(process_name, text)

    def apply_filter(self, process_name):
        """Switch output filter and rebuild the view."""
        self._filter = process_name
        del self._walker[:]
        if process_name is None:
            for name, text in self._all_lines:
                self._walker.append(self._make_widget(name, text))
        elif process_name in self._per_process:
            for text in self._per_process[process_name]:
                self._walker.append(
                    self._make_widget(process_name, text))
        self._scroll_to_bottom()

    def _append_widget(self, name, text):
        self._walker.append(self._make_widget(name, text))
        cap = self.MAX_PER_PROCESS if self._filter else self.MAX_TOTAL_LINES
        while len(self._walker) > cap:
            del self._walker[0]
        self._scroll_to_bottom()

    def _make_widget(self, name, text):
        return urwid.Text([('prefix', f'[{name}] '), text])

    def _scroll_to_bottom(self):
        if self._walker:
            self._walker.set_focus(len(self._walker) - 1)
