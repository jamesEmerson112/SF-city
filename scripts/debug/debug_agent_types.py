#!/usr/bin/env python3
"""
Debug script to check agent types and rule execution.
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
from openglassbox.resources import Resources

def debug_agent_types():
    """Debug agent types and rule execution."""
    print("=== Debugging Agent Types and Rule Execution ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse TestCity to get types
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create a test city
    print(f"\n2. Creating test city...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    people_agent_type = simulation.get_agent_type("People")
    worker_agent_type = simulation.get_agent_type("Worker")
    
    print(f"\n3. Agent Type Definitions:")
    print(f"   People agent: {people_agent_type.name}, speed: {people_agent_type.speed}")
    print(f"   Worker agent: {worker_agent_type.name}, speed: {worker_agent_type.speed}")
    
    # Create simple network
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(100.0, 100.0, 0.0))
    n2 = road.add_node(Vector3f(200.0, 100.0, 0.0))
    w1 = road.add_way(dirt_type, n1, n2)
    
    # Place units
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.25)
    work_unit = paris.add_unit_on_way(work_type, road, w1, 0.75)
    
    print(f"\n4. Initial Unit States:")
    print(f"   Home unit: {[(r.type(), r.get_amount()) for r in home_unit.resources().container()]}")
    print(f"   Work unit: {[(r.type(), r.get_amount()) for r in work_unit.resources().container()]}")
    
    # Initialize water for SendPeopleToHome condition
    water_type = simulation.get_map_type("Water")
    paris_water = paris.add_map(water_type)
    for u in range(paris_water.grid_size_u()):
        for v in range(paris_water.grid_size_v()):
            paris_water.add_resource(u, v, 80)  # Above 70 threshold
    
    print(f"   Water map initialized to 80 (above threshold of 70)")
    
    # Run simulation to track agent lifecycle
    print(f"\n5. Running simulation to track agent types and rule execution...")
    
    for tick in range(150):  # Run longer to see multiple cycles
        simulation.update(0.016)
        sim_tick = simulation.get_total_ticks()
        
        # Check unit rule execution timing
        if sim_tick % 20 == 0:  # SendPeopleToWork rate
            print(f"\nTick {sim_tick}: SendPeopleToWork should execute")
            print(f"   Home unit resources: {[(r.type(), r.get_amount()) for r in home_unit.resources().container()]}")
            print(f"   Home can spawn agent: {len([r for r in home_unit.resources().container() if r.type() == 'People' and r.get_amount() > 0]) > 0}")
        
        if sim_tick % 100 == 0 and sim_tick > 0:  # SendPeopleToHome rate
            print(f"\nTick {sim_tick}: SendPeopleToHome should execute")
            print(f"   Work unit resources: {[(r.type(), r.get_amount()) for r in work_unit.resources().container()]}")
            print(f"   Work can spawn agent: {len([r for r in work_unit.resources().container() if r.type() == 'People' and r.get_amount() > 0]) > 0}")
            print(f"   Water level: {paris_water.get_resource(5, 5)}")  # Check sample water level
        
        agent_count = len(paris.agents())
        if agent_count > 0:
            print(f"\nTick {sim_tick}: {agent_count} agent(s) active")
            for i, agent in enumerate(paris.agents()):
                print(f"   Agent {i}: type='{agent.type()}', target='{agent.m_searchTarget}', pos={agent.position()}")
                print(f"     Resources: {[(r.type(), r.get_amount()) for r in agent.resources()]}")
                print(f"     Distance to target: {(agent.position() - (work_unit.position() if agent.m_searchTarget == 'Work' else home_unit.position())).magnitude():.2f}")
        
        # Check for completed deliveries
        if tick > 50 and tick % 10 == 0:  # Check periodically after initial spawn
            print(f"\nTick {sim_tick}: Unit status check")
            print(f"   Home: {[(r.type(), r.get_amount()) for r in home_unit.resources().container()]}")
            print(f"   Work: {[(r.type(), r.get_amount()) for r in work_unit.resources().container()]}")
            
            # Check if cycle is complete
            home_people = sum(r.get_amount() for r in home_unit.resources().container() if r.type() == 'People')
            work_people = sum(r.get_amount() for r in work_unit.resources().container() if r.type() == 'People')
            
            if home_people < 4:  # Home lost people
                print(f"   → Home has lost People ({home_people}/4)")
            if work_people > 0:  # Work gained people
                print(f"   → Work has gained People ({work_people}/2)")
                
            if work_people > 0 and agent_count == 0:
                print(f"   ❌ ISSUE: Work has People but no Worker agents to return them!")
                break
                
        if tick > 100 and agent_count == 0:
            print(f"\n❌ No agents after tick 100 - system may have stopped")
            break

if __name__ == "__main__":
    debug_agent_types()
