from setuptools import find_packages, setup

package_name = 'ros2launch_gui'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Roland Arsenault',
    maintainer_email='roland@ccom.unh.edu',
    description='Provides a gui option to the ros2 launch command',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'ros2launch.option': [
          'gui = ros2launch_gui.option.gui:GuiOption',
          'tui = ros2launch_gui.option.tui:TuiOption',
        ],
    },
)
