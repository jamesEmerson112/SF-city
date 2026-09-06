"""
Script parser implementation for OpenGlassBox simulation engine.

This module implements the parsing functionality for simulation configuration scripts
that exactly matches the C++ ScriptParser behavior.
"""

import os
import errno
from typing import Dict, List, Optional, Any, TextIO
from dataclasses import dataclass, field

from .resource import Resource
from .resources import Resources
from .agent import AgentType
from .rule import RuleMap, RuleUnit, RuleMapType, RuleUnitType
from .rule_command import (
    IRuleCommand, RuleCommandAdd, RuleCommandRemove,
    RuleCommandTest, RuleCommandAgent, Comparison
)
from .rule_value import (
    IRuleValue, RuleValueLocal, RuleValueGlobal,
    RuleValueMap
)


@dataclass
class PathType:
    """Path type definition from script."""
    name: str
    color: int = 0


@dataclass
class WayType:
    """Way type definition from script."""
    name: str
    color: int = 0


@dataclass
class MapType:
    """Map type definition from script."""
    name: str
    color: int = 0
    capacity: int = 0
    rules: List[RuleMap] = field(default_factory=list)


@dataclass
class UnitType:
    """Unit type definition from script."""
    name: str
    color: int = 0
    radius: int = 0
    targets: List[str] = field(default_factory=list)
    rules: List[RuleUnit] = field(default_factory=list)
    resources: Optional[Resources] = None

    def __post_init__(self):
        if self.resources is None:
            self.resources = Resources()


