import urwid


class ProcessListItem(urwid.WidgetWrap):
    """A single process entry in the process list."""

    RUNNING = ('running', '\u25cf RUNNING')
    EXITED = ('exited', '\u25cb EXITED')
    CRASHED = ('crashed', '\u2717 CRASHED')

    def __init__(self, shortcut, name, pid):
        self.process_name = name
        self.pid = pid
        self._status = self.RUNNING

        self._status_widget = urwid.Text(self._status)
        cols = urwid.Columns([
            ('fixed', 4, urwid.Text(f'[{shortcut}]')),
            ('weight', 1, urwid.Text(name)),
            ('fixed', 12, self._status_widget),
            ('fixed', 12, urwid.Text(f'pid:{pid}')),
        ], dividechars=1)
        super().__init__(urwid.AttrMap(cols, None, focus_map='focused'))

    def update_status(self, return_code):
        if return_code == 0:
            self._status = self.EXITED
        else:
            self._status = self.CRASHED
        self._status_widget.set_text(self._status)

    def selectable(self):
        return True

    def keypress(self, size, key):
        return key


class ProcessList(urwid.ListBox):
    """Scrollable list of launched processes with status indicators."""

    def __init__(self):
        self._walker = urwid.SimpleFocusListWalker([])
        self._items = {}
        self._next_shortcut = ord('a')
        super().__init__(self._walker)

    def add_process(self, name, pid):
        if name in self._items:
            existing = self._items[name]
            existing.pid = pid
            existing._status = ProcessListItem.RUNNING
            existing._status_widget.set_text(existing._status)
            return
        shortcut = chr(self._next_shortcut) \
            if self._next_shortcut <= ord('z') else '?'
        if self._next_shortcut <= ord('z'):
            self._next_shortcut += 1
        item = ProcessListItem(shortcut, name, pid)
        self._items[name] = item
        self._walker.append(item)

    def update_process_status(self, name, return_code):
        if name in self._items:
            self._items[name].update_status(return_code)

    def get_focused_process(self):
        if self._walker:
            widget, _ = self._walker.get_focus()
            if widget is not None and hasattr(widget, 'process_name'):
                return widget.process_name
        return None
