"""
Resource module for OpenGlassBox simulation engine.

This module implements the Resource class, which represents the basic currency
of the simulation. Resources have a type, amount, and capacity.
"""

import sys
from typing import Any, Optional


class Resource:
    """
    Resource is the basic currency of the simulation defined by its type, amount and capacity.

    A game Unit can hold an amount of resource R which cannot exceed a fixed-size capacity C.
    Examples of resources:
    - Citizen, cars, goods ...
    - Oil, coal, wood, water, electricity ...
    - Money, food, labour, pollution, trash ...
    - Happiness, sickness, taxes.
    """

    # Maximum possible capacity (equivalent to uint32_t max in C++)
    MAX_CAPACITY: int = 2**32 - 1

    def __init__(self, resource_type: str, capacity: int = None):
        """
        Initialize a resource with zero amount and optional capacity.

        Args:
            resource_type: The type of resource (e.g., "water", "oil", "electricity")
            capacity: Optional capacity (defaults to MAX_CAPACITY if not specified)
        """
        self.m_type: str = resource_type
        self.m_capacity: int = capacity if capacity is not None else Resource.MAX_CAPACITY
        self.m_amount: int = 0

    def add(self, to_add: int) -> None:
        """
        Increase the current amount of resource by a given quantity.
        The result is limited by the capacity.

        Args:
            to_add: The amount to add
        """
        # Avoid integer overflow
        if self.m_amount >= Resource.MAX_CAPACITY - to_add:
            self.m_amount = Resource.MAX_CAPACITY
        else:
            self.m_amount += to_add

        # Limit by capacity
        if self.m_amount > self.m_capacity:
            self.m_amount = self.m_capacity

    def remove(self, to_remove: int) -> None:
        """
        Decrease the current amount of resource by a given quantity.
        The result is limited to 0 (won't go negative).

        Args:
            to_remove: The amount to remove
        """
        if self.m_amount > to_remove:
            self.m_amount -= to_remove
        else:
            self.m_amount = 0

    def transfer_to(self, target: 'Resource') -> None:
        """
        Transfer resources to a given recipient. The quantity of
        resources transferred is limited by the capacity of the recipient.

        Args:
            target: The recipient resource
        """
        to_transfer = min(self.m_amount, target.m_capacity - target.m_amount)
        self.remove(to_transfer)
        target.add(to_transfer)

    def set_capacity(self, capacity: int) -> None:
        """
        Modify the capacity of the resource.
        If the new capacity is less than the current amount,
        the amount will be reduced to match the capacity.

        Args:
            capacity: The new capacity
        """
        self.m_capacity = capacity
        if self.m_amount > capacity:
            self.m_amount = capacity

    def type(self) -> str:
        """
        Return the type of resource (e.g., "food", "water", "electricity").

        Returns:
            The resource type string
        """
        return self.m_type

    def get_capacity(self) -> int:
        """
        Return how many resources can be held.

        Returns:
            The resource capacity
        """
        return self.m_capacity

    def get_amount(self) -> int:
        """
        Return the current quantity of resource.

        Returns:
            The current amount
        """
        return self.m_amount

    def has_amount(self) -> bool:
        """
        Check if the current quantity is not zero.

        Returns:
            True if the resource has a non-zero amount, False otherwise
        """
        return self.m_amount > 0

    def __str__(self) -> str:
        """
        Return a string representation of the resource.

        Returns:
            A formatted string showing the resource type, amount, and capacity
        """
        return f"Resource {self.m_type}: {self.m_amount}/{self.m_capacity}"

    def __repr__(self) -> str:
        """
        Return a representation of the resource for debugging.

        Returns:
            A string representation of the resource
        """
        return f"Resource('{self.m_type}', amount={self.m_amount}, capacity={self.m_capacity})"
