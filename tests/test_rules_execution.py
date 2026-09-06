#!/usr/bin/env python3
"""
Test script to verify that units with parsed types execute rules properly.
This reproduces the issue where Python side doesn't show the same rule execution as C++.
"""

import time
from openglassbox.simulation import Simulation
from openglassbox.vector import Vector3f

def test_rules_execution():
    """Test that units execute rules from parsed script."""
    print("Testing rule execution with parsed types...")

    # Create simulation and parse script
    sim = Simulation(12, 12)
    result = sim.parse('demo/data/Simulations/TestCity.txt')
    print(f'Parse result: {result}')

    if not result:
        print("Failed to parse script!")
        return False

    # Get parsed types (like C++ demo does)
    home_type = sim.get_unit_type("Home")
    work_type = sim.get_unit_type("Work")
    road_type = sim.get_path_type("Road")
    dirt_type = sim.get_way_type("Dirt")
    grass_type = sim.get_map_type("Grass")
    water_type = sim.get_map_type("Water")

    print(f'Home type has {len(home_type.rules)} rules: {[r.type() for r in home_type.rules]}')
    print(f'Work type has {len(work_type.rules)} rules: {[r.type() for r in work_type.rules]}')
    print(f'Home type resources: {home_type.resources}')
    print(f'Work type resources: {work_type.resources}')

    # Create a city
    city = sim.add_city('TestCity', Vector3f(0, 0, 0))

    # Add a path and units using parsed types
    path = city.add_path(road_type)
    n1 = path.add_node(Vector3f(10, 10, 0))
    n2 = path.add_node(Vector3f(20, 20, 0))
    way = path.add_way(dirt_type, n1, n2)

    # Add units with parsed types (should have rules)
    home_unit = city.add_unit_on_way(home_type, path, way, 0.3)
    work_unit = city.add_unit_on_way(work_type, path, way, 0.7)

    # Add maps
    grass_map = city.add_map(grass_type)
    water_map = city.add_map(water_type)

    print(f'\nAfter creation:')
    print(f'Home unit has {len(home_unit.m_type.rules)} rules')
    print(f'Work unit has {len(work_unit.m_type.rules)} rules')
    print(f'Home unit resources: {home_unit.m_resources}')
    print(f'Work unit resources: {work_unit.m_resources}')
    print(f'Agents in city: {len(city.agents())}')

    # Run simulation for several ticks to see rule execution
    print('\nRunning simulation...')
    for i in range(100):
        sim.update(0.01)  # 10ms per tick

        if i % 20 == 0:
            print(f'Tick {i}:')
            print(f'  Home unit resources: {home_unit.m_resources}')
            print(f'  Work unit resources: {work_unit.m_resources}')
            print(f'  Agents in city: {len(city.agents())}')
            print(f'  Water map total: {sum(water_map.get_resource(u, v) for u in range(water_map.grid_size_u()) for v in range(water_map.grid_size_v()))}')
            print(f'  Grass map total: {sum(grass_map.get_resource(u, v) for u in range(grass_map.grid_size_u()) for v in range(grass_map.grid_size_v()))}')

    print('\nTest completed!')
    return True

if __name__ == "__main__":
    test_rules_execution()
