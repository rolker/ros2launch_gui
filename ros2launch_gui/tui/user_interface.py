import re

from launch import LaunchDescription

import urwid

from .output_view import OutputView
from .process_list import ProcessList
from .status_bar import StatusBar
from ..api import DescribedLaunchEntity
from ..api import UserInterface as UserInterfaceBase

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

PALETTE = [
    ('running', 'light green', ''),
    ('exited', 'light gray', ''),
    ('crashed', 'light red', ''),
    ('focused', 'black', 'light gray'),
    ('header', 'white,bold', 'dark blue'),
    ('status_bar', 'white', 'dark blue'),
    ('prefix', 'light cyan', ''),
]


class UserInterface(UserInterfaceBase):
    def __init__(
            self,
            launch_description: LaunchDescription,
            debug: bool = False
    ):
        super().__init__(launch_description, debug)

        self.process_list = ProcessList()
        self.output_view = OutputView()
        self.status_bar = StatusBar()

        process_header = urwid.AttrMap(
            urwid.Text(' Processes'), 'header')
        self._output_header_text = urwid.Text(' Output (all)')
        output_header = urwid.AttrMap(
            self._output_header_text, 'header')

        body = urwid.Pile([
            ('pack', process_header),
            ('weight', 1, self.process_list),
            ('pack', output_header),
            ('weight', 3, self.output_view),
        ])

        frame = urwid.Frame(
            body=body,
            footer=urwid.AttrMap(self.status_bar, 'status_bar'),
        )

        self.screen = urwid.raw_display.Screen()
        self.loop = urwid.MainLoop(
            frame,
            palette=PALETTE,
            screen=self.screen,
            unhandled_input=self._handle_input,
        )
        self.loop.start()
        self.screen.set_input_timeouts(max_wait=0)

        self._output_filter = None

    def spin_once(self):
        if self.close_requested:
            return
        self.loop.draw_screen()
        keys = self.screen.get_input()
        for key in keys:
            self.loop.process_input([key])

    def close(self):
        super().close()
        try:
            self.loop.stop()
        except Exception:
            pass

    def on_process_started(self, process_name, pid,
                           action: DescribedLaunchEntity):
        self.process_list.add_process(process_name, pid)

    def on_process_exited(self, process_name, pid, action, return_code):
        self.process_list.update_process_status(
            process_name, return_code)

    def on_process_io(self, process_name, text):
        decoded = text.decode() if isinstance(text, bytes) else text
        clean = _ANSI_RE.sub('', decoded)
        for line in clean.splitlines():
            self.output_view.add_line(process_name, line)

    def on_close(self):
        super().on_close()

    def _handle_input(self, key):
        if key in ('q', 'Q'):
            self.on_close()
        elif key == 'enter':
            name = self.process_list.get_focused_process()
            if name is not None:
                if self._output_filter == name:
                    self._output_filter = None
                    self._output_header_text.set_text(' Output (all)')
                else:
                    self._output_filter = name
                    self._output_header_text.set_text(
                        f' Output ({name})')
                self.output_view.apply_filter(self._output_filter)
