#!/usr/bin/env python3
"""
Debug script to trace Dijkstra pathfinding step by step.
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
from openglassbox.dijkstra import Dijkstra
from openglassbox.resources import Resources

class DebugDijkstra(Dijkstra):
    """Dijkstra with debug tracing."""
    
    def find_next_point(self, from_node, search_target: str, resources):
        """Find next point with debug tracing."""
        print(f"\n=== DIJKSTRA TRACE ===")
        print(f"Starting from: {from_node.position()}")
        print(f"Searching for: '{search_target}'")
        print(f"Carrying resources: {[(r.type(), r.get_amount()) for r in resources.container()]}")
        
        # Clear our collections
        self.m_closed_set.clear()
        self.m_open_set.clear()
        self.m_came_from.clear()
        self.m_score_from_start.clear()
        self.m_score_plus_heuristic_from_start.clear()

        # Start the search from the starting node
        self.m_open_set.append(from_node)
        self.m_score_from_start[from_node] = 0.0
        self.m_score_plus_heuristic_from_start[from_node] = 0.0
        
        step = 0
        while len(self.m_open_set) > 0:
            step += 1
            print(f"\n--- Step {step} ---")
            print(f"Open set size: {len(self.m_open_set)}")
            print(f"Closed set size: {len(self.m_closed_set)}")
            
            # Get the node with lowest score
            current = self._get_point_with_lowest_score_plus_heuristic_from_start()
            if current is None:
                print("No current node found!")
                break
                
            print(f"Current node: {current.position()}")
            print(f"  Units: {len(current.units())}")
            for i, unit in enumerate(current.units()):
                print(f"    Unit {i}: {unit.type()}")
                accepts = unit.accepts(search_target, resources)
                print(f"      Accepts '{search_target}': {accepts}")
                print(f"      Unit targets: {unit.m_type.targets}")

            # Check if we've reached a target
            if self._get_unit_with_target_and_capacity(current, search_target, resources):
                print(f"✓ FOUND TARGET at {current.position()}!")
                
                # If we started at the target, we're already there
                if current is from_node:
                    print("Already at target, returning current node")
                    return current

                # Otherwise, reconstruct the path back to the start and return the next step
                print("Reconstructing path...")
                path = []
                trace_node = current
                while trace_node in self.m_came_from:
                    path.append(trace_node.position())
                    trace_node = self.m_came_from[trace_node]
                path.append(from_node.position())
                path.reverse()
                print(f"Full path: {path}")
                
                while self.m_came_from[current] is not from_node:
                    current = self.m_came_from[current]
                    
                print(f"Next step: {current.position()}")
                return current

            # Process the current node
            self.m_open_set.remove(current)
            self.m_closed_set.add(current)
            print(f"Added to closed set: {current.position()}")

            # Examine all connected ways/nodes
            print(f"Exploring {len(current.ways())} connected ways...")
            for i, way in enumerate(current.ways()):
                # Get the neighbor node (the node at the other end of the way)
                neighbor = way.to() if way.from_() is current else way.from_()
                print(f"  Way {i}: to {neighbor.position()} (distance: {way.magnitude():.2f})")

                # Calculate tentative score to this neighbor
                neighbor_score_from_start = self.m_score_from_start[current] + way.magnitude()

                # If this node is in the closed set and we don't have a better path, skip it
                if neighbor in self.m_closed_set:
                    if neighbor_score_from_start >= self.m_score_from_start.get(neighbor, float('inf')):
                        print(f"    Skipping (in closed set with worse/equal score)")
                        continue

                # If we found a better path to this neighbor, update it
                if neighbor not in self.m_open_set or neighbor_score_from_start < self.m_score_from_start.get(neighbor, float('inf')):
                    # Update or set the path and scores
                    self.m_came_from[neighbor] = current
                    self.m_score_from_start[neighbor] = neighbor_score_from_start
                    self.m_score_plus_heuristic_from_start[neighbor] = (
                        neighbor_score_from_start + self._heuristic(neighbor, from_node)
                    )

                    # Add to open set if not already there
                    if neighbor not in self.m_open_set:
                        self.m_open_set.append(neighbor)
                        print(f"    Added to open set")
                    else:
                        print(f"    Updated score in open set")

        print(f"\n--- SEARCH EXHAUSTED ---")
        print(f"No target found after {step} steps")
        
        # No path found - return a random connected node as fallback
        if from_node.ways():
            import random
            random_way = random.choice(from_node.ways())
            if random_way.from_() is from_node:
                fallback = random_way.to()
            elif random_way.to() is from_node:
                fallback = random_way.from_()
            else:
                fallback = None
                
            print(f"FALLBACK: Returning random neighbor {fallback.position() if fallback else None}")
            return fallback

        print("FALLBACK: No connected ways, returning None")
        return None

def debug_dijkstra_trace():
    """Trace Dijkstra pathfinding step by step."""
    print("=== Debugging Dijkstra Step-by-Step ===")
    
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
    
    # Create a simple triangle network
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(100.0, 100.0, 0.0))
    n2 = road.add_node(Vector3f(200.0, 100.0, 0.0))
    n3 = road.add_node(Vector3f(150.0, 200.0, 0.0))
    
    w1 = road.add_way(dirt_type, n1, n2)  # Bottom edge
    w2 = road.add_way(dirt_type, n2, n3)  # Right edge
    w3 = road.add_way(dirt_type, n3, n1)  # Left edge
    
    # Place units
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.5)
    work_unit = paris.add_unit_on_way(work_type, road, w2, 0.75)
    
    print(f"Home unit at: {home_unit.position()}")
    print(f"Work unit at: {work_unit.position()}")
    
    # Test pathfinding with debug tracing
    print(f"\n3. Testing pathfinding with debug tracing...")
    
    debug_dijkstra = DebugDijkstra()
    test_resources = Resources()
    test_resources.add_resource("People", 1)
    
    # Test from Home to Work
    print(f"\n### PATHFINDING: Home → Work ###")
    next_node = debug_dijkstra.find_next_point(home_unit.node(), "Work", test_resources)
    print(f"\nResult: {next_node.position() if next_node else None}")

if __name__ == "__main__":
    debug_dijkstra_trace()
