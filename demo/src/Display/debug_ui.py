"""
Debug UI system for OpenGlassBox Python implementation.

This module provides a Dear ImGui-like debug interface using Pygame,
allowing inspection of simulation state including agents, units, maps, and paths.
"""

import pygame
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass
from openglassbox.city import City
from openglassbox.simulation import Simulation
from openglassbox.agent import Agent
from openglassbox.unit import Unit
from openglassbox.map import Map
from openglassbox.path import Path

# UI Colors
UI_BACKGROUND = (30, 30, 40, 180)
UI_HEADER = (50, 50, 70)
UI_TEXT = (255, 255, 255)
UI_HIGHLIGHT = (100, 150, 200)
UI_BORDER = (80, 80, 100)
UI_SELECTED = (120, 180, 220)

@dataclass
class UIState:
    """Tracks the state of collapsible UI elements."""
    expanded_headers: Set[str]
    expanded_trees: Set[str]
    selected_city: int

    def __init__(self):
        self.expanded_headers = set()
        self.expanded_trees = set()
        self.selected_city = 0

class DebugUI:
    """
    Debug UI system providing simulation introspection.

    Mimics Dear ImGui functionality for debugging simulation state.
    """

    def __init__(self, font: pygame.font.Font):
        """
        Initialize the debug UI.

        Args:
            font: Pygame font for text rendering
        """
        self.font = font
        self.small_font = pygame.font.SysFont("Arial", 12)
        self.ui_state = UIState()
        self.panel_width = 350
        self.panel_height = 500
        self.line_height = 20
        self.indent_size = 16
        self.current_y = 10
        self.visible = True

    def toggle_visibility(self):
        """Toggle debug panel visibility."""
        self.visible = not self.visible

    def hex_to_rgb(self, hex_color: int) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple."""
        r = (hex_color >> 16) & 0xFF
        g = (hex_color >> 8) & 0xFF
        b = hex_color & 0xFF
        return (r, g, b)

    def draw_background(self, surface: pygame.Surface, x: int, y: int, width: int, height: int):
        """Draw semi-transparent background panel."""
        panel_surface = pygame.Surface((width, height))
        panel_surface.set_alpha(180)
        panel_surface.fill(UI_BACKGROUND[:3])
        surface.blit(panel_surface, (x, y))

        # Draw border
        pygame.draw.rect(surface, UI_BORDER, (x, y, width, height), 2)

    def draw_text(self, surface: pygame.Surface, text: str, x: int, y: int,
                  color: Tuple[int, int, int] = UI_TEXT, font: Optional[pygame.font.Font] = None) -> int:
        """
        Draw text and return the height used.

        Args:
            surface: Surface to draw on
            text: Text to render
            x, y: Position
            color: Text color
            font: Font to use (defaults to self.font)

        Returns:
            Height of rendered text
        """
        if font is None:
            font = self.font

        text_surface = font.render(text, True, color)
        surface.blit(text_surface, (x, y))
        return text_surface.get_height()

    def draw_colored_text(self, surface: pygame.Surface, text: str, x: int, y: int,
                         entity_color: int) -> int:
        """Draw text with entity's color."""
        color = self.hex_to_rgb(entity_color)
        return self.draw_text(surface, text, x, y, color)

    def collapsing_header(self, surface: pygame.Surface, label: str, x: int, y: int) -> Tuple[bool, int]:
        """
        Draw a collapsible header.

        Returns:
            Tuple of (is_expanded, height_used)
        """
        is_expanded = label in self.ui_state.expanded_headers

        # Draw header background
        header_rect = pygame.Rect(x, y, self.panel_width - 20, self.line_height)
        pygame.draw.rect(surface, UI_HEADER, header_rect)
        pygame.draw.rect(surface, UI_BORDER, header_rect, 1)

        # Draw expand/collapse indicator
        indicator = "▼" if is_expanded else "▶"
        self.draw_text(surface, indicator, x + 5, y + 2, UI_TEXT, self.small_font)

        # Draw header text
        self.draw_text(surface, label, x + 25, y + 2, UI_TEXT)

        return is_expanded, self.line_height + 2

    def tree_node(self, surface: pygame.Surface, label: str, x: int, y: int,
                  indent: int = 0, entity_color: Optional[int] = None) -> Tuple[bool, int]:
        """
        Draw a tree node.

        Returns:
            Tuple of (is_expanded, height_used)
        """
        full_label = f"{' ' * indent}{label}"
        is_expanded = full_label in self.ui_state.expanded_trees

        # Draw expand/collapse indicator for nodes with children
        indicator = "▼" if is_expanded else "▶"
        self.draw_text(surface, indicator, x + indent * self.indent_size, y, UI_TEXT, self.small_font)

        # Draw node text with entity color if provided
        text_x = x + indent * self.indent_size + 15
        if entity_color is not None:
            height = self.draw_colored_text(surface, label, text_x, y, entity_color)
        else:
            height = self.draw_text(surface, label, text_x, y)

        return is_expanded, height + 2

    def bullet_text(self, surface: pygame.Surface, text: str, x: int, y: int, indent: int = 1) -> int:
        """Draw bullet point text."""
        bullet_x = x + indent * self.indent_size
        self.draw_text(surface, "•", bullet_x, y, UI_HIGHLIGHT, self.small_font)
        return self.draw_text(surface, text, bullet_x + 15, y, UI_TEXT, self.small_font)

    def combo_box(self, surface: pygame.Surface, label: str, items: List[str],
                  selected_index: int, x: int, y: int) -> Tuple[int, int]:
        """
        Draw a combo box for selecting items.

        Returns:
            Tuple of (selected_index, height_used)
        """
        if not items:
            return selected_index, self.line_height

        # Ensure selected index is valid
        selected_index = max(0, min(selected_index, len(items) - 1))

        # Draw label
        label_height = self.draw_text(surface, label + ":", x, y)

        # Draw combo box
        combo_y = y + label_height + 2
        combo_rect = pygame.Rect(x + 10, combo_y, self.panel_width - 40, self.line_height)
        pygame.draw.rect(surface, UI_BACKGROUND[:3], combo_rect)
        pygame.draw.rect(surface, UI_BORDER, combo_rect, 1)

        # Draw selected item
        if items:
            selected_text = items[selected_index]
            self.draw_text(surface, selected_text, x + 15, combo_y + 2, UI_TEXT, self.small_font)

        return selected_index, label_height + self.line_height + 4

    def debug_agents(self, surface: pygame.Surface, city: City, x: int, y: int) -> int:
        """Debug agents in the city."""
        is_expanded, height = self.collapsing_header(surface, "Agents", x, y)
        if not is_expanded:
            return height

        current_y = y + height

        for agent in city.agents():
            agent_label = f"Agent {agent.id()} ({agent.type()})"
            is_tree_expanded, tree_height = self.tree_node(
                surface, agent_label, x, current_y, 1, agent.m_type.color
            )
            current_y += tree_height

            if is_tree_expanded:
                # Agent position
                pos_text = f"Position: {int(agent.position().x)}, {int(agent.position().y)}"
                current_y += self.bullet_text(surface, pos_text, x, current_y, 2)

                # Agent resources
                resources_text = f"Has {len(agent.resources())} Resources:"
                current_y += self.bullet_text(surface, resources_text, x, current_y, 2)

                for resource in agent.resources():
                    res_text = f"{resource.type()}: {resource.getAmount()} / {resource.getCapacity()}"
                    current_y += self.bullet_text(surface, res_text, x, current_y, 3)

        return current_y - y

    def debug_units(self, surface: pygame.Surface, city: City, x: int, y: int) -> int:
        """Debug units in the city."""
        is_expanded, height = self.collapsing_header(surface, "Units", x, y)
        if not is_expanded:
            return height

        current_y = y + height

        for unit in city.units():
            unit_label = f"Unit {unit.id()} ({unit.type()})"
            is_tree_expanded, tree_height = self.tree_node(
                surface, unit_label, x, current_y, 1, unit.color()
            )
            current_y += tree_height

            if is_tree_expanded:
                # Unit node and position
                if hasattr(unit, 'node') and unit.node():
                    node_text = f"Node {unit.node().id()}. Position: {int(unit.position().x)}, {int(unit.position().y)}"
                else:
                    node_text = f"Position: {int(unit.position().x)}, {int(unit.position().y)}"
                current_y += self.bullet_text(surface, node_text, x, current_y, 2)

                # Unit resources
                resources = unit.resources()
                if hasattr(resources, 'container'):
                    resource_list = resources.container()
                else:
                    resource_list = resources if hasattr(resources, '__iter__') else []

                resources_text = f"Has {len(resource_list)} Resources:"
                current_y += self.bullet_text(surface, resources_text, x, current_y, 2)

                for resource in resource_list:
                    res_text = f"{resource.type()}: {resource.getAmount()} / {resource.getCapacity()}"
                    current_y += self.bullet_text(surface, res_text, x, current_y, 3)

        return current_y - y

    def debug_maps(self, surface: pygame.Surface, city: City, x: int, y: int) -> int:
        """Debug maps in the city."""
        is_expanded, height = self.collapsing_header(surface, "Maps", x, y)
        if not is_expanded:
            return height

        current_y = y + height

        for map_name, map_obj in city.maps().items():
            map_label = f"Map {map_obj.type()}"
            is_tree_expanded, tree_height = self.tree_node(
                surface, map_label, x, current_y, 1, map_obj.color()
            )
            current_y += tree_height

            if is_tree_expanded:
                # Map capacity
                capacity_text = f"Capacity: {map_obj.get_capacity()}"
                current_y += self.bullet_text(surface, capacity_text, x, current_y, 2)

                # Resource grid (show summary)
                total_resources = 0
                max_resource = 0
                for u in range(map_obj.grid_size_u()):
                    for v in range(map_obj.grid_size_v()):
                        res = map_obj.get_resource(u, v)
                        total_resources += res
                        max_resource = max(max_resource, res)

                grid_text = f"Grid: {map_obj.grid_size_u()}x{map_obj.grid_size_v()}, Total: {total_resources}, Max: {max_resource}"
                current_y += self.bullet_text(surface, grid_text, x, current_y, 2)

        return current_y - y

    def debug_paths(self, surface: pygame.Surface, city: City, x: int, y: int) -> int:
        """Debug paths in the city."""
        is_expanded, height = self.collapsing_header(surface, "Paths", x, y)
        if not is_expanded:
            return height

        current_y = y + height

        for path_name, path in city.paths().items():
            path_label = f"Path {path.type()}"
            is_tree_expanded, tree_height = self.tree_node(
                surface, path_label, x, current_y, 1, path.color()
            )
            current_y += tree_height

            if is_tree_expanded:
                # Ways summary
                ways_text = f"Ways: {len(path.ways())}"
                current_y += self.bullet_text(surface, ways_text, x, current_y, 2)

                for i, way in enumerate(path.ways()[:5]):  # Show first 5 ways
                    way_text = f"Way {way.id()}: Node {way.from_node().id()} → Node {way.to_node().id()}"
                    current_y += self.bullet_text(surface, way_text, x, current_y, 3)

                if len(path.ways()) > 5:
                    more_text = f"... and {len(path.ways()) - 5} more ways"
                    current_y += self.bullet_text(surface, more_text, x, current_y, 3)

                # Nodes summary
                nodes_text = f"Nodes: {len(path.nodes())}"
                current_y += self.bullet_text(surface, nodes_text, x, current_y, 2)

                for i, node in enumerate(path.nodes()[:5]):  # Show first 5 nodes
                    node_text = f"Node {node.id()}: ({int(node.position().x)}, {int(node.position().y)})"
                    current_y += self.bullet_text(surface, node_text, x, current_y, 3)

                if len(path.nodes()) > 5:
                    more_text = f"... and {len(path.nodes()) - 5} more nodes"
                    current_y += self.bullet_text(surface, more_text, x, current_y, 3)

        return current_y - y

    def debug_city(self, surface: pygame.Surface, city: City, x: int, y: int) -> int:
        """Debug all aspects of a city."""
        current_y = y

        current_y += self.debug_agents(surface, city, x, current_y) + 5
        current_y += self.debug_units(surface, city, x, current_y) + 5
        current_y += self.debug_maps(surface, city, x, current_y) + 5
        current_y += self.debug_paths(surface, city, x, current_y) + 5

        return current_y - y

    def handle_click(self, pos: Tuple[int, int], city_names: List[str]) -> bool:
        """
        Handle mouse clicks on UI elements.

        Args:
            pos: Mouse click position
            city_names: List of available city names

        Returns:
            True if click was handled by UI
        """
        if not self.visible:
            return False

        x, y = pos
        # Position panel on top-right corner
        screen_width = 800  # Default screen width, could be passed in
        panel_x = screen_width - self.panel_width - 10
        panel_y = 10

        # Check if click is within debug panel
        if not (panel_x <= x <= panel_x + self.panel_width and
                panel_y <= y <= panel_y + self.panel_height):
            return False

        # Simple click handling for headers (expand/collapse)
        # In a real implementation, you'd track exact positions of UI elements
        relative_y = y - panel_y

        # Estimate header positions (this is simplified)
        header_positions = ["Agents", "Units", "Maps", "Paths"]
        estimated_y = 50  # After city combo

        for header in header_positions:
            if estimated_y <= relative_y <= estimated_y + self.line_height:
                if header in self.ui_state.expanded_headers:
                    self.ui_state.expanded_headers.remove(header)
                else:
                    self.ui_state.expanded_headers.add(header)
                return True
            estimated_y += 100  # Rough estimate of header spacing

        return True

    def draw_debug_panel(self, surface: pygame.Surface, simulation: Simulation):
        """Draw the main debug panel."""
        if not self.visible:
            return

        # Position panel on top-right corner
        screen_width = surface.get_width()
        panel_x = screen_width - self.panel_width - 10
        panel_y = 10

        # Draw background panel
        self.draw_background(surface, panel_x, panel_y, self.panel_width, self.panel_height)

        current_y = panel_y + 10

        # City selection combo
        city_names = [city.name() for city in simulation.cities().values()]
        if city_names:
            # Ensure selected city index is valid
            self.ui_state.selected_city = max(0, min(self.ui_state.selected_city, len(city_names) - 1))

            selected_city, combo_height = self.combo_box(
                surface, "City", city_names, self.ui_state.selected_city,
                panel_x + 10, current_y
            )
            self.ui_state.selected_city = selected_city
            current_y += combo_height + 10

            # Debug selected city
            if city_names:
                selected_city_obj = list(simulation.cities().values())[self.ui_state.selected_city]
                self.debug_city(surface, selected_city_obj, panel_x + 10, current_y)
        else:
            self.draw_text(surface, "No cities available", panel_x + 10, current_y)

    def handle_key_press(self, key: int, city_names: List[str]):
        """Handle keyboard input for UI navigation."""
        if key == pygame.K_TAB:
            # Cycle through cities
            if city_names:
                self.ui_state.selected_city = (self.ui_state.selected_city + 1) % len(city_names)
        elif key == pygame.K_SPACE:
            # Toggle all headers
            all_headers = {"Agents", "Units", "Maps", "Paths"}
            if len(self.ui_state.expanded_headers) == len(all_headers):
                self.ui_state.expanded_headers.clear()
            else:
                self.ui_state.expanded_headers.update(all_headers)
