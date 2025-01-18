
from launch import Event

class QueryUserInterface(Event):
    """Event sent at regular interval to collect Actions from a user interface"""

    name = 'ros2launch_gui.events.QueryUserInterface'

    def __init__(self):
        super().__init__()
