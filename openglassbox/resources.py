"""
Resources module for OpenGlassBox simulation engine.

This module implements the Resources class, which is a container for Resource objects.
Resources allows managing collections of heterogeneous resources with operations for
finding, adding, removing, and transferring resources between containers.
"""

from typing import List, Optional, Dict, Any
from .resource import Resource


class Resources:
    """
    Resources container that manages a collection of heterogeneous resources.

    Resources come in a container. This class manages a collection of
    heterogeneous resources. Resources are initially empty but with infinite
    capacity by default.

    Example: House = { Citizen 0/2, Money 1/10, Electricity 3/3, Trash 0/1 }.
    """

    def __init__(self):
        """
        Initialize an empty resources container.
        """
        self.m_bin: List[Resource] = []

    def find_resource(self, resource_type: str) -> Optional[Resource]:
        """
        Search for a resource given its type.

        Args:
            resource_type: The type of resource (e.g., "Water")

        Returns:
            The resource if present, None if not found
        """
        for resource in self.m_bin:
            if resource.type() == resource_type:
                return resource
        return None

    def find_or_add_resource(self, resource_type: str) -> Resource:
        """
        Search for a resource given its name. If the resource is not
        present, create one and store it before returning its reference.

        Args:
            resource_type: The type of resource (e.g., "Water")

        Returns:
            The reference of the resource already stored or the newly created
        """
        resource = self.find_resource(resource_type)
        if resource is not None:
            return resource

        new_resource = Resource(resource_type)
        self.m_bin.append(new_resource)
        return new_resource

    def add_resource(self, resource_type: str, amount: int) -> Resource:
        """
        Find an existing resource in the collection. If not found,
        create and store a new resource with the current amount. If the resource
        already exists, increase its amount of resource (limited by its capacity).

        Args:
            resource_type: The type of resource
            amount: Increase the current amount of resource by the given quantity

        Returns:
            The found resource or newly created resource
        """
        resource = self.find_or_add_resource(resource_type)
        resource.add(amount)
        return resource

    def remove_resource(self, resource_type: str, amount: int) -> bool:
        """
        Reduce a given quantity of resource. If the resource does not
        exist, this function does nothing.

        Note: This method does not delete a type of resource but acts on the
        amount of resource.

        Args:
            resource_type: The type of resource
            amount: The amount to reduce

        Returns:
            Boolean indicating if the desired resource has been found
        """
        resource = self.find_resource(resource_type)
        if resource is not None:
            resource.remove(amount)
            return True
        return False

    def add_resources(self, resources_to_add: 'Resources') -> None:
        """
        Add a collection of resources. Apply addResource() for each type
        of resource.

        Args:
            resources_to_add: What resources and what amount to increase
        """
        if self is resources_to_add:
            return

        for resource in resources_to_add.m_bin:
            self.add_resource(resource.type(), resource.get_amount())

    def remove_resources(self, resources_to_reduce: 'Resources') -> None:
        """
        Apply removeResource() for each resource in the collection.

        Args:
            resources_to_reduce: What resources and what amount to reduce
        """
        if self is resources_to_reduce:
            return

        for resource in resources_to_reduce.m_bin:
            self.remove_resource(resource.type(), resource.get_amount())

    def can_add_some_resources(self, resources_to_try_add: 'Resources') -> bool:
        """
        Check if we can add at least one resource.

        Conditions are: identical resource type and recipient shall not be full.

        Args:
            resources_to_try_add: What resources and what amount to add

        Returns:
            True if it is possible to add at least one resource, else False
        """
        if self is resources_to_try_add:
            return False

        for resource in resources_to_try_add.m_bin:
            if resource.has_amount():
                my_resource = self.find_resource(resource.type())
                if my_resource is not None and my_resource.get_amount() < my_resource.get_capacity():
                    return True
        return False

    def transfer_resources_to(self, resources_target: 'Resources') -> None:
        """
        Transfer all resources to the recipient. For each resource the
        amount of resource is limited by the capacity of the recipient.

        Args:
            resources_target: The recipient resources container
        """
        if self is resources_target:
            return

        for resource in self.m_bin:
            resource.transfer_to(resources_target.find_or_add_resource(resource.type()))

    def get_amount(self, resource_type: str) -> int:
        """
        Return the amount of resource of the given type.
        If the resource does not exist, return 0.

        Args:
            resource_type: The type of resource to check

        Returns:
            The amount of the resource or 0 if not found
        """
        resource = self.find_resource(resource_type)
        return resource.get_amount() if resource is not None else 0

    def set_capacity(self, resource_type: str, capacity: int) -> None:
        """
        Find an existing resource in the collection and change its
        capacity. If the resource has not been found then create and store a new
        resource with the current capacity. If the resource is already present
        then its capacity is changed and the current amount of resource is
        limited to the newly capacity.

        Args:
            resource_type: The type of resource
            capacity: The new capacity
        """
        resource = self.find_or_add_resource(resource_type)
        resource.set_capacity(capacity)

    def set_capacities(self, resources_capacities: 'Resources') -> None:
        """
        Apply setCapacity() to a collection of resources.

        Args:
            resources_capacities: Resources container with capacity information
        """
        for resource in resources_capacities.m_bin:
            self.set_capacity(resource.type(), resource.get_capacity())

    def get_capacity(self, resource_type: str) -> int:
        """
        Return the maximal amount of resource of the given type.
        If the resource does not exist, return 0.

        Args:
            resource_type: The type of resource to check

        Returns:
            The capacity of the resource or 0 if not found
        """
        resource = self.find_resource(resource_type)
        return resource.get_capacity() if resource is not None else 0

    def is_empty(self) -> bool:
        """
        Return true if all resources are empty.

        Returns:
            True if all resources have zero amount, False otherwise
        """
        for resource in self.m_bin:
            if resource.has_amount():
                return False
        return True

    def has_resource(self, resource_type: str) -> bool:
        """
        Return true if the resource of the given type is present in the
        collection.

        Args:
            resource_type: The type of resource to check

        Returns:
            True if the resource exists in the collection, False otherwise
        """
        return self.find_resource(resource_type) is not None

    def container(self) -> List[Resource]:
        """
        Return read-only access to resources (for debug purposes).

        Returns:
            The list of resources in this container
        """
        return self.m_bin.copy()

    def __len__(self) -> int:
        """Return the number of resource types in this container."""
        return len(self.m_bin)

    def __iter__(self):
        """Iterate over Resource objects in this container."""
        return iter(self.m_bin)

    def empty(self) -> bool:
        """Alias for is_empty(). Return true if all resources are empty."""
        return self.is_empty()

    def __str__(self) -> str:
        """
        Return a string representation of the resources.

        Returns:
            A formatted string showing all resources in the container
        """
        result = f"{len(self.m_bin)} Resources:\n"
        for resource in self.m_bin:
            result += f"  {resource}\n"
        return result

    def __repr__(self) -> str:
        """
        Return a representation of the resources for debugging.

        Returns:
            A string representation of the resources container
        """
        resources = ', '.join([repr(resource) for resource in self.m_bin])
        return f"Resources([{resources}])"
