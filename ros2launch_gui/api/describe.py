
from launch import Action
from launch import Condition
from launch import LaunchContext
from launch import LaunchDescription
from launch import LaunchDescriptionEntity
from launch.launch_introspector import format_action
from launch.launch_introspector import format_substitutions
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.utilities import normalize_to_list_of_substitutions
from launch.utilities import perform_substitutions

from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace
from launch_ros.actions import SetParameter
from launch_ros.actions import SetParametersFromFile


class DescribedLaunchEntity:
    """A human readable description of launch entity and its children.
    This is used to decouple the launch context from the description to be used
    in a GUI which may be running in a different thread.
    """

    def __init__(
            self,
            launch_entity: LaunchDescriptionEntity,
            context: LaunchContext = None
    ):
        if launch_entity is None:
            self.type_name = 'None'
            self.label = ''
            self.description = ''
            self.id = 0

        self.id = id(launch_entity)

        self.type_name = type(launch_entity).__name__
        self.label = ''
        if isinstance(launch_entity, Action):
            try:
                self.description = format_action(launch_entity)
            except Exception as e:
                self.description = str(e)
        else:
            try:
                self.description = launch_entity.describe()
            except NotImplementedError:
                self.description = ''

        self.conditional_children = []

        # IncludeLaunchDescription's describe_sub_entities() method returns temporary entities with different ids than the entities actually run, so try to get the real ones.
        if isinstance(launch_entity, IncludeLaunchDescription):
            try:
                self.children = [DescribedLaunchEntity(launch_entity.launch_description_source.get_launch_description(context)),]
            except Exception as e:
                self.children = []
        else:
            self.children = [DescribedLaunchEntity(child) for child in launch_entity.describe_sub_entities()]
            for condition, sub_entities in launch_entity.describe_conditional_sub_entities():
                self.conditional_children.append((condition, [DescribedLaunchEntity(child) for child in sub_entities]))

        self.condition = None
        if isinstance(launch_entity, Action):
            if launch_entity.condition is not None:
                self.condition = describe_condition(launch_entity.condition, context)

        if isinstance(launch_entity, IncludeLaunchDescription):
            self.description = launch_entity.launch_description_source.location
            self.launch_arguments = []
            for la in launch_entity.launch_arguments:
                try:
                    la0 = describe_substitution(la[0], context)
                except Exception as e:
                    la0 = str(la[0])
                try:
                    la1 = describe_substitution(la[1], context)
                except Exception as e:
                    la1 = str(la[1])
                self.launch_arguments.append((la0, la1))

        elif isinstance(launch_entity, DeclareLaunchArgument):
            self.label = str(launch_entity.name)
            if context is not None and launch_entity.name in context.launch_configurations:
                self.description = context.launch_configurations[launch_entity.name]
            else:
                self.description = describe_substitution(launch_entity.default_value, context)

        elif isinstance(launch_entity, SetParameter):
            self.label = describe_substitution(launch_entity.name, context)
            self.description = describe_substitution(launch_entity.value, context)

        elif isinstance(launch_entity, SetParametersFromFile):
            self.description = describe_substitution(launch_entity._input_file, context)

        elif isinstance(launch_entity, Node):
            try:
                self.label = launch_entity.node_name
            except RuntimeError:
                pass
            self.description = "package: {}, executable: {}".format(launch_entity.node_package, launch_entity.node_executable)
        
        elif isinstance(launch_entity, PushRosNamespace):
            self.label = describe_substitution(launch_entity.namespace, context)
            self.description = describe_substitution(launch_entity.namespace, None)




    def __repr__(self):
        return 'id: {} ({}) name: {} desc: {}'.format(self.id, self.type_name, self.label, self.description)

def describe_condition(condition: Condition, context: LaunchContext) -> str:
    if condition is not None:
        value = '?'
        if context is not None:
            try:
                value = condition.evaluate(context)
            except Exception as e:
                value = str(e)
        return '{}: {}'.format(type(condition).__name__, value)
    return ''

def describe_substitution(substitution, context: LaunchContext) -> str:
    if substitution is None:
        return ''
    try:
        if context is not None:
            return perform_substitutions(context, normalize_to_list_of_substitutions(substitution))
        else:
            return format_substitutions(substitution)
    except Exception as e:
        print(e)
        return str(substitution)
