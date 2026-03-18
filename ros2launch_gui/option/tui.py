from typing import Tuple

from launch import LaunchDescription

from ros2launch.option import OptionExtension
from ros2launch_gui.actions import DisplayUserInterface


def _create_tui(launch_description, context, debug):
    from ros2launch_gui.tui import UserInterface
    return UserInterface(launch_description, debug)


class TuiOption(OptionExtension):

    def add_arguments(self, parser, cli_name, *, argv=None):
        parser.add_argument(
            '-t', '--tui',
            action='store_true',
            help='Display launch status in a terminal UI'
        )

    def prelaunch(
        self,
        launch_description: LaunchDescription,
        args
    ) -> Tuple[LaunchDescription,]:
        if args.tui:
            if hasattr(args, 'gui') and args.gui:
                raise ValueError(
                    '--tui and --gui are mutually exclusive')
            return LaunchDescription(
                [
                    DisplayUserInterface(
                        launch_description=launch_description,
                        ui_launcher=_create_tui,
                        debug=args.debug),
                ]
            ),

        return launch_description,
