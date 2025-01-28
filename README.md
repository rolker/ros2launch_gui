# ROS 2 Launch GUI

This package provides a Graphical User Interface for the ROS 2 Launch System.

![Example screenshot](./doc/ros2_launch_gui_example.png)

The above screenshot is from running:

    ros2 launch -g turtlesim multisim.launch.py

On the left is a tree representation of the launch description while on the right, the output of each process is separated into tabs.

For a more complex example, here is a screenshot from the nav2 tutorial.

![Nav2 example screenshot](./doc/ros2_launch_gui_nav2_example.png)

## Command line option

An option is add to the `ros2 launch command for enabling a gui.

    ros2 launch --gui my_package my_launch.py

or

    ros2 launch -g my_package my_launch.xml

## DisplayUserInterface action

This is a work in progress...
