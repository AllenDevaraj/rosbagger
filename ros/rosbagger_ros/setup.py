from glob import glob

from setuptools import setup

package_name = "rosbagger_ros"

setup(
    name=package_name,
    version="0.2.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Allen Devaraj",
    maintainer_email="allendevaraj33333@gmail.com",
    description="ROS 2 bringup for rosbagger — launch the desktop cockpit GUI.",
    license="MIT",
    entry_points={"console_scripts": []},
)
