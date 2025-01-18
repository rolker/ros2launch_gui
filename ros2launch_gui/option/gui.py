
from launch import LaunchDescription

from ros2launch_gui.actions import DisplayUserInterface
from ros2launch.option import OptionExtension

from typing import Tuple


class GuiOption(OptionExtension):

    def add_arguments(self, parser, cli_name, *, argv=None):
        parser.add_argument(
            '-g', '--gui',
            action='store_true',
            help='Display launch status in a GUI'
        )

    def prelaunch(
        self,
        launch_description: LaunchDescription,
        args
    ) -> Tuple[LaunchDescription,]:
        if(args.gui):
            return LaunchDescription(
                [
                    DisplayUserInterface(launch_description=launch_description, debug=args.debug),
                ]
            ),

        return launch_description, 


