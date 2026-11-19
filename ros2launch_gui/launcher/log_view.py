"""
Log pane: output of every launch, one launch or one process, with search.

Typing in the search box highlights every match and scrolls to the newest one; Enter
filters the view to the matching lines; editing the text again goes back to highlighting.
"""

import collections
import heapq
import html
import itertools
import re
from typing import List
from typing import Optional

from python_qt_binding.QtCore import QTimer
from python_qt_binding.QtGui import QTextCursor
from python_qt_binding.QtGui import QTextDocument
from python_qt_binding.QtWidgets import QHBoxLayout
from python_qt_binding.QtWidgets import QLabel
from python_qt_binding.QtWidgets import QLineEdit
from python_qt_binding.QtWidgets import QPlainTextEdit
from python_qt_binding.QtWidgets import QPushButton
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

from ..ansi import ansi_color_re
from ..ansi import ansi_to_html

# Lines kept per (launch, process); older lines are dropped.
MAX_LINES_PER_SOURCE = 50000
# Lines shown at most: the newest matching ones when the source or search changes.
MAX_RENDERED_LINES = 10000
# A search is applied this long after the last keystroke.
SEARCH_DELAY_MS = 250
# Lines arriving while the view is shown are added in batches at this interval.
APPEND_INTERVAL_MS = 50
HIGHLIGHT = '<span style="background:#ffd54f">{}</span>'
LAUNCH_LABEL = 'launch'

_TAG_RE = re.compile(r'(<[^>]*>)')

_Entry = collections.namedtuple('_Entry', ['seq', 'plain', 'html'])
_Shown = collections.namedtuple('_Shown', ['plain', 'match'])


def _highlight(markup: str, needle: str) -> str:
    """Wrap case-insensitive matches of needle in the text parts of escaped HTML."""
    if not needle:
        return markup
    pattern = re.compile(re.escape(html.escape(needle)), re.IGNORECASE)
    parts = _TAG_RE.split(markup)
    for i in range(0, len(parts), 2):
        parts[i] = pattern.sub(lambda m: HIGHLIGHT.format(m.group(0)), parts[i])
    return ''.join(parts)


def _paragraphs(markups: List[str]) -> str:
    return ''.join('<p>{}</p>'.format(m) for m in markups)


