"""
Core simulation rendering functionality.
"""
import pygame
from typing import Dict, List, Optional, Tuple, Any, Set

from openglassbox.city import City
from openglassbox.map import Map
from openglassbox.path import Path, Node, Way
from openglassbox.unit import Unit
from openglassbox.agent import Agent
from openglassbox.vector import Vector3f

from .colors import hex_to_rgb, WHITE, BLACK
from .coordinate_system import CoordinateSystem

class SimulationRenderer:
    """Handles rendering of simulation objects (maps, paths, units, agents)."""
    
    def __init__(self, coordinate_system: CoordinateSystem, font: pygame.font.Font):
        self.coordinate_system = coordinate_system
        self.font = font

    def draw_maps(self, city: City, surface: pygame.Surface, zoom: float, 
                  camera_offset_x: float, camera_offset_y: float, show_maps: bool):
        """Draw all maps in the city."""
        if not show_maps:
            return

        for map_name, map_obj in city.maps().items():
            pos = map_obj.position()
            grid_size_u = map_obj.grid_size_u()
            grid_size_v = map_obj.grid_size_v()
            cell_size = max(1, int(zoom * 5))

            for u in range(grid_size_u):
                for v in range(grid_size_v):
                    resource_amount = map_obj.get_resource(u, v)
                    if resource_amount > 0:
                        cell_world_x = pos.x + u * 10
                        cell_world_y = pos.y + v * 10
                        screen_x, screen_y = self.coordinate_system.world_to_screen(
                            cell_world_x, cell_world_y, zoom, camera_offset_x, camera_offset_y)

                        color = hex_to_rgb(map_obj.color())
                        intensity = min(255, int(resource_amount / map_obj.get_capacity() * 255))
                        cell_color = (
                            min(255, color[0] + intensity // 3),
                            min(255, color[1] + intensity // 3),
                            min(255, color[2] + intensity // 3)
                        )

                        pygame.draw.rect(surface, cell_color,
                                       (screen_x, screen_y, cell_size, cell_size))

    def draw_paths(self, city: City, surface: pygame.Surface, zoom: float,
                   camera_offset_x: float, camera_offset_y: float, show_paths: bool):
        """Draw all paths, nodes, and ways in the city."""
        if not show_paths:
            return

        for path_name, path in city.paths().items():
            # Draw ways first
            for way in path.ways():
                from_pos = way.position1()
                to_pos = way.position2()
                from_x, from_y = self.coordinate_system.world_to_screen(
                    from_pos.x, from_pos.y, zoom, camera_offset_x, camera_offset_y)
                to_x, to_y = self.coordinate_system.world_to_screen(
                    to_pos.x, to_pos.y, zoom, camera_offset_x, camera_offset_y)

                color = hex_to_rgb(way.color())
                pygame.draw.line(surface, color, (from_x, from_y), (to_x, to_y), 2)

            # Draw nodes on top
            for i, node in enumerate(path.nodes()):
                pos = node.position()
                x, y = self.coordinate_system.world_to_screen(
                    pos.x, pos.y, zoom, camera_offset_x, camera_offset_y)

                pygame.draw.circle(surface, WHITE, (x, y), 3)
                pygame.draw.circle(surface, BLACK, (x, y), 2)

                text = self.font.render(str(i), True, WHITE)
                surface.blit(text, (x + 8, y - 8))

    def draw_units(self, city: City, surface: pygame.Surface, zoom: float,
                   camera_offset_x: float, camera_offset_y: float, show_units: bool):
        """Draw all units in the city."""
        if not show_units:
            return

        for unit in city.units():
            pos = unit.position()
            x, y = self.coordinate_system.world_to_screen(
                pos.x, pos.y, zoom, camera_offset_x, camera_offset_y)

            unit_type_name = unit.type() if callable(unit.type) else getattr(unit, "type", "Unknown")
            color = hex_to_rgb(unit.color())
            base_size = max(8, int(zoom * 3))

            if unit_type_name == "Home":
                # Draw triangle for houses
                triangle_size = base_size
                points = [
                    (x, y - triangle_size // 2),
                    (x - triangle_size // 2, y + triangle_size // 2),
                    (x + triangle_size // 2, y + triangle_size // 2)
                ]
                pygame.draw.polygon(surface, color, points)
            elif unit_type_name == "Work":
                # Draw large rectangle for factories
                size = base_size * 4
                pygame.draw.rect(surface, color, (x - size//2, y - size//2, size, size))
            else:
                # Default rectangle
                size = base_size
                pygame.draw.rect(surface, color, (x - size//2, y - size//2, size, size))

    def draw_agents(self, city: City, surface: pygame.Surface, zoom: float,
                    camera_offset_x: float, camera_offset_y: float, show_agents: bool):
        """Draw all agents in the city."""
        if not show_agents:
            return

        for agent in city.agents():
            pos = agent.position()
            x, y = self.coordinate_system.world_to_screen(
                pos.x, pos.y, zoom, camera_offset_x, camera_offset_y)

            # Determine color based on agent type
            if hasattr(agent, "type") and agent.type() == "People":
                if hasattr(agent, "goal") and agent.goal == "Work":
                    color = (255, 255, 0)  # Yellow
                elif hasattr(agent, "goal") and agent.goal == "Home":
                    color = (255, 255, 255)  # White
                else:
                    color = (255, 255, 0)  # Default yellow
            else:
                color = hex_to_rgb(agent.m_type.color)

            size = 6
            points = [
                (x, y - size),
                (x - size, y + size),
                (x + size, y + size)
            ]
            pygame.draw.polygon(surface, color, points)

    def draw_city(self, city: City, surface: pygame.Surface, zoom: float,
                  camera_offset_x: float, camera_offset_y: float, 
                  show_maps: bool, show_paths: bool, show_units: bool, show_agents: bool):
        """Draw a city and all its components."""
        self.draw_maps(city, surface, zoom, camera_offset_x, camera_offset_y, show_maps)
        self.draw_paths(city, surface, zoom, camera_offset_x, camera_offset_y, show_paths)
        self.draw_units(city, surface, zoom, camera_offset_x, camera_offset_y, show_units)
        self.draw_agents(city, surface, zoom, camera_offset_x, camera_offset_y, show_agents)

        # Draw city name
        pos = city.position()
        x, y = self.coordinate_system.world_to_screen(
            pos.x, pos.y, zoom, camera_offset_x, camera_offset_y)
        text = self.font.render(city.name().upper(), True, WHITE)
        surface.blit(text, (x - 50, y - 50))
