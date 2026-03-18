import unittest
from unittest.mock import MagicMock, patch

from launch import LaunchDescription


class TestTuiUserInterface(unittest.TestCase):
    """Smoke tests for TUI backend initialisation."""

    @patch('urwid.MainLoop')
    @patch('urwid.raw_display.Screen')
    def test_init_and_close(self, mock_screen_cls, mock_loop_cls):
        mock_screen = MagicMock()
        mock_screen_cls.return_value = mock_screen
        mock_loop = MagicMock()
        mock_loop_cls.return_value = mock_loop
        mock_loop.screen = mock_screen

        from ros2launch_gui.tui.user_interface import UserInterface

        ld = LaunchDescription()
        ui = UserInterface(ld)

        assert not ui.close_requested
        assert ui.process_list is not None
        assert ui.output_view is not None

        mock_loop.start.assert_called_once()

        ui.close()
        assert ui.close_requested
        mock_loop.stop.assert_called_once()

    @patch('urwid.MainLoop')
    @patch('urwid.raw_display.Screen')
    def test_process_lifecycle(self, mock_screen_cls, mock_loop_cls):
        mock_screen_cls.return_value = MagicMock()
        mock_loop = MagicMock()
        mock_loop_cls.return_value = mock_loop
        mock_loop.screen = mock_screen_cls.return_value

        from ros2launch_gui.tui.user_interface import UserInterface
        from ros2launch_gui.api.describe import DescribedLaunchEntity

        ld = LaunchDescription()
        ui = UserInterface(ld)

        action = MagicMock(spec=DescribedLaunchEntity)
        ui.on_process_started('test_node', 1234, action)
        assert 'test_node' in ui.process_list._items

        ui.on_process_io('test_node', b'hello world\n')
        assert len(ui.output_view._walker) == 1

        ui.on_process_exited('test_node', 1234, action, 0)

        ui.close()

    @patch('urwid.MainLoop')
    @patch('urwid.raw_display.Screen')
    def test_output_filter_toggle(self, mock_screen_cls, mock_loop_cls):
        mock_screen_cls.return_value = MagicMock()
        mock_loop = MagicMock()
        mock_loop_cls.return_value = mock_loop
        mock_loop.screen = mock_screen_cls.return_value

        from ros2launch_gui.tui.user_interface import UserInterface

        ld = LaunchDescription()
        ui = UserInterface(ld)

        action = MagicMock()
        ui.on_process_started('node_a', 100, action)
        ui.on_process_started('node_b', 101, action)
        ui.on_process_io('node_a', b'line a\n')
        ui.on_process_io('node_b', b'line b\n')

        assert len(ui.output_view._walker) == 2

        # Filter to node_a
        ui.output_view.apply_filter('node_a')
        assert len(ui.output_view._walker) == 1

        # Back to all
        ui.output_view.apply_filter(None)
        assert len(ui.output_view._walker) == 2

        ui.close()


if __name__ == '__main__':
    unittest.main()
