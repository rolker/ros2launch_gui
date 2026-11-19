import os
import time

import pytest
from python_qt_binding.QtCore import Qt
from python_qt_binding.QtTest import QTest
from python_qt_binding.QtWidgets import QApplication

from ros2launch_gui.launcher import log_view
from ros2launch_gui.launcher.log_view import LogView


@pytest.fixture(scope='module')
def qapp():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp):
    widget = LogView()
    widget.append('L1', 'a', 'one\n')
    widget.append('L1', 'b', 'two\n\n')
    widget.append('L2', 'a', 'three')
    return widget


def test_filter_by_source(view):
    assert view.visible_lines() == ['[a] one', '[b] two', '[a] three']
    view.set_source('L1', None)
    assert view.visible_lines() == ['[a] one', '[b] two']
    view.set_source('L1', 'b')
    assert view.visible_lines() == ['[b] two']
    view.append('L1', 'b', 'four')
    view.append('L1', 'a', 'not shown')
    assert view.visible_lines() == ['[b] two', '[b] four']
    view.show_all_button.click()
    assert len(view.visible_lines()) == 5


def highlighted(widget):
    # Qt re-serialises the highlight span as background-color.
    return 'background-color:#ffd54f' in widget.text_edit.document().toHtml().replace(' ', '')


def type_search(widget, text):
    """Type into the search box and let the typing delay pass: highlight only."""
    widget.search_edit.setText(text)
    widget.flush_search()


def search(widget, text):
    """Type into the search box and press Enter: filter to matching lines."""
    widget.search_edit.setText(text)
    QTest.keyClick(widget.search_edit, Qt.Key_Return)


def test_search_is_debounced(qapp, view):
    view.search_edit.setText('one')
    assert not highlighted(view)  # not re-rendered on the keystroke
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not highlighted(view):
        qapp.processEvents()
        time.sleep(0.02)
    assert highlighted(view)
    assert len(view.visible_lines()) == 3


def test_typing_highlights_without_filtering(view):
    type_search(view, 'one')
    assert view.visible_lines() == ['[a] one', '[b] two', '[a] three']
    assert highlighted(view)
    assert view.match_label.text() == '1 match'
    view.append('L2', 'c', 'zzz')
    view.append('L2', 'c', 'one more')
    view.flush_appends()
    assert view.visible_lines()[-2:] == ['[c] zzz', '[c] one more']
    assert view.match_label.text() == '2 matches'


def test_typing_scrolls_to_newest_match(qapp):
    widget = LogView()
    widget.append('L', 'p', 'x one\ny\nz one\n' + '\n'.join(str(i) for i in range(500)))
    type_search(widget, 'ONE')
    cursor = widget.text_edit.textCursor()
    assert cursor.selectedText().lower() == 'one'
    assert cursor.block().text() == '[p] z one'


def test_enter_filters_and_editing_returns_to_highlight(view):
    search(view, 'one')
    assert view.visible_lines() == ['[a] one']
    assert view.match_label.text() == '1 match'
    type_search(view, 'tw')
    assert view.visible_lines() == ['[a] one', '[b] two', '[a] three']
    assert highlighted(view)
    type_search(view, '')
    assert view.match_label.text() == ''
    assert not highlighted(view)


def test_enter_with_empty_search_shows_all(view):
    search(view, '')
    assert len(view.visible_lines()) == 3


def test_reselecting_same_source_does_not_rerender(view, monkeypatch):
    view.set_source('L1', None)
    calls = []
    monkeypatch.setattr(view, '_render', lambda: calls.append(1))
    view.set_source('L1', None)
    assert calls == []


def test_render_is_fast_with_full_buffers(qapp):
    widget = LogView()
    for source in ('a', 'b'):
        for start in range(0, 50000, 5000):
            widget.append('L', source, '\n'.join(
                'line {} of {} with \x1b[31mcolour\x1b[0m'.format(i, source)
                for i in range(start, start + 5000)))
    t0 = time.monotonic()
    widget.set_source('L', 'a')
    widget.set_source(None, None)
    search(widget, 'line 4')
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5, elapsed
    assert len(widget.visible_lines()) <= log_view.MAX_RENDERED_LINES
    assert widget.visible_lines()[-1] == '[b] line 49999 of b with colour'


def test_search_case_insensitive(view):
    search(view, 'ONE')
    assert view.visible_lines() == ['[a] one']
    assert highlighted(view)
    view.append('L2', 'c', 'gone with the wind')
    view.append('L2', 'c', 'zzz')
    assert view.visible_lines() == ['[a] one', '[c] gone with the wind']
    search(view, '')
    assert len(view.visible_lines()) == 5


def test_search_with_html_chars(qapp):
    widget = LogView()
    widget.append('L', 'p', 'if a<b && c\x1b[31m red\x1b[0m')
    widget.append('L', 'p', 'other')
    search(widget, 'a<b &&')
    assert widget.visible_lines() == ['[p] if a<b && c red']
    search(widget, 'C RED')
    assert widget.visible_lines() == ['[p] if a<b && c red']


def test_launch_output_label(qapp):
    widget = LogView()
    widget.append('L', '', '[INFO] [launch]: Default logging verbosity')
    assert widget.visible_lines() == ['[launch] [INFO] [launch]: Default logging verbosity']


def test_line_cap(qapp, monkeypatch):
    monkeypatch.setattr(log_view, 'MAX_LINES_PER_SOURCE', 5)
    widget = LogView()
    widget.append('L', 'p', '\n'.join(str(i) for i in range(8)))
    widget.flush_search()  # re-render from the stored (capped) buffer
    assert widget.visible_lines() == ['[p] {}'.format(i) for i in range(3, 8)]