class LogView(QWidget):
    """Shows process output of the running launches; filterable by source and text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources = {}
        self._seq = itertools.count()
        self._launch_key = None
        self._process_name = None
        self._search = ''
        self._filter = False
        self._visible = collections.deque(maxlen=MAX_RENDERED_LINES)
        self._match_count = 0
        self._pending_html = []

        self.source_label = QLabel(self)
        self.show_all_button = QPushButton('Show all', self)
        self.show_all_button.clicked.connect(lambda: self.set_source(None, None))
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText('Search logs… (Enter: show only matching lines)')
        self.search_edit.setClearButtonEnabled(True)
        self.match_label = QLabel(self)
        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(MAX_RENDERED_LINES)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self.flush_search)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start())
        self.search_edit.returnPressed.connect(self.apply_filter)
        self._append_timer = QTimer(self)
        self._append_timer.setSingleShot(True)
        self._append_timer.setInterval(APPEND_INTERVAL_MS)
        self._append_timer.timeout.connect(self.flush_appends)

        bar = QHBoxLayout()
        bar.addWidget(self.source_label, 1)
        bar.addWidget(self.show_all_button)
        layout = QVBoxLayout()
        layout.addLayout(bar)
        search_bar = QHBoxLayout()
        search_bar.addWidget(self.search_edit, 1)
        search_bar.addWidget(self.match_label)
        layout.addLayout(search_bar)
        layout.addWidget(self.text_edit)
        self.setLayout(layout)
        self._render()

    def append(self, launch_key: str, process_name: str, text: str) -> None:
        """Add output of a process ('' for the launch's own output)."""
        key = (launch_key, process_name)
        lines = self._sources.get(key)
        if lines is None:
            lines = collections.deque(maxlen=MAX_LINES_PER_SOURCE)
            self._sources[key] = lines
        label = process_name or LAUNCH_LABEL
        in_scope = self._in_scope(key)
        for line in text.split('\n'):
            line = line.rstrip()
            if not line:
                continue
            entry = _Entry(
                seq=next(self._seq),
                plain='[{}] {}'.format(label, ansi_color_re.sub('', line)),
                html='[{}] {}'.format(html.escape(label), ansi_to_html(line)))
            lines.append(entry)
            if in_scope and self._shown(entry):
                self._show(entry)
                self._pending_html.append(_highlight(entry.html, self._search))
        if self._pending_html and not self._append_timer.isActive():
            self._append_timer.start()
        self._update_match_label()

    def set_source(self, launch_key: Optional[str], process_name: Optional[str]) -> None:
        """Show one process, one launch (process_name None) or everything (both None)."""
        process_name = process_name if launch_key is not None else None
        if (launch_key, process_name) == (self._launch_key, self._process_name):
            return
        self._launch_key = launch_key
        self._process_name = process_name
        self._render()

    def flush_search(self) -> None:
        """Highlight the search box text now instead of after the typing delay."""
        self._search_timer.stop()
        self._filter = False
        self._render()
        self._scroll_to_newest_match()

    def apply_filter(self) -> None:
        """Show only the lines matching the search box text (Enter in the box)."""
        self._search_timer.stop()
        self._filter = True
        self._render()

    def flush_appends(self) -> None:
        """Add the lines received since the last batch to the view now."""
        self._append_timer.stop()
        if self._pending_html:
            self.text_edit.appendHtml(_paragraphs(self._pending_html))
            self._pending_html = []

    def visible_lines(self) -> List[str]:
        """Return the shown lines as plain text."""
        return [shown.plain for shown in self._visible]

    def _in_scope(self, key) -> bool:
        launch_key, process_name = key
        if self._launch_key is None:
            return True
        if launch_key != self._launch_key:
            return False
        return self._process_name is None or process_name == self._process_name

    def _matches(self, entry: _Entry) -> bool:
        return bool(self._search) and self._search.lower() in entry.plain.lower()

    def _shown(self, entry: _Entry) -> bool:
        return not (self._filter and self._search) or self._matches(entry)

    def _show(self, entry: _Entry) -> None:
        """Record a shown line; the oldest one drops off at the display limit."""
        if len(self._visible) == self._visible.maxlen and self._visible[0].match:
            self._match_count -= 1
        match = self._matches(entry)
        self._visible.append(_Shown(entry.plain, match))
        self._match_count += match

    def _update_match_label(self) -> None:
        if not self._search:
            self.match_label.setText('')
        else:
            self.match_label.setText('{} match{}'.format(
                self._match_count, '' if self._match_count == 1 else 'es'))

    def _scroll_to_newest_match(self) -> None:
        if not self._match_count:
            return
        self.text_edit.moveCursor(QTextCursor.End)
        self.text_edit.find(self._search, QTextDocument.FindBackward)

    def _render(self) -> None:
        self._search = self.search_edit.text()
        if self._launch_key is None:
            self.source_label.setText('All launches')
        elif self._process_name is None:
            self.source_label.setText('Launch: {}'.format(self._launch_key))
        else:
            self.source_label.setText('Process: {} ({})'.format(
                self._process_name or LAUNCH_LABEL, self._launch_key))
        self.show_all_button.setEnabled(self._launch_key is not None)

        # Walk newest first and stop at the display limit: cost follows what is shown.
        scoped = [reversed(lines) for key, lines in self._sources.items() if self._in_scope(key)]
        newest = itertools.islice(
            (e for e in heapq.merge(*scoped, reverse=True) if self._shown(e)),
            MAX_RENDERED_LINES)
        entries = list(newest)[::-1]
        self._visible = collections.deque(maxlen=MAX_RENDERED_LINES)
        self._match_count = 0
        for entry in entries:
            self._show(entry)
        self._update_match_label()
        self._pending_html = []
        self._append_timer.stop()
        self.text_edit.clear()
        if entries:
            self.text_edit.appendHtml(
                _paragraphs([_highlight(e.html, self._search) for e in entries]))
