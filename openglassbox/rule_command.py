"""
//-----------------------------------------------------------------------------
// Copyright (c) 2025 An Thien Vo.
// Based on https://github.com/Lecrapouille/OpenGlassBox
// Based on https://github.com/federicodangelo/MultiAgentSimulation
// Distributed under MIT License.
//-----------------------------------------------------------------------------
"""

"""
RuleCommand module for OpenGlassBox simulation engine.

This module implements concrete rule command classes that inherit from IRuleCommand.
These commands represent specific actions that rules can take, such as adding/removing
resources, testing conditions, and spawning agents.
"""

from typing import Dict, List, Optional, Any, Union
from enum import Enum, auto
from .rule import IRuleCommand, IRuleValue, RuleContext


class Comparison(Enum):
    """
    Comparison types for rule test commands.
    Equivalent to C++ RuleCommandTest::Comparison enum.
    """
    EQUALS = auto()
    GREATER = auto()
    LESS = auto()


class RuleCommandAdd(IRuleCommand):
    """
    Command to add resources to a target.
    Equivalent to C++ RuleCommandAdd class.

    Example: "map Grass add 1"
    """

    def __init__(self, target: IRuleValue, amount: int):
        """
        Initialize an add command.

        Args:
            target: The target value to add resources to
            amount: The amount to add
        """
        self.m_target = target
        self.m_amount = amount

    def validate(self, context: RuleContext) -> bool:
        """
        Can be applied if the amount of resource has not reached the capacity.

        Args:
            context: The rule execution context

        Returns:
            True if the command can be executed, False otherwise
        """
        return self.m_target.get(context) < self.m_target.capacity(context)

    def execute(self, context: RuleContext) -> None:
        """
        Increase the amount of resource of the target.

        Args:
            context: The rule execution context
        """
        self.m_target.add(context, self.m_amount)

    def type(self) -> str:
        """
        Get the command type string for debugging.

        Returns:
            Formatted string describing the command
        """
        return f"Add {self.m_amount} Resources {self.m_target.type()}"


class RuleCommandRemove(IRuleCommand):
    """
    Command to remove resources from a target.
    Equivalent to C++ RuleCommandRemove class.

    Example: "local People remove 1"
    """

    def __init__(self, target: IRuleValue, amount: int):
        """
        Initialize a remove command.

        Args:
            target: The target value to remove resources from
            amount: The amount to remove
        """
        self.m_target = target
        self.m_amount = amount

    def validate(self, context: RuleContext) -> bool:
        """
        Can be applied if the amount of resource is enough.

        Args:
            context: The rule execution context

        Returns:
            True if the command can be executed, False otherwise
        """
        return self.m_target.get(context) >= self.m_amount

    def execute(self, context: RuleContext) -> None:
        """
        Decrease the amount of resource of the target.

        Args:
            context: The rule execution context
        """
        self.m_target.remove(context, self.m_amount)

    def type(self) -> str:
        """
        Get the command type string for debugging.

        Returns:
            Formatted string describing the command
        """
        return f"Remove {self.m_amount} Resources {self.m_target.type()}"


class RuleCommandTest(IRuleCommand):
    """
    Command to test a condition on a target.
    Equivalent to C++ RuleCommandTest class.

    Example: "map Water greater 300"
    """

    def __init__(self, target: IRuleValue, comparison: Comparison, amount: int):
        """
        Initialize a test command.

        Args:
            target: The target value to test
            comparison: The comparison operation to perform
            amount: The amount to compare against
        """
        self.m_target = target
        self.m_amount = amount
        self.m_comparison = comparison

    def validate(self, context: RuleContext) -> bool:
        """
        Can be applied if the comparison condition is met.

        Args:
            context: The rule execution context

        Returns:
            True if the test condition passes, False otherwise
        """
        target_value = self.m_target.get(context)

        if self.m_comparison == Comparison.EQUALS:
            return target_value == self.m_amount
        elif self.m_comparison == Comparison.GREATER:
            return target_value > self.m_amount
        elif self.m_comparison == Comparison.LESS:
            return target_value < self.m_amount
        else:
            # Should not happen, but handle gracefully
            assert False, f"Unhandled comparison type in RuleCommandTest::validate: {self.m_comparison}"
            return False

    def execute(self, context: RuleContext) -> None:
        """
        Execute the test command (no-op).
        Test commands only validate conditions; they don't modify state.

        Args:
            context: The rule execution context
        """
        # Do nothing - test commands only validate, they don't execute actions
        pass

    def type(self) -> str:
        """
        Get the command type string for debugging.

        Returns:
            Formatted string describing the command
        """
        comparison_str = ""
        if self.m_comparison == Comparison.EQUALS:
            comparison_str = "Test Equal"
        elif self.m_comparison == Comparison.GREATER:
            comparison_str = "Test Greater"
        elif self.m_comparison == Comparison.LESS:
            comparison_str = "Test Less"

        return f"{comparison_str} {self.m_amount} Resources {self.m_target.type()}"


class RuleCommandAgent(IRuleCommand):
    """
    Command to spawn an agent in the simulation.
    Equivalent to C++ RuleCommandAgent class.
    Inherits from both IRuleCommand and AgentType functionality.

    Example: "agent People color 0xFFFF00 speed 10"
    """

    def __init__(self, agent_type: Any, target: str, resources: Any):
        """
        Initialize an agent command.

        Args:
            agent_type: The AgentType definition (color, speed, etc.)
            target: The target the agent should search for
            resources: Resources to give to the agent
        """
        # Store AgentType properties (equivalent to inheriting from AgentType)
        self.agent_type = agent_type
        self.m_target = target
        self.m_resources = resources

    def validate(self, context: RuleContext) -> bool:
        """
        Always returns true - agent commands can always be executed.

        Args:
            context: The rule execution context

        Returns:
            Always True
        """
        return True

    def execute(self, context: RuleContext) -> None:
        """
        Add a new agent in the city.

        Args:
            context: The rule execution context
        """
        if context.unit is not None and hasattr(context.unit, 'has_ways') and context.unit.has_ways():
            # Add agent to the city
            if context.city is not None and hasattr(context.city, 'add_agent'):
                context.city.add_agent(self.agent_type, context.unit, self.m_resources, self.m_target)
        else:
            # Debug message equivalent to C++ version
            import sys
            if hasattr(sys, 'gettrace') and sys.gettrace() is not None:
                # Only print debug message in debug mode
                unit_id = getattr(context.unit, 'id', lambda: 'unknown')()
                print(f"Ill-formed: Unit {unit_id} is attached to an orphan Path Node "
                      f"and its Agent will not be able to move towards the City.",
                      file=sys.stderr)

    def type(self) -> str:
        """
        Get the command type string for debugging.

        Returns:
            The command type string
        """
        return "Add Agent"

    # AgentType properties (equivalent to C++ multiple inheritance)
    def name(self) -> str:
        """Get the agent type name."""
        return getattr(self.agent_type, 'name', 'Unknown')

    def color(self) -> int:
        """Get the agent color."""
        return getattr(self.agent_type, 'color', 0xFFFFFF)

    def speed(self) -> float:
        """Get the agent speed."""
        return getattr(self.agent_type, 'speed', 1.0)


# Backwards compatibility aliases
RuleCommand = IRuleCommand
