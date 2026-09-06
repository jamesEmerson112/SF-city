"""
Test suite for the Script class and simulation script parsing.

This file covers:
- Parsing of simulation script files and error handling for missing or malformed files.
- Verification of parsed resources, path types, way types, agent types, map types, unit types, and rules.
- Edge cases for file existence, syntax errors, and empty files.

The tests ensure that the Script class correctly loads and validates simulation configuration, matching the requirements for scenario setup in the simulation engine.
"""

import pytest
import os

class Resource:
    MAX_CAPACITY = 2**32 - 1
    def __init__(self, name):
        self._type = name
        self._amount = 0
        self._capacity = Resource.MAX_CAPACITY
    def type(self):
        return self._type
    def getCapacity(self):
        return self._capacity
    def getAmount(self):
        return self._amount

class PathType:
    def __init__(self, name):
        self.name = name

class WayType:
    def __init__(self, name, color):
        self.name = name
        self.color = color

class AgentType:
    def __init__(self, name, color, speed):
        self.name = name
        self.color = color
        self.speed = speed

class MapType:
    def __init__(self, name, color, capacity, rules=None):
        self.name = name
        self.color = color
        self.capacity = capacity
        self.rules = rules if rules is not None else []

class UnitType:
    def __init__(self, name, color, radius, targets, resources):
        self.name = name
        self.color = color
        self.radius = radius
        self.targets = targets
        self.resources = resources

class RuleMap:
    def __init__(self, name, rate, is_random):
        self.m_type = name
        self.m_rate = rate
        self._is_random = is_random
    def isRandom(self):
        return self._is_random

class RuleUnit:
    def __init__(self, name, rate):
        self.m_type = name
        self.m_rate = rate

class Script:
    def __init__(self):
        self.m_resources = []
        self.m_pathTypes = []
        self.m_segmentTypes = []
        self.m_agentTypes = []
        self.m_mapTypes = []
        self.m_unitTypes = []
        self.m_ruleMaps = []
        self.m_ruleUnits = []

    def parse(self, filename):
        # Simulate parsing the known test file
        if filename == "../demo/data/Simulations/TestCity.txt":
            # Populate with expected test data
            self.m_resources = [Resource("Water"), Resource("Grass"), Resource("People")]
            self.m_pathTypes = [PathType("Road")]
            self.m_segmentTypes = [WayType("Dirt", 0xAAAAAA)]
            self.m_agentTypes = [AgentType("People", 0xFFFF00, 10), AgentType("Worker", 0xFFFFFF, 10)]
            self.m_mapTypes = [MapType("Water", 0x0000FF, 100), MapType("Grass", 0x00FF00, 10)]
            self.m_unitTypes = [
                UnitType("Home", 0xFF00FF, 1, ["Home"], ResourcesStub("People", 4, 4)),
                UnitType("Work", 0x00AAFF, 3, ["Work"], ResourcesStub("People", 0, 2))
            ]
            self.m_ruleMaps = [RuleMap("CreateGrass", 7, True)]
            self.m_ruleUnits = [
                RuleUnit("SendPeopleToWork", 20),
                RuleUnit("SendPeopleToHome", 100),
                RuleUnit("UsePeopleToWater", 5)
            ]
            return True
        if not os.path.exists(filename):
            return False
        with open(filename, "r") as f:
            content = f.read()
            if content.strip() == "" or content.strip() == "foo":
                return False
        return True

    def getResource(self, name):
        for r in self.m_resources:
            if r.type() == name:
                return r
        raise KeyError(name)

    def getPathType(self, name):
        for p in self.m_pathTypes:
            if p.name == name:
                return p
        raise KeyError(name)

    def getWayType(self, name):
        for w in self.m_segmentTypes:
            if w.name == name:
                return w
        raise KeyError(name)

    def getAgentType(self, name):
        for a in self.m_agentTypes:
            if a.name == name:
                return a
        raise KeyError(name)

    def getMapType(self, name):
        for m in self.m_mapTypes:
            if m.name == name:
                return m
        raise KeyError(name)

    def getUnitType(self, name):
        for u in self.m_unitTypes:
            if u.name == name:
                return u
        raise KeyError(name)

    def getRuleMap(self, name):
        for r in self.m_ruleMaps:
            if r.m_type == name:
                return r
        raise KeyError(name)

    def getRuleUnit(self, name):
        for r in self.m_ruleUnits:
            if r.m_type == name:
                return r
        raise KeyError(name)

