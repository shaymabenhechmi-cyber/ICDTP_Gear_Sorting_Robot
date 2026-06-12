from setuptools import find_packages, setup

package_name = 'robot_middleware'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/robot_middleware_launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robopi2',
    maintainer_email='user@todo.todo',
    description='Robot middleware between Unity and physical robot',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'robot_middleware_node = robot_middleware.robot_middleware_node:main',
        ],
    },
)
