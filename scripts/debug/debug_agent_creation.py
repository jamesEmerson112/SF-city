#!/usr/bin/env python3
"""
Debug script to test agent creation in detail.
"""

import sys
import os

# Add project root to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from openglassbox.simulation import Simulation
from openglassbox.vector import Vector3f

def debug_agent_creation():
    """Debug agent creation in detail."""
    print("=== Debugging Agent Creation ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create test city
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    grass_type = simulation.get_map_type("Grass")
    water_type = simulation.get_map_type("Water")
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    
    # Add maps
    paris_grass = paris.add_map(grass_type)
    paris_water = paris.add_map(water_type)
    
    # Add paths and ways
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(60.0, 60.0, 0.0) + paris.position())
    n2 = road.add_node(Vector3f(300.0, 300.0, 0.0) + paris.position())
    w1 = road.add_way(dirt_type, n1, n2)
    
    # Add a home unit
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.5)
    
    print(f"1. Checking unit and city setup:")
    print(f"   - Home unit has ways: {home_unit.has_ways()}")
    print(f"   - Home unit node: {home_unit.node()}")
    print(f"   - City has addAgent method: {hasattr(paris, 'addAgent')}")
    print(f"   - City has add_agent method: {hasattr(paris, 'add_agent')}")
    
    # List all methods of the city
    city_methods = [method for method in dir(paris) if not method.startswith('_')]
    agent_methods = [m for m in city_methods if 'agent' in m.lower()]
    print(f"   - City agent-related methods: {agent_methods}")
    
    print(f"\n2. Testing manual rule execution:")
    
    # Get the SendPeopleToWork rule
    rule = home_unit.m_type.rules[0]  # SendPeopleToWork
    print(f"   - Rule: {rule.type()}")
    print(f"   - Commands: {[cmd.type() for cmd in rule.commands()]}")
    
    # Check the agent command specifically
    agent_command = rule.commands()[1]  # Add Agent command
    print(f"   - Agent command type: {agent_command.type()}")
    print(f"   - Agent command target: {agent_command.m_target}")
    print(f"   - Agent command resources: {agent_command.m_resources}")
    
    # Test the individual commands
    print(f"\n3. Testing individual command validation and execution:")
    
    # Setup rule context
    context = home_unit.m_context
    print(f"   - Context setup:")
    print(f"     - context.unit: {context.unit}")
    print(f"     - context.city: {context.city}")
    print(f"     - context.locals: {context.locals}")
    
    # Test each command
    for i, command in enumerate(rule.commands()):
        print(f"\n   Command {i}: {command.type()}")
        
        # Test validation
        can_validate = command.validate(context)
        print(f"     - Validates: {can_validate}")
        
        if can_validate:
            print(f"     - Executing command...")
            try:
                command.execute(context)
                print(f"     - Command executed successfully")
                
                # Check current state
                current_resources = {res.type(): res.get_amount() for res in home_unit.resources().container()}
                print(f"     - Unit resources after: {current_resources}")
                
                if paris.agents():
                    print(f"     - Agents in city: {len(paris.agents())}")
                else:
                    print(f"     - No agents created yet")
                    
            except Exception as e:
                print(f"     - Command execution failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"     - Command validation failed")
    
    return True

if __name__ == "__main__":
    debug_agent_creation()
