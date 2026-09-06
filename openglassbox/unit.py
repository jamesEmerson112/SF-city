"""
Unit class for OpenGlassBox simulation engine.

This module defines the Unit class which represents stationary entities in the simulation
such as buildings, factories, and other fixed structures. Units are placed at Nodes in
the Path network, store resources, and execute rules that can create Agents.
"""

from typing import List, Dict, Optional, Any, TYPE_CHECKING

from .vector import Vector3f
from .resources import Resources
from .rule import RuleContext
from .script_parser import UnitType

if TYPE_CHECKING:
    from .node import Node
    from .city import City


class Unit:
    """
    A Unit represents things: houses, factories, even people.
    Equivalent to C++ Unit class.

    A unit has state: a collection of resource but also a well-defined spatial extent:
    bounding volume, simulation footprint. Currently implemented, an Unit shall
    refer to an existing Path Node to allow Agent to carry Resources from an
    Unit to another Unit.
    """

    def __init__(self, unit_type: UnitType, node: 'Node', city: 'City'):
        """
        Create a new Unit instance placed on an existing Path's Node.
        Equivalent to C++ Unit(UnitType const& type, Node& node, City& city).

        Args:
            unit_type: const reference of a given type of Unit also referred internally
            node: The reference to the Path Node owning this instance
            city: The reference to the City owning this instance
        """
        # Reference to the type of Unit defined in the simulation script
        self.m_type = unit_type

        # Reference to Node of a Path
        self.m_node = node

        # Unit produce resources as defined by simulation scripts
        # C++: m_resources(type.resources) - copy constructor
        self.m_resources = Resources()
        self.m_resources.add_resources(unit_type.resources)

        # Discrete time for running UnitRules at the rate time defined by simulation scripts
        self.m_ticks = 0

        # Register the unit with the node
        self.m_node.add_unit(self)

        # Structure holding useful information for the good execution of UnitRules
        self.m_context = RuleContext()

        # References states needed for running Rules
        self.m_context.unit = self
        self.m_context.city = city
        self.m_context.globals = city.globals()
        self.m_context.locals = self.m_resources
        self.m_context.radius = unit_type.radius

        # Convert world position to map coordinates
        u_out = []
        v_out = []
        city.world2mapPosition(self.m_node.position(), u_out, v_out)
        self.m_context.u = u_out[0] if u_out else 0
        self.m_context.v = v_out[0] if v_out else 0

    def execute_rules(self) -> None:
        """
        Execute simulation rules given by UnitType (defined by the simulation script).
        Equivalent to C++ void executeRules().
        """
        self.m_ticks += 1  # Increment the tick counter for this unit

        # Execute rules in reverse order (C++ pattern: size_t i = m_type.rules.size(); while (i--))
        i = len(self.m_type.rules)
        while i > 0:
            i -= 1
            # Only execute rules at their specified rate (every N ticks)
            if self.m_ticks % self.m_type.rules[i].rate() == 0:
                # Execute the rule with the current context (unit, city, resources, etc.)
                self.m_type.rules[i].execute(self.m_context)

    def accepts(self, searchTarget: str, resourcesToTryToAdd: Resources) -> bool:
        """
        Check if the current resources of this instance can add external resources
        from a matching target.
        Equivalent to C++ bool accepts(std::string const& searchTarget, Resources const& resourcesToTryToAdd).

        Args:
            searchTarget: The target type to check against this unit's targets
            resourcesToTryToAdd: The resources to check for acceptance

        Returns:
            True if the unit accepts the resources for this target, False otherwise
        """
        # C++: return (m_resources.can_add_some_resources(resourcesToTryToAdd)) &&
        #             ((find(m_type.targets.begin(), m_type.targets.end(), searchTarget)
        #               != m_type.targets.end()));

        can_add_resources = self.m_resources.can_add_some_resources(resourcesToTryToAdd)
        target_found = searchTarget in self.m_type.targets  # Python equivalent of std::find

        return can_add_resources and target_found

    def type(self) -> str:
        """
        Getter: return the type of Unit.
        Equivalent to C++ std::string const& type() const.
        """
        return self.m_type.name

    def resources(self) -> Resources:
        """
        Return current resources.
        Equivalent to C++ Resources& resources().
        """
        return self.m_resources

    def position(self) -> Vector3f:
        """
        Return the position inside the World coordinate of the Path Node that is referring.
        Equivalent to C++ Vector3f const& position() const.
        """
        return self.m_node.position()

    def color(self) -> int:
        """
        Return the color for the Renderer.
        Equivalent to C++ uint32_t color() const.
        """
        return self.m_type.color

    def node(self) -> 'Node':
        """
        Return the associated Path Node.
        Equivalent to C++ Node& node().
        """
        return self.m_node

    def id(self) -> int:
        """
        Return the unique identifier.
        Equivalent to C++ uint32_t id() const.
        """
        return self.m_node.id()

    def has_ways(self) -> bool:
        """
        Check if can access to at least one Way. A Unit shall refer to
        a Node with neighbors else Agents cannot move towards Path.
        Equivalent to C++ bool hasWays() const.
        """
        return self.m_node.has_ways()


# Type alias for collections (equivalent to C++ using Units = std::vector<std::unique_ptr<Unit>>)
Units = List[Unit]
