#!/usr/bin/env python3
"""
Debug script to trace agent movement step by step.
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

def debug_agent_movement():
    """Debug agent movement behavior."""
    print("=== Debugging Agent Movement ===")
    
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
    
    # Create simple straight line network
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(100.0, 100.0, 0.0))
    n2 = road.add_node(Vector3f(200.0, 100.0, 0.0))
    w1 = road.add_way(dirt_type, n1, n2)
    
    # Place units
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.25)  # At 125,100
    work_unit = paris.add_unit_on_way(work_type, road, w1, 0.75)  # At 175,100
    
    print(f"Home unit at: {home_unit.position()}")
    print(f"Work unit at: {work_unit.position()}")
    print(f"Distance between units: {(work_unit.position() - home_unit.position()).magnitude():.2f}")
    
    # Initialize water for SendPeopleToHome condition
    water_type = simulation.get_map_type("Water")
    paris_water = paris.add_map(water_type)
    for u in range(paris_water.grid_size_u()):
        for v in range(paris_water.grid_size_v()):
            paris_water.add_resource(u, v, 80)
    
    print(f"\n3. Initial network state:")
    print(f"   Nodes: {len(road.nodes())}")
    print(f"   Ways: {len(road.ways())}")
    for i, node in enumerate(road.nodes()):
        print(f"     Node {i}: {node.position()}, units: {len(node.units())}, ways: {len(node.ways())}")
    
    # Run simulation to track complete agent lifecycle
    print(f"\n4. Running simulation to track complete agent lifecycle...")
    debug_agent_movement.last_pos = None
    debug_agent_movement.delivered = False
    
    for tick in range(100):  # Run longer to see complete lifecycle
        simulation.update(0.016)
        sim_tick = simulation.get_total_ticks()
        
        agent_count = len(paris.agents())
        
        if agent_count > 0:
            agent = paris.agents()[0]
            print(f"Tick {sim_tick}: Agent {agent.id()} at {agent.position()}")
            
            # Check agent's internal state
            print(f"  Agent state:")
            print(f"    m_lastNode: {agent.m_lastNode.position() if agent.m_lastNode else None}")
            print(f"    m_nextNode: {agent.m_nextNode.position() if agent.m_nextNode else None}")
            if agent.m_currentWay:
                print(f"    m_currentWay: {agent.m_currentWay.from_().position()} → {agent.m_currentWay.to().position()}")
            else:
                print(f"    m_currentWay: None")
            print(f"    m_offset: {agent.m_offset}")
            print(f"    m_searchTarget: {agent.m_searchTarget}")
            print(f"    Resources: {[(r.type(), r.get_amount()) for r in agent.resources()]}")
            
            # Check if agent reached destination
            dist_to_work = (agent.position() - work_unit.position()).magnitude()
            print(f"    Distance to Work unit: {dist_to_work:.4f}")
            
            # Manual pathfinding test when agent needs new target
            if agent.m_nextNode is None:
                print(f"  → Agent needs new pathfinding target")
                next_node = paris.m_dijkstra.find_next_point(agent.m_lastNode, agent.m_searchTarget, agent.m_resources)
                print(f"  → Dijkstra suggests: {next_node.position() if next_node else None}")
            
            # Check if agent is moving
            if debug_agent_movement.last_pos is not None:
                dist_moved = (agent.position() - debug_agent_movement.last_pos).magnitude()
                print(f"  → Distance moved since last tick: {dist_moved:.4f}")
                
                # Check for delivery completion
                if dist_to_work < 1.0 and not debug_agent_movement.delivered:
                    print(f"  🎯 AGENT REACHED WORK UNIT!")
                    print(f"     Work unit resources before: {[(r.type(), r.get_amount()) for r in work_unit.resources().container()]}")
                    debug_agent_movement.delivered = True
                    
            debug_agent_movement.last_pos = agent.position()
            
            print()
            
        elif debug_agent_movement.last_pos is not None:
            # Agent disappeared
            print(f"Tick {sim_tick}: ❌ AGENT DISAPPEARED! (total agents: {agent_count})")
            print(f"  Work unit resources after: {[(r.type(), r.get_amount()) for r in work_unit.resources().container()]}")
            print(f"  Home unit resources after: {[(r.type(), r.get_amount()) for r in home_unit.resources().container()]}")
            print()
            break
        
        # Check for new agents
        if sim_tick % 22 == 0 and sim_tick > 22:  # Agent spawn interval
            print(f"Tick {sim_tick}: Expected new agent spawn (total agents: {agent_count})")
            if agent_count == 0:
                print("  ❌ No agents! Rule execution may have stopped.")
                print(f"  Home unit resources: {[(r.type(), r.get_amount()) for r in home_unit.resources().container()]}")

if __name__ == "__main__":
    debug_agent_movement()
