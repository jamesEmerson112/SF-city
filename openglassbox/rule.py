"""
Rule module for OpenGlassBox simulation engine.

This module implements the Rule system which defines how simulation entities
interact with each other and how resources flow through the simulation.
It provides the base classes for commands, values, and rules.
"""

from typing import Dict, List, Optional, Any, TypeVar, Generic, Union
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class RuleContext:
    """
    Structure holding all information needed to execute simulation rules.
    Equivalent to C++ RuleContext struct.
    """
    city: Optional[Any] = None          # Non null pointer on the City
    unit: Optional[Any] = None          # Non null pointer on the Unit
    locals: Optional[Any] = None        # Local resources (of Map or Unit)
    globals: Optional[Any] = None       # Global resources
    u: int = 0                          # Position on the grid of the Map
    v: int = 0                          # Position on the grid of the Map
    radius: int = 0                     # Radius action on Map resources


class IRuleCommand(ABC):
    """
    Base class interfacing command defined from simulation scripts.
    Equivalent to C++ IRuleCommand interface.
    """

    @abstractmethod
    def validate(self, context: RuleContext) -> bool:
        """
        Return true if this command can be applied in the current context.

        Args:
            context: The rule execution context

        Returns:
            True if the command can be executed, False otherwise
        """
        pass

    @abstractmethod
    def execute(self, context: RuleContext) -> None:
        """
        Apply the command on the current context.

        Args:
            context: The rule execution context
        """
        pass

    @abstractmethod
    def type(self) -> str:
        """
        Get the type of this command.

        Returns:
            The command type string
        """
        pass


class IRuleValue(ABC):
    """
    Base class for rule values.
    Equivalent to C++ IRuleValue interface.
    """

    @abstractmethod
    def get(self, context: RuleContext) -> int:
        """
        Get the current value in the given context.

        Args:
            context: The rule execution context

        Returns:
            The current value
        """
        pass

    @abstractmethod
    def capacity(self, context: RuleContext) -> int:
        """
        Get the maximum capacity in the given context.

        Args:
            context: The rule execution context

        Returns:
            The maximum capacity
        """
        pass

    @abstractmethod
    def add(self, context: RuleContext, to_add: int) -> None:
        """
        Add value in the given context.

        Args:
            context: The rule execution context
            to_add: The amount to add
        """
        pass

    @abstractmethod
    def remove(self, context: RuleContext, to_remove: int) -> None:
        """
        Remove value in the given context.

        Args:
            context: The rule execution context
            to_remove: The amount to remove
        """
        pass

    @abstractmethod
    def type(self) -> str:
        """
        Get the type of this value.

        Returns:
            The value type string
        """
        pass


class IRule:
    """
    Base rule class.
    Equivalent to C++ IRule base class.
    """

    def __init__(self, name: str, rate: int, commands: List[IRuleCommand]):
        """
        Initialize a rule with name, rate, and commands.

        Args:
            name: The rule name/type
            rate: The execution rate (in ticks)
            commands: List of commands to execute
        """
        self.m_type = name
        self.m_rate = rate
        self.m_commands = commands

    def execute(self, context: RuleContext) -> bool:
        """
        Execute the rule using two-phase execution pattern.
        First validate all commands, then execute all commands.

        Args:
            context: The rule execution context

        Returns:
            True if execution succeeded, False otherwise
        """
        # Phase 1: Validate ALL commands first
        for command in reversed(self.m_commands):
            if not command.validate(context):
                return False

        # Phase 2: Execute ALL commands (only if all validations passed)
        for command in reversed(self.m_commands):
            command.execute(context)

        return True

    def type(self) -> str:
        """
        Get the rule type.

        Returns:
            The rule type string
        """
        return self.m_type

    def rate(self) -> int:
        """
        Get the rule execution rate.

        Returns:
            The rule execution rate
        """
        return self.m_rate

    def commands(self) -> List[IRuleCommand]:
        """
        Get the list of commands.

        Returns:
            The list of commands
        """
        return self.m_commands


@dataclass
class RuleMapType:
    """Type definition for map rules."""
    name: str
    rate: int = 1
    randomTiles: bool = False
    randomTilesPercent: int = 0
    commands: List[IRuleCommand] = field(default_factory=list)


@dataclass
class RuleUnitType:
    """Type definition for unit rules."""
    name: str
    rate: int = 1
    commands: List[IRuleCommand] = field(default_factory=list)
    onFail: Optional['RuleUnit'] = None


class RuleMap(IRule):
    """
    Rule specific to maps with random tile support.
    Equivalent to C++ RuleMap class.
    """

    def __init__(self, rule_type: RuleMapType):
        """
        Initialize a map rule with the specified type.

        Args:
            rule_type: The type definition for the map rule
        """
        super().__init__(rule_type.name, rule_type.rate, rule_type.commands)
        self.m_randomTiles = rule_type.randomTiles
        self.m_randomTilesPercent = min(100, rule_type.randomTilesPercent)

    def is_random(self) -> bool:
        """
        Check if this rule uses randomized tiles.

        Returns:
            True if using random tiles, False otherwise
        """
        return self.m_randomTiles

    def percent(self, value: Union[int, float]) -> Union[int, float]:
        """
        Compute the percent of the given value.
        Template-like method equivalent to C++ template method.

        Args:
            value: The value to calculate percentage of

        Returns:
            The percentage of the value
        """
        if isinstance(value, int):
            return value * self.m_randomTilesPercent // 100
        else:
            return value * float(self.m_randomTilesPercent) / 100.0


class RuleUnit(IRule):
    """
    Rule specific to units with failure handling support.
    Equivalent to C++ RuleUnit class.
    """

    def __init__(self, rule_type: RuleUnitType):
        """
        Initialize a unit rule with the specified type.

        Args:
            rule_type: The type definition for the unit rule
        """
        super().__init__(rule_type.name, rule_type.rate, rule_type.commands)
        self.m_onFail = rule_type.onFail

    def execute(self, context: RuleContext) -> bool:
        """
        Execute the rule with failure handling.
        If primary execution fails, try the onFail rule.

        Args:
            context: The rule execution context

        Returns:
            True if execution succeeded, False otherwise
        """
        # Try primary rule execution
        if super().execute(context):
            return True
        else:
            # If primary rule failed, try onFail rule
            if self.m_onFail is not None:
                return self.m_onFail.execute(context)
            else:
                return False


# Backwards compatibility aliases
Rule = IRule
RuleCommand = IRuleCommand
RuleValue = IRuleValue
