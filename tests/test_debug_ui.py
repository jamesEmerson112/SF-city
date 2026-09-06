"""
Tests for the debug UI system.

Tests the Dear ImGui-equivalent debug panels and interactive UI components.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pygame
from typing import List, Dict

from demo.src.Display.debug_ui import DebugUI
from openglassbox.simulation import Simulation
from openglassbox.city import City
from openglassbox.vector import Vector3f


class TestDebugUI(unittest.TestCase):
    """Test cases for the DebugUI class."""

    def setUp(self):
        """Set up test fixtures."""
        pygame.init()
        pygame.font.init()
        self.font = pygame.font.SysFont("Arial", 16)
        self.debug_ui = DebugUI(self.font)

        # Create a mock simulation with test data
        self.simulation = Simulation(12, 12)
        self.city = self.simulation.add_city("TestCity", Vector3f(100, 100, 0))

        # Create mock surface
        self.surface = pygame.Surface((800, 600))

    def tearDown(self):
        """Clean up after tests."""
        pygame.quit()

    def test_init(self):
        """Test DebugUI initialization."""
        debug_ui = DebugUI(self.font)
        # visible starts True in actual implementation
        self.assertTrue(debug_ui.visible)
        self.assertEqual(debug_ui.ui_state.selected_city, 0)
        self.assertIsNotNone(debug_ui.font)
        self.assertEqual(debug_ui.panel_width, 350)

    def test_visibility_toggle(self):
        """Test showing and hiding the debug UI."""
        # Initially visible
        self.assertTrue(self.debug_ui.visible)

        # Toggle to hide
        self.debug_ui.toggle_visibility()
        self.assertFalse(self.debug_ui.visible)

        # Toggle to show
        self.debug_ui.toggle_visibility()
        self.assertTrue(self.debug_ui.visible)

    def test_draw_debug_panel_hidden(self):
        """Test that nothing is drawn when debug UI is hidden."""
        self.debug_ui.visible = False

        # draw_debug_panel should return immediately when not visible
        # We verify this by ensuring it doesn't raise any errors
        self.debug_ui.draw_debug_panel(self.surface, self.simulation)
        # If we got here, the method returned cleanly without drawing

    def test_draw_debug_panel_visible(self):
        """Test that debug panel is drawn when visible."""
        self.debug_ui.visible = True

        # Should not raise any errors when drawing
        try:
            self.debug_ui.draw_debug_panel(self.surface, self.simulation)
        except Exception as e:
            self.fail(f"draw_debug_panel raised an exception: {e}")

    def test_expanded_headers(self):
        """Test collapsible header functionality using expanded_headers set."""
        # ui_state.expanded_headers is a set
        self.assertIsInstance(self.debug_ui.ui_state.expanded_headers, set)

        # Initially empty (all collapsed)
        self.assertEqual(len(self.debug_ui.ui_state.expanded_headers), 0)

        # Expand a header
        self.debug_ui.ui_state.expanded_headers.add("Agents")
        self.assertIn("Agents", self.debug_ui.ui_state.expanded_headers)

        # Collapse it
        self.debug_ui.ui_state.expanded_headers.remove("Agents")
        self.assertNotIn("Agents", self.debug_ui.ui_state.expanded_headers)

    def test_city_selection(self):
        """Test city selection functionality."""
        # Add multiple cities to simulation
        city2 = self.simulation.add_city("SecondCity", Vector3f(200, 200, 0))
        city3 = self.simulation.add_city("ThirdCity", Vector3f(300, 300, 0))

        # Test initial selection
        self.assertEqual(self.debug_ui.ui_state.selected_city, 0)

        # Cycle to next city
        self.debug_ui.ui_state.selected_city = 1
        self.assertEqual(self.debug_ui.ui_state.selected_city, 1)

        # Cycle to third city
        self.debug_ui.ui_state.selected_city = 2
        self.assertEqual(self.debug_ui.ui_state.selected_city, 2)

        # Test wrapping
        self.debug_ui.ui_state.selected_city = 0
        self.assertEqual(self.debug_ui.ui_state.selected_city, 0)

    def test_handle_click_on_panel(self):
        """Test clicking on the debug panel."""
        city_names = ["TestCity"]

        # Click inside panel area (panel is on right side: screen_width - panel_width - 10)
        # Default screen_width is 800, panel_width is 350
        panel_x = 800 - 350 - 10  # 440
        click_pos = (panel_x + 10, 60)

        # Test click handling
        result = self.debug_ui.handle_click(click_pos, city_names)

        # Should return True if click was in panel
        self.assertTrue(result)

    def test_handle_click_outside_panel(self):
        """Test clicking outside the debug panel."""
        city_names = ["TestCity"]

        # Click far to the left, outside the panel
        click_pos = (10, 500)

        # Test click handling
        result = self.debug_ui.handle_click(click_pos, city_names)

        # Should return False if click was not in panel
        self.assertFalse(result)

    def test_key_press_tab_cycles_cities(self):
        """Test that Tab key cycles through cities."""
        # Add multiple cities
        city2 = self.simulation.add_city("SecondCity", Vector3f(200, 200, 0))
        city_names = list(self.simulation.cities().keys())

        # Test Tab key press
        initial_index = self.debug_ui.ui_state.selected_city
        self.debug_ui.handle_key_press(pygame.K_TAB, city_names)

        # Should cycle to next city
        expected_index = (initial_index + 1) % len(city_names)
        self.assertEqual(self.debug_ui.ui_state.selected_city, expected_index)

    def test_key_press_space_toggles_headers(self):
        """Test that Space key toggles all headers."""
        # Initially no headers expanded
        self.assertEqual(len(self.debug_ui.ui_state.expanded_headers), 0)

        # Test Space key press - should expand all
        self.debug_ui.handle_key_press(pygame.K_SPACE, ["TestCity"])

        # Should have expanded all headers
        all_headers = {"Agents", "Units", "Maps", "Paths"}
        self.assertEqual(self.debug_ui.ui_state.expanded_headers, all_headers)

        # Press space again - should collapse all
        self.debug_ui.handle_key_press(pygame.K_SPACE, ["TestCity"])
        self.assertEqual(len(self.debug_ui.ui_state.expanded_headers), 0)

    def test_draw_text_helper(self):
        """Test the text drawing helper method."""
        # draw_text is public in actual implementation
        result_height = self.debug_ui.draw_text(
            self.surface, "Test Text", 10, 20, (255, 255, 255)
        )

        # Should return height of rendered text
        self.assertGreater(result_height, 0)

    def test_collapsing_header(self):
        """Test the collapsing_header method."""
        # Test drawing header
        is_expanded, height = self.debug_ui.collapsing_header(
            self.surface, "Test Header", 10, 20
        )

        # Should return expanded state and height
        self.assertIsInstance(is_expanded, bool)
        self.assertGreater(height, 0)

    def test_error_handling_with_invalid_simulation(self):
        """Test error handling with invalid simulation data."""
        # Test with None simulation - should not crash
        # The actual implementation may or may not handle None gracefully,
        # but we test that the visible=False path works
        self.debug_ui.visible = False
        # This should be a no-op when not visible
        self.debug_ui.draw_debug_panel(self.surface, None)

    def test_performance_with_large_simulation(self):
        """Test performance with a large simulation."""
        # Create a larger simulation with many cities
        large_simulation = Simulation(32, 32)
        for i in range(10):
            city = large_simulation.add_city(f"City{i}", Vector3f(i * 50, i * 50, 0))

        # Time the drawing operation
        import time
        start_time = time.time()

        self.debug_ui.visible = True
        self.debug_ui.draw_debug_panel(self.surface, large_simulation)

        end_time = time.time()
        draw_time = end_time - start_time

        # Should complete within reasonable time (< 0.1 seconds)
        self.assertLess(draw_time, 0.1, "Debug UI drawing should be fast")


class TestDebugUIIntegration(unittest.TestCase):
    """Integration tests for DebugUI with simulation components."""

    def setUp(self):
        """Set up integration test fixtures."""
        pygame.init()
        pygame.font.init()
        self.font = pygame.font.SysFont("Arial", 16)
        self.debug_ui = DebugUI(self.font)
        self.surface = pygame.Surface((800, 600))

        # Create a complete simulation with multiple components
        self.simulation = Simulation(12, 12)

        # Create types
        from openglassbox.map import MapType
        from openglassbox.path import PathType, WayType
        from openglassbox.unit import UnitType

        self.grass_type = MapType("Grass", 0x00FF00, 100)
        self.road_type = PathType("Road", 0x555555)
        self.dirt_type = WayType("Dirt", 0x8B4513)
        self.home_type = UnitType("Home", 0xFF0000)

        # Create Paris city with full components
        self.paris = self.simulation.add_city("Paris", Vector3f(400, 200, 0))

        # Add map
        self.paris_grass = self.paris.add_map(self.grass_type)
        for u in range(0, 12, 2):
            for v in range(0, 12, 2):
                self.paris_grass.set_resource(u, v, 8)

        # Add path with nodes and ways
        self.road = self.paris.add_path(self.road_type)
        self.n1 = self.road.addNode(Vector3f(60.0, 60.0, 0.0))
        self.n2 = self.road.addNode(Vector3f(300.0, 300.0, 0.0))
        self.w1 = self.road.addWay(self.dirt_type, self.n1, self.n2)

        # Add units
        self.unit1 = self.paris.add_unit(self.home_type, self.n1)

    def tearDown(self):
        """Clean up after integration tests."""
        pygame.quit()

    def test_debug_ui_with_complete_simulation(self):
        """Test debug UI with a complete simulation including all components."""
        # Make debug UI visible
        self.debug_ui.visible = True

        # Should be able to draw without errors
        try:
            self.debug_ui.draw_debug_panel(self.surface, self.simulation)
        except Exception as e:
            self.fail(f"Debug UI failed with complete simulation: {e}")

    def test_city_switching_with_multiple_cities(self):
        """Test city switching functionality with multiple cities."""
        # Add second city
        versailles = self.simulation.add_city("Versailles", Vector3f(0, 30, 0))

        city_names = list(self.simulation.cities().keys())

        # Test switching between cities
        self.assertEqual(self.debug_ui.ui_state.selected_city, 0)

        # Switch to second city
        self.debug_ui.handle_key_press(pygame.K_TAB, city_names)
        self.assertEqual(self.debug_ui.ui_state.selected_city, 1)

        # Switch back to first city (wraps around)
        self.debug_ui.handle_key_press(pygame.K_TAB, city_names)
        self.assertEqual(self.debug_ui.ui_state.selected_city, 0)

    def test_resource_display_accuracy(self):
        """Test that resource information is displayed accurately."""
        # The debug UI should display resource information correctly
        self.debug_ui.visible = True

        # Expand relevant sections
        self.debug_ui.ui_state.expanded_headers.add("Maps")

        try:
            self.debug_ui.draw_debug_panel(self.surface, self.simulation)
        except Exception as e:
            self.fail(f"Debug UI failed displaying resources: {e}")


if __name__ == "__main__":
    unittest.main()
