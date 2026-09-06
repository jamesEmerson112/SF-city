"""
RuleValue module for OpenGlassBox simulation engine.

This module implements concrete rule value classes that allow accessing and manipulating
resources in different contexts within the simulation (global, local, map).
"""

from typing import Any
from .rule import IRuleValue, RuleContext
from .resource import Resource


class RuleValueGlobal(IRuleValue):
    """
    Rule value for accessing and manipulating global resources.
    Equivalent to C++ RuleValueGlobal class.
    """

    def __init__(self, resource: Resource):
        """
        Initialize with a resource.

        Args:
            resource: The resource to use for identifying the global resource
        """
        self.m_resource = resource

    def get(self, context: RuleContext) -> int:
        """
        Get the amount of the global resource.

        Args:
            context: The rule context containing reference to resources

        Returns:
            The amount of the global resource
        """
        return context.globals.get_amount(self.m_resource.type())

    def capacity(self, context: RuleContext) -> int:
        """
        Get the capacity of the global resource.

        Args:
            context: The rule context containing reference to resources

        Returns:
            The capacity of the global resource
        """
        return context.globals.get_capacity(self.m_resource.type())

    def add(self, context: RuleContext, to_add: int) -> None:
        """
        Add the specified amount to the global resource.

        Args:
            context: The rule context containing reference to resources
            to_add: The amount to add
        """
        context.globals.add_resource(self.m_resource.type(), to_add)

    def remove(self, context: RuleContext, to_remove: int) -> None:
        """
        Remove the specified amount from the global resource.

        Args:
            context: The rule context containing reference to resources
            to_remove: The amount to remove
        """
        context.globals.remove_resource(self.m_resource.type(), to_remove)

    def type(self) -> str:
        """
        Get the type (name) of the resource.

        Returns:
            The resource type string
        """
        return self.m_resource.type()


class RuleValueLocal(IRuleValue):
    """
    Rule value for accessing and manipulating local resources.
    Equivalent to C++ RuleValueLocal class.
    """

    def __init__(self, resource: Resource):
        """
        Initialize with a resource.

        Args:
            resource: The resource to use for identifying the local resource
        """
        self.m_resource = resource

    def get(self, context: RuleContext) -> int:
        """
        Get the amount of the local resource.

        Args:
            context: The rule context containing reference to resources

        Returns:
            The amount of the local resource
        """
        return context.locals.get_amount(self.m_resource.type())

    def capacity(self, context: RuleContext) -> int:
        """
        Get the capacity of the local resource.

        Args:
            context: The rule context containing reference to resources

        Returns:
            The capacity of the local resource
        """
        return context.locals.get_capacity(self.m_resource.type())

    def add(self, context: RuleContext, to_add: int) -> None:
        """
        Add the specified amount to the local resource.

        Args:
            context: The rule context containing reference to resources
            to_add: The amount to add
        """
        context.locals.add_resource(self.m_resource.type(), to_add)

    def remove(self, context: RuleContext, to_remove: int) -> None:
        """
        Remove the specified amount from the local resource.

        Args:
            context: The rule context containing reference to resources
            to_remove: The amount to remove
        """
        context.locals.remove_resource(self.m_resource.type(), to_remove)

    def type(self) -> str:
        """
        Get the type (name) of the resource.

        Returns:
            The resource type string
        """
        return self.m_resource.type()


class RuleValueMap(IRuleValue):
    """
    Rule value for accessing and manipulating map resources.
    Equivalent to C++ RuleValueMap class.
    """

    def __init__(self, map_id: str):
        """
        Initialize with a map ID.

        Args:
            map_id: The ID of the map to access
        """
        self.m_mapId = map_id

    def get(self, context: RuleContext) -> int:
        """
        Get the amount of the map resource at the specified location.

        Args:
            context: The rule context containing reference to resources

        Returns:
            The amount of the map resource
        """
        return context.city.get_map(self.m_mapId).get_resource(context.u, context.v, context.radius)

    def capacity(self, context: RuleContext) -> int:
        """
        Get the capacity of the map resource.

        Args:
            context: The rule context containing reference to resources

        Returns:
            The capacity of the map resource
        """
        return context.city.get_map(self.m_mapId).get_capacity()

    def add(self, context: RuleContext, to_add: int) -> None:
        """
        Add the specified amount to the map resource at the specified location.

        Args:
            context: The rule context containing reference to resources
            to_add: The amount to add
        """
        context.city.get_map(self.m_mapId).add_resource(context.u, context.v, context.radius, to_add)

    def remove(self, context: RuleContext, to_remove: int) -> None:
        """
        Remove the specified amount from the map resource at the specified location.

        Args:
            context: The rule context containing reference to resources
            to_remove: The amount to remove
        """
        context.city.get_map(self.m_mapId).remove_resource(context.u, context.v, context.radius, to_remove)

    def type(self) -> str:
        """
        Get the type (name) of the map.

        Returns:
            The map ID
        """
        return self.m_mapId
