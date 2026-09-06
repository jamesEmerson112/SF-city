"""
Modular UI Renderer for OpenGlassBox demo.

This module provides a clean interface to all UI rendering functionality
by orchestrating specialized renderer components.
"""

import pygame
from typing import Dict, List, Optional, Tuple, Any, Set

from openglassbox.city import City

from .colors import WHITE, BLACK, RED, GREEN, BLUE, GRAY, DARK_GRAY, LIGHT_GRAY, YELLOW, hex_to_rgb
from .coordinate_system import CoordinateSystem
from .simulation_renderer import SimulationRenderer
from .ui_panels import UIPanels
from .debug_panels import DebugPanels

class UIRenderer:
    """Main UI renderer that orchestrates all rendering components."""
    
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        
        # Initialize fonts
        self.font = pygame.font.SysFont("Arial", 16)
        self.big_font = pygame.font.SysFont("Arial", 20, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 12)
        
        # Initialize component systems
        self.coordinate_system = CoordinateSystem(width, height)
        self.simulation_renderer = SimulationRenderer(self.coordinate_system, self.font)
        self.ui_panels = UIPanels(width, height, self.font, self.big_font)
        self.debug_panels = DebugPanels(width, height, self.font, self.big_font, self.small_font)
    
    def world_to_screen(self, world_x: float, world_y: float, zoom: float, 
                       camera_offset_x: float, camera_offset_y: float) -> Tuple[int, int]:
        """Convert world coordinates to screen coordinates."""
        return self.coordinate_system.world_to_screen(world_x, world_y, zoom, camera_offset_x, camera_offset_y)

    def draw_maps(self, city: City, surface: pygame.Surface, zoom: float, 
                  camera_offset_x: float, camera_offset_y: float, show_maps: bool):
        """Draw all maps in the city."""
        self.simulation_renderer.draw_maps(city, surface, zoom, camera_offset_x, camera_offset_y, show_maps)

    def draw_paths(self, city: City, surface: pygame.Surface, zoom: float,
                   camera_offset_x: float, camera_offset_y: float, show_paths: bool):
        """Draw all paths, nodes, and ways in the city."""
        self.simulation_renderer.draw_paths(city, surface, zoom, camera_offset_x, camera_offset_y, show_paths)

    def draw_units(self, city: City, surface: pygame.Surface, zoom: float,
                   camera_offset_x: float, camera_offset_y: float, show_units: bool):
        """Draw all units in the city."""
        self.simulation_renderer.draw_units(city, surface, zoom, camera_offset_x, camera_offset_y, show_units)

    def draw_agents(self, city: City, surface: pygame.Surface, zoom: float,
                    camera_offset_x: float, camera_offset_y: float, show_agents: bool):
        """Draw all agents in the city."""
        self.simulation_renderer.draw_agents(city, surface, zoom, camera_offset_x, camera_offset_y, show_agents)

    def draw_city(self, city: City, surface: pygame.Surface, zoom: float,
                  camera_offset_x: float, camera_offset_y: float, 
                  show_maps: bool, show_paths: bool, show_units: bool, show_agents: bool):
        """Draw a city and all its components."""
        self.simulation_renderer.draw_city(city, surface, zoom, camera_offset_x, camera_offset_y, 
                                         show_maps, show_paths, show_units, show_agents)

    def draw_tick_counter(self, surface: pygame.Surface, tick_count: int, show_tick_counter: bool):
        """Draw the tick counter in the top left."""
        self.ui_panels.draw_tick_counter(surface, tick_count, show_tick_counter)

    def draw_debug_panel(self, surface: pygame.Surface, debug_options: Dict[str, bool], 
                        camera_offset_x: float, camera_offset_y: float, zoom: float):
        """Draw the debug panel."""
        self.ui_panels.draw_debug_panel(surface, debug_options, camera_offset_x, camera_offset_y, zoom)

    def draw_color_details_panel(self, surface: pygame.Surface, simulation):
        """Draw comprehensive type color legend panel in top-right corner."""
        self.ui_panels.draw_color_details_panel(surface, simulation)

    def draw_status(self, surface: pygame.Surface, paused: bool, fps: int):
        """Draw status information."""
        self.ui_panels.draw_status(surface, paused, fps)

    def draw_grid(self, surface: pygame.Surface):
        """Draw reference grid."""
        self.ui_panels.draw_grid(surface)

    def draw_instructions(self, surface: pygame.Surface):
        """Draw pause screen instructions."""
        self.ui_panels.draw_instructions(surface)

    def draw_comprehensive_debug_panel(self, surface: pygame.Surface, simulation):
        """Draw comprehensive debug panel with detailed simulation introspection."""
        self.debug_panels.draw_comprehensive_debug_panel(surface, simulation)
