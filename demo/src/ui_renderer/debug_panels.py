"""
Comprehensive debug panels for detailed simulation introspection.
"""
import pygame
from typing import Dict, List, Optional, Tuple, Any, Set

from .colors import WHITE, BLACK, hex_to_rgb

class DebugPanels:
    """Handles comprehensive debug panels with detailed simulation introspection."""
    
    def __init__(self, width: int, height: int, font: pygame.font.Font, big_font: pygame.font.Font, small_font: pygame.font.Font):
        self.width = width
        self.height = height
        self.font = font
        self.big_font = big_font
        self.small_font = small_font

    def draw_comprehensive_debug_panel(self, surface: pygame.Surface, simulation):
        """Draw comprehensive debug panel with detailed simulation introspection (C++ style)."""
        if not simulation.cities():
            return
            
        # Panel dimensions and position (right sidebar)
        panel_width = 400
        panel_height = self.height - 20
        panel_x = self.width - panel_width - 10
        panel_y = 10
        
        # Draw main panel background
        pygame.draw.rect(surface, (30, 30, 40, 220), (panel_x, panel_y, panel_width, panel_height))
        pygame.draw.rect(surface, (80, 80, 100), (panel_x, panel_y, panel_width, panel_height), 2)
        
        # Scrollable content area
        content_x = panel_x + 10
        content_y = panel_y + 10
        content_width = panel_width - 20
        current_y = content_y
        
        # City selection header
        cities = list(simulation.cities().values())
        if not cities:
            return
            
        # For now, show first city (could add city selector later)
        city = cities[0]
        
        # City Header
        city_text = f"City: {city.name()}"
        text_surface = self.font.render(city_text, True, WHITE)
        surface.blit(text_surface, (content_x, current_y))
        current_y += 25
        
        # Draw separator
        pygame.draw.line(surface, (80, 80, 100), (content_x, current_y), (content_x + content_width - 20, current_y), 1)
        current_y += 10
        
        # Debug each component
        current_y = self._debug_agents_comprehensive(surface, city, content_x, current_y, content_width)
        current_y = self._debug_units_comprehensive(surface, city, content_x, current_y, content_width)
        current_y = self._debug_maps_comprehensive(surface, city, content_x, current_y, content_width)
        current_y = self._debug_paths_comprehensive(surface, city, content_x, current_y, content_width)

    def _debug_agents_comprehensive(self, surface: pygame.Surface, city, x: int, y: int, width: int) -> int:
        """Debug agents with comprehensive details like C++ version."""
        current_y = y
        
        # Agents header
        header_text = "▼ Agents"
        text_surface = self.big_font.render(header_text, True, (100, 150, 200))
        surface.blit(text_surface, (x, current_y))
        current_y += 25
        
        for agent in city.agents():
            # Agent ID and type
            agent_label = f"  Agent {agent.id()} ({agent.type()})"
            color = hex_to_rgb(agent.m_type.color) if hasattr(agent, 'm_type') else (255, 255, 255)
            text_surface = self.font.render(agent_label, True, color)
            surface.blit(text_surface, (x + 10, current_y))
            current_y += 18
            
            # Agent position
            pos = agent.position()
            pos_text = f"    Position: {int(pos.x)}, {int(pos.y)}"
            text_surface = self.small_font.render(pos_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            # Agent resources
            resources = agent.resources()
            res_count_text = f"    Has {len(resources)} Resources:"
            text_surface = self.small_font.render(res_count_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            for resource in resources:
                res_text = f"      • {resource.type()}: {resource.get_amount()} / {resource.get_capacity()}"
                text_surface = self.small_font.render(res_text, True, (200, 200, 200))
                surface.blit(text_surface, (x + 30, current_y))
                current_y += 13
            
            current_y += 5  # spacing between agents
        
        current_y += 10
        return current_y
    
    def _debug_units_comprehensive(self, surface: pygame.Surface, city, x: int, y: int, width: int) -> int:
        """Debug units with comprehensive details like C++ version."""
        current_y = y
        
        # Units header
        header_text = "▼ Units"
        text_surface = self.big_font.render(header_text, True, (100, 150, 200))
        surface.blit(text_surface, (x, current_y))
        current_y += 25
        
        for unit in city.units():
            # Unit ID and type
            unit_label = f"  Unit {unit.id()} ({unit.type()})"
            color = hex_to_rgb(unit.color())
            text_surface = self.font.render(unit_label, True, color)
            surface.blit(text_surface, (x + 10, current_y))
            current_y += 18
            
            # Unit node and position
            pos = unit.position()
            if hasattr(unit, 'node') and unit.node():
                node_text = f"    Node {unit.node().id()}. Position: {int(pos.x)}, {int(pos.y)}"
            else:
                node_text = f"    Position: {int(pos.x)}, {int(pos.y)}"
            text_surface = self.small_font.render(node_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            # Unit resources
            resources = unit.resources()
            if hasattr(resources, 'container'):
                resource_list = resources.container()
            else:
                resource_list = resources if hasattr(resources, '__iter__') else []
            
            res_count_text = f"    Has {len(resource_list)} Resources:"
            text_surface = self.small_font.render(res_count_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            for resource in resource_list:
                res_text = f"      • {resource.type()}: {resource.get_amount()} / {resource.get_capacity()}"
                text_surface = self.small_font.render(res_text, True, (200, 200, 200))
                surface.blit(text_surface, (x + 30, current_y))
                current_y += 13
            
            current_y += 5  # spacing between units
        
        current_y += 10
        return current_y
    
    def _debug_maps_comprehensive(self, surface: pygame.Surface, city, x: int, y: int, width: int) -> int:
        """Debug maps with comprehensive details like C++ version."""
        current_y = y
        
        # Maps header
        header_text = "▼ Maps"
        text_surface = self.big_font.render(header_text, True, (100, 150, 200))
        surface.blit(text_surface, (x, current_y))
        current_y += 25
        
        for map_name, map_obj in city.maps().items():
            # Map name
            map_label = f"  Map {map_obj.type()}"
            color = hex_to_rgb(map_obj.color())
            text_surface = self.font.render(map_label, True, color)
            surface.blit(text_surface, (x + 10, current_y))
            current_y += 18
            
            # Map capacity
            capacity_text = f"    Capacity: {map_obj.get_capacity()}"
            text_surface = self.small_font.render(capacity_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            # Resource grid - show summary and first few rows like C++
            grid_u = map_obj.grid_size_u()
            grid_v = map_obj.grid_size_v()
            total_resources = 0
            max_resource = 0
            
            # Calculate totals
            for u in range(grid_u):
                for v in range(grid_v):
                    res = map_obj.get_resource(u, v)
                    total_resources += res
                    max_resource = max(max_resource, res)
            
            # Show grid summary
            grid_summary = f"    Grid {grid_u}x{grid_v}: Total={total_resources}, Max={max_resource}"
            text_surface = self.small_font.render(grid_summary, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            # Show first few rows of resources (like C++ version)
            resources_header = "    Resources:"
            text_surface = self.small_font.render(resources_header, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 13
            
            # Show first 3 rows (to avoid too much clutter)
            for u in range(min(3, grid_u)):
                row_values = []
                for v in range(grid_v):
                    row_values.append(str(map_obj.get_resource(u, v)))
                row_text = f"      {u} => " + " ".join(row_values)
                
                # Truncate if too long to fit
                if len(row_text) > 45:
                    row_text = row_text[:42] + "..."
                
                text_surface = self.small_font.render(row_text, True, (200, 200, 200))
                surface.blit(text_surface, (x + 30, current_y))
                current_y += 12
            
            if grid_u > 3:
                more_text = f"      ... and {grid_u - 3} more rows"
                text_surface = self.small_font.render(more_text, True, (150, 150, 150))
                surface.blit(text_surface, (x + 30, current_y))
                current_y += 12
            
            # Map rules information
            if hasattr(map_obj, 'm_type') and hasattr(map_obj.m_type, 'rules') and map_obj.m_type.rules:
                rules_text = f"    Map Rules: {len(map_obj.m_type.rules)}"
                text_surface = self.small_font.render(rules_text, True, WHITE)
                surface.blit(text_surface, (x + 20, current_y))
                current_y += 13
                
                for rule in map_obj.m_type.rules[:2]:  # Show first 2 rules
                    if hasattr(rule, 'rate'):
                        rule_text = f"      • Rate: {rule.rate()}"
                        if hasattr(rule, 'is_random') and rule.is_random():
                            rule_text += f", Random: {rule.percent(100)}%"
                        text_surface = self.small_font.render(rule_text, True, (200, 200, 200))
                        surface.blit(text_surface, (x + 30, current_y))
                        current_y += 12
            
            current_y += 8  # spacing between maps
        
        current_y += 10
        return current_y
    
    def _debug_paths_comprehensive(self, surface: pygame.Surface, city, x: int, y: int, width: int) -> int:
        """Debug paths with comprehensive details like C++ version."""
        current_y = y
        
        # Paths header
        header_text = "▼ Paths"
        text_surface = self.big_font.render(header_text, True, (100, 150, 200))
        surface.blit(text_surface, (x, current_y))
        current_y += 25
        
        for path_name, path in city.paths().items():
            # Path name
            path_label = f"  Path {path.type()}"
            color = hex_to_rgb(path.color())
            text_surface = self.font.render(path_label, True, color)
            surface.blit(text_surface, (x + 10, current_y))
            current_y += 18
            
            # Nodes summary
            nodes_text = f"    Nodes: {len(path.nodes())}"
            text_surface = self.small_font.render(nodes_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            # Ways summary
            ways_text = f"    Ways: {len(path.ways())}"
            text_surface = self.small_font.render(ways_text, True, WHITE)
            surface.blit(text_surface, (x + 20, current_y))
            current_y += 15
            
            # Show first few nodes
            if path.nodes():
                nodes_header = "    First Nodes:"
                text_surface = self.small_font.render(nodes_header, True, WHITE)
                surface.blit(text_surface, (x + 20, current_y))
                current_y += 13
                
                for i, node in enumerate(path.nodes()[:3]):  # Show first 3 nodes
                    pos = node.position()
                    node_text = f"      {i}: ({int(pos.x)}, {int(pos.y)})"
                    text_surface = self.small_font.render(node_text, True, (200, 200, 200))
                    surface.blit(text_surface, (x + 30, current_y))
                    current_y += 12
                
                if len(path.nodes()) > 3:
                    more_nodes_text = f"      ... and {len(path.nodes()) - 3} more nodes"
                    text_surface = self.small_font.render(more_nodes_text, True, (150, 150, 150))
                    surface.blit(text_surface, (x + 30, current_y))
                    current_y += 12
            
            current_y += 8  # spacing between paths
        
        current_y += 10
        return current_y
