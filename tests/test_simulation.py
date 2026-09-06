"""
Test suite for the Simulation class and city management logic.

This file covers:
- Construction and initialization of Simulation objects.
- Adding and retrieving City objects within the simulation.
- Verification of member variables, time, and city lookup logic.
- Testing the update mechanism and rule execution flow.

The tests ensure that Simulation objects and their city management behave as expected,
matching the requirements for simulation setup, city registration, and update logic.
"""

import pytest

from openglassbox.simulation import Simulation, TICKS_PER_SECOND
from openglassbox.vector import Vector3f
from openglassbox.city import City

def test_constants():
    """Test that simulation constants are properly defined."""
    assert TICKS_PER_SECOND > 0

def test_constructor():
    """Test simulation construction and city management."""
    sim = Simulation(4, 5)
    assert sim.m_gridSizeU == 4
    assert sim.m_gridSizeV == 5
    assert sim.m_time == 0.0
    assert len(sim.m_cities) == 0

    c1 = sim.add_city("Paris", Vector3f(0.0, 0.0, 0.0))
    assert c1.name() == "Paris"

    c2 = sim.get_city("Paris")
    assert c1 is c2
    assert c2.name() == "Paris"

    assert len(sim.m_cities) == 1
    assert sim.m_cities["Paris"] is c1
    assert sim.m_cities["Paris"].name() == "Paris"

def test_listener():
    """Test the simulation listener mechanism."""
    class TestListener(Simulation.Listener):
        def __init__(self):
            self.added_cities = []
            self.removed_cities = []

        def onCityAdded(self, city):
            self.added_cities.append(city)

        def onCityRemoved(self, city):
            self.removed_cities.append(city)

    listener = TestListener()
    sim = Simulation(10, 10)
    sim.set_listener(listener)

    # Test city addition notification
    city = sim.add_city("London", Vector3f(10.0, 10.0, 0.0))
    assert len(listener.added_cities) == 1
    assert listener.added_cities[0] is city
    assert listener.added_cities[0].name() == "London"

def test_update():
    """Test the simulation update mechanism."""
    # Set up a mock city for testing update calls
    class MockCity:
        def __init__(self, name, position):
            self._name = name
            self._position = position
            self.update_count = 0

        def name(self):
            return self._name

        def update(self):
            self.update_count += 1

    sim = Simulation(10, 10)

    # Replace add_city to use our mock
    def add_mock_city(name, position):
        mock_city = MockCity(name, position)
        sim.m_cities[name] = mock_city
        return mock_city

    sim.add_city = add_mock_city

    # Add a mock city and verify updating works
    city = sim.add_city("TestCity", Vector3f(0.0, 0.0, 0.0))
    assert city.update_count == 0

    # Test update with various time steps
    sim.update(0.001)  # Small delta, shouldn't trigger an update
    assert city.update_count == 0

    # Large enough delta to trigger multiple updates
    update_threshold = 1.0 / TICKS_PER_SECOND
    sim.update(update_threshold * 3)
    assert city.update_count == 3