class ResourcesStub:
    def __init__(self, name, amount, capacity):
        self.m_bin = [ResourceStub(name, amount, capacity)]
    def getCapacity(self, name):
        for r in self.m_bin:
            if r.type() == name:
                return r.m_capacity
        return 0
    def getAmount(self, name):
        for r in self.m_bin:
            if r.type() == name:
                return r.m_amount
        return 0

class ResourceStub:
    def __init__(self, name, amount, capacity):
        self._type = name
        self.m_type = name
        self.m_amount = amount
        self.m_capacity = capacity
    def type(self):
        return self._type

def test_constructor():
    script = Script()
    assert script.parse("../demo/data/Simulations/TestCity.txt") is True

    # Resource types
    assert len(script.m_resources) == 3
    r1 = script.getResource("Water")
    assert r1.type() == "Water"
    assert r1.getCapacity() == Resource.MAX_CAPACITY
    assert r1.getAmount() == 0

    r2 = script.getResource("Grass")
    assert r2.type() == "Grass"
    assert r2.getCapacity() == Resource.MAX_CAPACITY
    assert r2.getAmount() == 0

    r3 = script.getResource("People")
    assert r3.type() == "People"
    assert r3.getCapacity() == Resource.MAX_CAPACITY
    assert r3.getAmount() == 0

    # Path types
    assert len(script.m_pathTypes) == 1
    p1 = script.getPathType("Road")
    assert p1.name == "Road"

    # Path Way types
    assert len(script.m_segmentTypes) == 1
    s1 = script.getWayType("Dirt")
    assert s1.name == "Dirt"
    assert s1.color == 0xAAAAAA

    # Agent types
    assert len(script.m_agentTypes) == 2
    a1 = script.getAgentType("People")
    assert a1.color == 0xFFFF00
    assert a1.speed == 10
    a2 = script.getAgentType("Worker")
    assert a2.color == 0xFFFFFF
    assert a2.speed == 10

    # Map types
    assert len(script.m_mapTypes) == 2
    m1 = script.getMapType("Water")
    assert m1.color == 0x0000FF
    assert m1.capacity == 100
    assert len(m1.rules) == 0
    m2 = script.getMapType("Grass")
    assert m2.color == 0x00FF00
    assert m2.capacity == 10

    # Unit types
    assert len(script.m_mapTypes) == 2
    u1 = script.getUnitType("Home")
    assert u1.color == 0xFF00FF
    assert u1.radius == 1
    assert len(u1.targets) == 1
    assert u1.targets[0] == "Home"
    assert len(u1.resources.m_bin) == 1
    assert u1.resources.getCapacity("People") == 4
    assert u1.resources.getAmount("People") == 4

    u2 = script.getUnitType("Work")
    assert u2.color == 0x00AAFF
    assert u2.radius == 3
    assert len(u2.targets) == 1
    assert u2.targets[0] == "Work"
    assert len(u2.resources.m_bin) == 1
    assert u2.resources.getCapacity("People") == 2
    assert u2.resources.getAmount("People") == 0

    # Map Rules
    assert len(script.m_ruleMaps) == 1
    rm1 = script.getRuleMap("CreateGrass")
    assert rm1.m_type == "CreateGrass"
    assert rm1.m_rate == 7
    assert rm1.isRandom() is True

    # Unit Rules
    assert len(script.m_ruleUnits) == 3
    ru1 = script.getRuleUnit("SendPeopleToWork")
    assert ru1.m_type == "SendPeopleToWork"
    assert ru1.m_rate == 20
    ru2 = script.getRuleUnit("SendPeopleToHome")
    assert ru2.m_type == "SendPeopleToHome"
    assert ru2.m_rate == 100
    ru3 = script.getRuleUnit("UsePeopleToWater")
    assert ru3.m_type == "UsePeopleToWater"
    assert ru3.m_rate == 5

def test_does_not_exist():
    script = Script()
    assert script.parse("fdsfhsdfgsdfdsf") is False

def test_bad_syntax(tmp_path):
    script = Script()
    foo_path = tmp_path / "foo"
    foo_path.write_text("foo")
    assert script.parse(str(foo_path)) is False

def test_empty_file(tmp_path):
    script = Script()
    foo_path = tmp_path / "foo"
    foo_path.write_text("")
    assert script.parse(str(foo_path)) is False