class Script:
    """
    Parse a simulation script and store internally all types and simulation rules.
    Equivalent to C++ Script class.
    """

    def __init__(self):
        """Initialize an empty script parser."""
        self.m_resources: Dict[str, Resource] = {}
        self.m_pathTypes: Dict[str, PathType] = {}
        self.m_segmentTypes: Dict[str, WayType] = {}
        self.m_agentTypes: Dict[str, AgentType] = {}
        self.m_ruleMaps: Dict[str, RuleMap] = {}
        self.m_ruleUnits: Dict[str, RuleUnit] = {}
        self.m_unitTypes: Dict[str, UnitType] = {}
        self.m_mapTypes: Dict[str, MapType] = {}
        self.m_file: Optional[TextIO] = None
        self.m_token: str = ""
        self.m_success: bool = False

    def parse(self, filename: str) -> bool:
        """
        Parse the simulation file and fill its internal states.
        Equivalent to C++ Script::parse().

        Args:
            filename: Path to the simulation script file

        Returns:
            True if parsing succeeded, False otherwise
        """
        print(f"Parsing script '{filename}'")

        try:
            self.m_file = open(filename, 'r')
        except IOError as e:
            print(f"Failed opening '{filename}' Reason '{os.strerror(e.errno)}'")
            self.m_success = False
            return self.m_success

        try:
            self.parse_script()
            self.m_success = True
            print("  done")
        except Exception as e:
            print(f"Failed parsing script '{filename}' at token '{self.m_token}' Reason was '{str(e)}'")
            self.m_success = False
        finally:
            if self.m_file:
                self.m_file.close()
                self.m_file = None

        return self.m_success

    def next_token(self) -> str:
        """
        Split the script file into tokens. Return the reference of the last token.
        Equivalent to C++ Script::nextToken().

        Returns:
            The next token as a string
        """
        if self.m_file is None:
            self.m_token = ""
            return self.m_token

        # Read next whitespace-separated token
        self.m_token = ""
        while True:
            char = self.m_file.read(1)
            if not char:  # EOF
                break
            if char.isspace():
                if self.m_token:  # End of current token
                    break
                # Skip whitespace before token
                continue
            self.m_token += char

        # Uncomment for debugging
        # if self.m_token:
        #     print(f"I read '{self.m_token}'")

        return self.m_token

    def parse_script(self) -> None:
        """
        Entry point method for parsing the script.
        Equivalent to C++ Script::parseScript().
        """
        while True:
            empty = (len(self.m_token) == 0)
            token = self.next_token()

            if token == "resources":
                self.parse_resources()
            elif token == "rules":
                self.parse_rules()
            elif token == "maps":
                self.parse_maps()
            elif token == "paths":
                self.parse_paths()
            elif token == "segments":
                self.parse_ways()
            elif token == "agents":
                self.parse_agents()
            elif token == "units":
                self.parse_units()
            elif token == "":
                if not empty:
                    return
                # Empty file detection
                raise RuntimeError("parseScript()")
            else:
                raise RuntimeError("parseScript()")

    def parse_resources(self) -> None:
        """Parse the resources section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "resource":
                self.parse_resource()
            else:
                raise RuntimeError("parseResources()")

    def parse_resource(self) -> None:
        """Parse a single resource definition."""
        name = self.next_token()
        self.m_resources[name] = Resource(name)

    def parse_resources_array(self, resources: Resources) -> None:
        """Parse an array of resource definitions."""
        token = self.next_token()
        if token != "[":
            raise RuntimeError("parseResourcesArray()")

        while True:
            token = self.next_token()
            if token == "]":
                return

            resource = self.get_resource(token)
            amount = self._toUint(self.next_token())
            # FIXME should be setAmount
            resources.add_resource(resource.type(), amount)

    def parse_capacities_array(self, resources: Resources) -> None:
        """Parse an array of capacity definitions."""
        token = self.next_token()
        if token != "[":
            raise RuntimeError("parseCapacitiesArray()")

        while True:
            token = self.next_token()
            if token == "]":
                return

            resource = self.get_resource(token)
            capacity = self._toUint(self.next_token())
            resources.set_capacity(resource.type(), capacity)

    def parse_paths(self) -> None:
        """Parse the paths section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "path":
                self.parse_path()
            else:
                raise RuntimeError("parsePaths()")

    def parse_path(self) -> None:
        """Parse a single path definition."""
        name = self.next_token()
        path = PathType(name)
        self.m_pathTypes[path.name] = path

        while True:
            token = self.next_token()
            if token == "color":
                path.color = self._toColor(self.next_token())
                return
            else:
                raise RuntimeError("parsePath()")

    def parse_ways(self) -> None:
        """Parse the ways/segments section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "segment":
                self.parse_way()
            else:
                raise RuntimeError("parseWays()")

    def parse_way(self) -> None:
        """Parse a single way/segment definition."""
        name = self.next_token()
        seg = WayType(name)
        self.m_segmentTypes[seg.name] = seg

        while True:
            token = self.next_token()
            if token == "color":
                seg.color = self._toColor(self.next_token())
                return
            else:
                raise RuntimeError("parseWay()")

    def parse_agents(self) -> None:
        """Parse the agents section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "agent":
                self.parse_agent()
            else:
                raise RuntimeError("parseAgents()")

    def parse_agent(self) -> None:
        """Parse a single agent definition."""
        name = self.next_token()
        agent = AgentType(name=name, speed=0.0, radius=0, color=0)
        self.m_agentTypes[agent.name] = agent

        while True:
            token = self.next_token()
            if token == "color":
                agent.color = self._toColor(self.next_token())
            elif token == "speed":
                agent.speed = self._toFloat(self.next_token())
                return
            else:
                raise RuntimeError("parseAgents()")

    def parse_rules(self) -> None:
        """Parse the rules section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "mapRule":
                self.parse_rule_map()
            elif token == "unitRule":
                self.parse_rule_unit()
            else:
                raise RuntimeError("parseRules()")

    def parse_rule_map(self) -> None:
        """Parse a map rule definition."""
        name = self.next_token()
        rule_type = RuleMapType(name)

        while True:
            token = self.next_token()
            if token == "end":
                rule = RuleMap(rule_type)
                self.m_ruleMaps[rule.type()] = rule
                return
            elif token == "rate":
                rule_type.rate = self._toUint(self.next_token())
            elif token == "randomTiles":
                rule_type.randomTiles = self._toBool(self.next_token())
            elif token == "randomTilesPercent":
                rule_type.randomTiles = True
                rule_type.randomTilesPercent = self._toUint(self.next_token())
            else:
                rule_type.commands.append(self.parse_command(token))

    def parse_rule_unit(self) -> None:
        """Parse a unit rule definition."""
        name = self.next_token()
        rule_type = RuleUnitType(name)

        while True:
            token = self.next_token()
            if token == "end":
                rule = RuleUnit(rule_type)
                self.m_ruleUnits[rule.type()] = rule
                return
            elif token == "rate":
                rule_type.rate = self._toUint(self.next_token())
            # TODO: Handle onFail
            # elif token == "onFail":
            #     rule_type.onFail = ...
            else:
                rule_type.commands.append(self.parse_command(token))

    def parse_command(self, token: str) -> IRuleCommand:
        """Parse a command definition."""
        target = None
        command = None

        if token == "local":
            resource = self.get_resource(self.next_token())
            target = RuleValueLocal(resource)
        elif token == "global":
            resource = self.get_resource(self.next_token())
            target = RuleValueGlobal(resource)
        elif token == "map":
            target = RuleValueMap(self.next_token())
        elif token == "agent":
            name = self.next_token()
            search_target = ""
            resources = Resources()

            while True:
                cmd = self.next_token()
                if cmd == "to":
                    search_target = self.next_token()
                elif cmd == "add":
                    self.parse_resources_array(resources)
                    break
                else:
                    raise RuntimeError("parseCommand()")

            command = RuleCommandAgent(self.get_agent_type(name), search_target, resources)
        else:
            raise RuntimeError("parseCommand()")

        if target is not None:
            cmd = self.next_token()
            if cmd == "add":
                command = RuleCommandAdd(target, self._toUint(self.next_token()))
            elif cmd == "remove":
                command = RuleCommandRemove(target, self._toUint(self.next_token()))
            elif cmd == "greater":
                command = RuleCommandTest(target, Comparison.GREATER, self._toUint(self.next_token()))
            elif cmd == "less":
                command = RuleCommandTest(target, Comparison.LESS, self._toUint(self.next_token()))
            elif cmd == "equals":
                command = RuleCommandTest(target, Comparison.EQUALS, self._toUint(self.next_token()))
            else:
                raise RuntimeError("parseCommand()")

        return command

    def parse_maps(self) -> None:
        """Parse the maps section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "map":
                self.parse_map()
            else:
                raise RuntimeError("parseMaps()")

    def parse_map(self) -> None:
        """Parse a map definition."""
        name = self.next_token()
        map_type = MapType(name)
        self.m_mapTypes[map_type.name] = map_type

        while True:
            token = self.next_token()
            if token == "color":
                map_type.color = self._toColor(self.next_token())
            elif token == "capacity":
                map_type.capacity = self._toUint(self.next_token())
            elif token == "rules":
                self.parse_rule_map_array(map_type.rules)
                return

    def parse_units(self) -> None:
        """Parse the units section."""
        while True:
            token = self.next_token()
            if token == "end":
                return
            elif token == "unit":
                self.parse_unit()
            else:
                raise RuntimeError("parseUnits()")

    def parse_unit(self) -> None:
        """Parse a unit definition."""
        name = self.next_token()
        unit = UnitType(name)
        self.m_unitTypes[unit.name] = unit

        caps = Resources()
        resources = Resources()

        while True:
            token = self.next_token()
            if token == "color":
                unit.color = self._toColor(self.next_token())
            elif token == "mapRadius":
                unit.radius = self._toUint(self.next_token())
            elif token == "rules":
                self.parse_rule_unit_array(unit.rules)
            elif token == "targets":
                self.parse_string_array(unit.targets)
            elif token == "caps":
                self.parse_capacities_array(caps)
                unit.resources.set_capacities(caps)
            elif token == "resources":
                self.parse_resources_array(resources)
                unit.resources.add_resources(resources)
                return
            else:
                raise RuntimeError("parseUnit()")

    def parse_string_array(self, vec: List[str]) -> None:
        """Parse an array of strings."""
        token = self.next_token()
        if token != "[":
            raise RuntimeError("parseStringArray()")

        while True:
            token = self.next_token()
            if token == "]":
                return
            vec.append(token)

    def parse_rule_map_array(self, rules: List[RuleMap]) -> None:
        """Parse an array of map rule references."""
        token = self.next_token()
        if token != "[":
            raise RuntimeError("parseRuleMapArray()")

        while True:
            token = self.next_token()
            if token == "]":
                return
            rules.append(self.m_ruleMaps[token])

    def parse_rule_unit_array(self, rules: List[RuleUnit]) -> None:
        """Parse an array of unit rule references."""
        token = self.next_token()
        if token != "[":
            raise RuntimeError("parseRuleUnitArray()")

        while True:
            token = self.next_token()
            if token == "]":
                return
            rules.append(self.m_ruleUnits[token])

    # Accessor methods with template-like behavior

    def get_resource(self, id: str) -> Resource:
        """Get a resource by identifier. Equivalent to C++ getT<Resource>()."""
        try:
            return self.m_resources[id]
        except KeyError:
            raise KeyError(f"Resource '{id}' not found")

    def get_path_type(self, id: str) -> PathType:
        """Get a path type by identifier."""
        try:
            return self.m_pathTypes[id]
        except KeyError:
            raise KeyError(f"PathType '{id}' not found")

    def get_way_type(self, id: str) -> WayType:
        """Get a way type by identifier."""
        try:
            return self.m_segmentTypes[id]
        except KeyError:
            raise KeyError(f"WayType '{id}' not found")

    def get_agent_type(self, id: str) -> AgentType:
        """Get an agent type by identifier."""
        try:
            return self.m_agentTypes[id]
        except KeyError:
            raise KeyError(f"AgentType '{id}' not found")

    def get_rule_map(self, id: str) -> RuleMap:
        """Get a map rule by identifier."""
        try:
            return self.m_ruleMaps[id]
        except KeyError:
            raise KeyError(f"RuleMap '{id}' not found")

    def get_rule_unit(self, id: str) -> RuleUnit:
        """Get a unit rule by identifier."""
        try:
            return self.m_ruleUnits[id]
        except KeyError:
            raise KeyError(f"RuleUnit '{id}' not found")

    def get_unit_type(self, id: str) -> UnitType:
        """Get a unit type by identifier."""
        try:
            return self.m_unitTypes[id]
        except KeyError:
            raise KeyError(f"UnitType '{id}' not found")

    def get_map_type(self, id: str) -> MapType:
        """Get a map type by identifier."""
        try:
            return self.m_mapTypes[id]
        except KeyError:
            raise KeyError(f"MapType '{id}' not found")

    # Utility methods for type conversion (equivalent to C++ static functions)

    @staticmethod
    def _toUint(word: str) -> int:
        """Convert string to unsigned integer. Equivalent to C++ toUint()."""
        return int(word)

    @staticmethod
    def _toColor(word: str) -> int:
        """Convert hex string to color integer. Equivalent to C++ toColor()."""
        return int(word, 16)

    @staticmethod
    def _toFloat(word: str) -> float:
        """Convert string to float. Equivalent to C++ toFloat()."""
        return float(word)

    @staticmethod
    def _toBool(word: str) -> bool:
        """Convert string to boolean. Equivalent to C++ toBool()."""
        if word == "true":
            return True
        if word == "false":
            return False
        return bool(Script._toUint(word))
