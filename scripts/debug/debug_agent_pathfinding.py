#!/usr/bin/env python3
"""
Debug script to trace agent pathfinding behavior and why agents disappear.
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

def debug_agent_pathfinding():
    """Debug agent pathfinding to see why they disappear."""
    print("=== Debugging Agent Pathfinding Issues ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse the original TestCity.txt file
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create a test city with a more complex path setup
    print(f"\n2. Creating test city with complex pathfinding scenario...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    grass_type = simulation.get_map_type("Grass")
    water_type = simulation.get_map_type("Water")
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    
    # Add maps
    paris_grass = paris.add_map(grass_type)
    paris_water = paris.add_map(water_type)
    
    # Create a triangle path network (like in the original demo)
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(60.0, 60.0, 0.0))    # Bottom left
    n2 = road.add_node(Vector3f(300.0, 300.0, 0.0))  # Top right  
    n3 = road.add_node(Vector3f(60.0, 300.0, 0.0))   # Top left
    
    # Connect all nodes in a triangle
    w1 = road.add_way(dirt_type, n1, n2)  # Bottom-left to top-right
    w2 = road.add_way(dirt_type, n2, n3)  # Top-right to top-left
    w3 = road.add_way(dirt_type, n3, n1)  # Top-left to bottom-left
    
    # Add units like the original demo - spread around the triangle
    u1 = paris.add_unit_on_way(home_type, road, w1, 0.66)  # Home on way 1
    u2 = paris.add_unit_on_way(home_type, road, w1, 0.5)   # Home on way 1
    u3 = paris.add_unit_on_way(work_type, road, w2, 0.5)   # Work on way 2
    u4 = paris.add_unit_on_way(work_type, road, w3, 0.5)   # Work on way 3
    
    print(f"✓ Created city with {len(paris.units())} units")
    print(f"  - Network: 3 nodes, 3 ways in triangle formation")
    print(f"  - Units: 2 Home units, 2 Work units")
    
    # Initialize water in the map (for the SendPeopleToHome condition)
    print(f"\n3. Initializing water resources...")
    for u in range(paris_water.grid_size_u()):
        for v in range(paris_water.grid_size_v()):
            paris_water.add_resource(u, v, 80)  # Set water > 70
    print(f"✓ Set water levels to 80 (above the required 70)")
    
    # Track agent state in detail
    print(f"\n4. Detailed agent tracking over 150 ticks...")
    
    agent_history = {}  # Track each agent's lifecycle
    
    for tick in range(150):
        # Record state before update
        agents_before = list(paris.agents())
        
        # Run one simulation step
        simulation.update(0.016)  # ~60 FPS delta time
        
        # Record state after update
        agents_after = list(paris.agents())
        sim_tick = simulation.get_total_ticks()
        
        # Track agent spawning and disappearing
        agent_ids_before = {agent.id() for agent in agents_before}
        agent_ids_after = {agent.id() for agent in agents_after}
        
        # New agents spawned?
        new_agents = agent_ids_after - agent_ids_before
        for agent_id in new_agents:
            agent = next(a for a in agents_after if a.id() == agent_id)
            agent_history[agent_id] = {
                'spawn_tick': sim_tick,
                'type': agent.type(),
                'spawn_pos': agent.position(),
                'positions': [agent.position()],
                'target': getattr(agent, 'm_searchTarget', 'unknown'),
                'resources': len(agent.resources())
            }
            print(f"Tick {sim_tick:3d}: Agent {agent_id} SPAWNED ({agent.type()}) at {agent.position()} → target: {agent_history[agent_id]['target']}")
        
        # Agents disappeared?
        disappeared_agents = agent_ids_before - agent_ids_after
        for agent_id in disappeared_agents:
            if agent_id in agent_history:
                history = agent_history[agent_id]
                print(f"Tick {sim_tick:3d}: Agent {agent_id} DISAPPEARED after {sim_tick - history['spawn_tick']} ticks")
                print(f"    → Journey: {history['spawn_pos']} → {history['positions'][-1]}")
                print(f"    → Target: {history['target']}, Resources: {history['resources']}")
                
                # Try to determine why it disappeared
                if len(history['positions']) <= 2:
                    print(f"    → ISSUE: Agent barely moved before disappearing!")
                
                # Check if it reached a valid destination
                last_pos = history['positions'][-1]
                print(f"    → Final position: {last_pos}")
        
        # Update positions for existing agents
        for agent in agents_after:
            if agent.id() in agent_history:
                agent_history[agent.id()]['positions'].append(agent.position())
        
        # Report agent movement every 20 ticks
        if sim_tick % 20 == 0 and agents_after:
            print(f"Tick {sim_tick:3d}: {len(agents_after)} active agents:")
            for agent in agents_after:
                if agent.id() in agent_history:
                    history = agent_history[agent.id()]
                    age = sim_tick - history['spawn_tick']
                    print(f"    → Agent {agent.id()}: age={age}, pos={agent.position()}")
    
    # Final analysis
    print(f"\n5. Final Analysis:")
    print(f"   Total agents that existed: {len(agent_history)}")
    
    for agent_id, history in agent_history.items():
        lifespan = len(history['positions'])
        print(f"   Agent {agent_id}: lived {lifespan} ticks, moved from {history['spawn_pos']} to {history['positions'][-1]}")

if __name__ == "__main__":
    debug_agent_pathfinding()
