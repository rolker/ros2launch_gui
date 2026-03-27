import urwid


class StatusBar(urwid.Text):
    """Bottom bar showing keybinding hints."""

    def __init__(self):
        super().__init__(
            ' [q]uit  [Enter] select process  '
            '[Up/Down] navigate')
