"""
Basic UI panels and interface elements.
"""
import pygame
from typing import Dict, List, Optional, Tuple, Any, Set

from .colors import WHITE, BLACK, RED, GREEN, BLUE, YELLOW, hex_to_rgb

class UIPanels:
    """Handles basic UI panels and interface elements."""
    
    def __init__(self, width: int, height: int, font: pygame.font.Font, big_font: pygame.font.Font):
        self.width = width
        self.height = height
        self.font = font
        self.big_font = big_font

    def draw_tick_counter(self, surface: pygame.Surface, tick_count: int, show_tick_counter: bool):
        """Draw the tick counter in the top left."""
        if not show_tick_counter:
            return
            
        tick_text = self.big_font.render(f"Ticks: {tick_count}", True, YELLOW)
        text_rect = tick_text.get_rect()
        bg_rect = text_rect.copy()
        bg_rect.x = 10
        bg_rect.y = 10
        bg_rect.width += 10
        bg_rect.height += 6
        pygame.draw.rect(surface, (0, 0, 0, 180), bg_rect)
        pygame.draw.rect(surface, YELLOW, bg_rect, 1)
        surface.blit(tick_text, (15, 13))

    def draw_debug_panel(self, surface: pygame.Surface, debug_options: Dict[str, bool], 
                        camera_offset_x: float, camera_offset_y: float, zoom: float):
        """Draw the debug panel."""
        panel_rect = pygame.Rect(10, self.height - 140, 200, 130)
        pygame.draw.rect(surface, (0, 0, 0, 180), panel_rect)
        pygame.draw.rect(surface, WHITE, panel_rect, 1)

        y_offset = self.height - 130
        for i, (option, enabled) in enumerate(debug_options.items()):
            color = GREEN if enabled else RED
            text = self.font.render(f"{option}: {'ON' if enabled else 'OFF'}", True, color)
            surface.blit(text, (20, y_offset + i * 20))

        # Camera info
        text = self.font.render(f"Camera: ({camera_offset_x}, {camera_offset_y}) Zoom: {zoom:.1f}", True, WHITE)
        surface.blit(text, (20, y_offset + 100))

    def draw_color_details_panel(self, surface: pygame.Surface, simulation):
        """Draw comprehensive type color legend panel in top-right corner."""
        # Collect unique types from all cities
        unit_types = set()
        map_types = set()
        agent_types = set()
        path_types = set()
        way_types = set()
        
        for city_name, city in simulation.cities().items():
            # Collect unit types
            for unit in city.units():
                unit_type = unit.type() if callable(unit.type) else getattr(unit, "type", "Unknown")
                unit_types.add((unit_type, unit.color()))
            
            # Collect map types
            for map_name, map_obj in city.maps().items():
                map_types.add((map_name, map_obj.color()))
            
            # Collect agent types
            for agent in city.agents():
                if hasattr(agent, 'm_type') and hasattr(agent.m_type, 'name'):
                    agent_name = agent.m_type.name
                    agent_color = agent.m_type.color
                    agent_types.add((agent_name, agent_color))
                else:
                    agent_type = agent.type() if callable(agent.type) else getattr(agent, "type", "Unknown")
                    agent_color = getattr(agent, 'color', lambda: 0xFF0000)()
                    agent_types.add((agent_type, agent_color))
            
            # Collect path types
            for path_name, path in city.paths().items():
                path_types.add((path_name, path.color()))
            
            # Collect way types from paths
            for path_name, path in city.paths().items():
                for way in path.ways():
                    if hasattr(way, 'type'):
                        way_type = way.type() if callable(way.type) else way.type
                        way_types.add((way_type, way.color()))
                    else:
                        # Default way type based on path
                        way_types.add((f"{path_name}_way", way.color()))

        # Convert sets to sorted lists
        type_groups = [
            ("Unit Types", sorted(list(unit_types))),
            ("Map Types", sorted(list(map_types))),
            ("Agent Types", sorted(list(agent_types))),
            ("Path Types", sorted(list(path_types))),
            ("Way Types", sorted(list(way_types))),
        ]

        # Calculate legend panel dimensions
        legend_panel_width = 220
        legend_panel_height = 0
        
        # Calculate height needed
        for group_name, type_list in type_groups:
            if type_list:  # Only add height if group has items
                legend_panel_height += 18  # group title
                legend_panel_height += 16 * len(type_list)
                legend_panel_height += 6   # spacing
        legend_panel_height += 10  # padding

        # Panel position (top right)
        legend_panel_x = self.width - legend_panel_width - 10
        legend_panel_y = 10
        legend_x = legend_panel_x + 10
        legend_y = legend_panel_y + 10

        # Draw panel background
        pygame.draw.rect(surface, (0, 0, 0, 180), (legend_panel_x, legend_panel_y, legend_panel_width, legend_panel_height))
        pygame.draw.rect(surface, WHITE, (legend_panel_x, legend_panel_y, legend_panel_width, legend_panel_height), 1)

        # Draw type groups
        for group_name, type_list in type_groups:
            if not type_list:  # Skip empty groups
                continue
                
            text = self.font.render(group_name + ":", True, WHITE)
            surface.blit(text, (legend_x, legend_y))
            legend_y += 18
            
            for type_name, color_val in type_list:
                # Get color
                if callable(color_val):
                    color_val = color_val()
                color_rgb = hex_to_rgb(color_val) if color_val is not None else (128, 128, 128)
                
                # Draw color swatch
                pygame.draw.rect(surface, color_rgb, (legend_x, legend_y + 3, 16, 12))
                pygame.draw.rect(surface, WHITE, (legend_x, legend_y + 3, 16, 12), 1)
                
                # Draw name
                text = self.font.render(str(type_name), True, WHITE)
                surface.blit(text, (legend_x + 22, legend_y))
                legend_y += 16
            
            legend_y += 6  # spacing between groups

    def draw_status(self, surface: pygame.Surface, paused: bool, fps: int):
        """Draw status information."""
        status = "PAUSED" if paused else "RUNNING"
        status_text = self.font.render(f"Status: {status} | FPS: {fps}", True, WHITE)
        surface.blit(status_text, (self.width - 200, 10))

    def draw_grid(self, surface: pygame.Surface):
        """Draw reference grid."""
        grid_size = 50
        for x in range(0, self.width, grid_size):
            pygame.draw.line(surface, (70, 70, 120), (x, 0), (x, self.height), 1)
        for y in range(0, self.height, grid_size):
            pygame.draw.line(surface, (70, 70, 120), (0, y), (self.width, y), 1)

    def draw_instructions(self, surface: pygame.Surface):
        """Draw pause screen instructions."""
        big_font = pygame.font.SysFont("Arial", 24)
        text1 = big_font.render("- PRESS P TO PLAY!", True, WHITE)
        text2 = big_font.render("- PRESS D TO SHOW DEBUG DURING THE PLAY!", True, WHITE)
        text3 = big_font.render("- PRESS I TO SHOW COLOR DETAILS!", True, WHITE)
        text4 = big_font.render("- PRESS T TO TOGGLE TICK COUNTER!", True, WHITE)
        text5 = big_font.render("- PRESS C TO SHOW COMPREHENSIVE DEBUG!", True, WHITE)

        surface.blit(text1, (50, 150))
        surface.blit(text2, (50, 200))
        surface.blit(text3, (50, 250))
        surface.blit(text4, (50, 300))
        surface.blit(text5, (50, 350))
