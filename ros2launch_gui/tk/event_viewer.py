from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ros2launch_gui.api import DescribedEvent

class EventViewer(ttk.Frame):
    """A widget that shows launch events."""
    
    def __init__(self, parent=None):
        super().__init__(parent)

        self.text = ScrolledText(self, state='disabled')
        self.text.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def on_event(self, event: DescribedEvent) -> None:
        self.text.config(state='normal')
        self.text.insert('end', '{}\n'.format(event))
        #self.text.see('end')
        self.text.config(state='disabled')

            
        