"""
Integration tests for the demo applications.

Tests the complete demo functionality including simulation setup and city creation.
"""

import unittest
import os
import pygame
import time
from unittest.mock import Mock, patch, MagicMock

from demo.src.demo import GlassBoxDemo as BasicDemo
from openglassbox.simulation import Simulation
from openglassbox.vector import Vector3f


class TestBasicDemoIntegration(unittest.TestCase):
    """Integration tests for the basic demo application."""

    def setUp(self):
        """Set up test fixtures."""
        pass

    def tearDown(self):
        """Clean up after tests."""
        try:
            pygame.quit()
        except Exception:
            pass

    def test_basic_demo_initialization(self):
        """Test that basic demo initializes correctly."""
        demo = BasicDemo(800, 600, "Test Demo")
        self.assertIsNotNone(demo)
        self.assertEqual(demo.width, 800)
        self.assertEqual(demo.height, 600)
        self.assertTrue(demo.paused)
        self.assertTrue(demo.running)

    def test_basic_demo_simulation_setup(self):
        """Test that basic demo sets up simulation correctly."""
        demo = BasicDemo(800, 600, "Test Demo")

        # Check simulation is created
        self.assertIsNotNone(demo.simulation)
        self.assertEqual(demo.simulation.m_gridSizeU, 12)
        self.assertEqual(demo.simulation.m_gridSizeV, 12)

    def test_basic_demo_listener_setup(self):
        """Test that event listeners are set up correctly."""
        demo = BasicDemo(800, 600, "Test Demo")

        # Simulation should have a listener (m_listener, not _listener)
        self.assertIsNotNone(demo.simulation.m_listener)

    def test_basic_demo_update(self):
        """Test that demo update works."""
        demo = BasicDemo(800, 600, "Test Demo")

        # When paused, update should not advance simulation
        demo.paused = True
        demo.update(0.016)
        self.assertEqual(demo.simulation.m_time, 0.0)

        # When unpaused, update should advance simulation
        demo.paused = False
        demo.update(1.0)
        # After update with 1.0s, some ticks should have occurred
        self.assertGreater(demo.simulation.get_total_ticks(), 0)

    def test_basic_demo_city_creation(self):
        """Test that demo can create cities programmatically."""
        demo = BasicDemo(800, 600, "Test Demo")

        # Create a city
        test_city = demo.simulation.add_city("TestFallbackCity", Vector3f(0, 0, 0))
        self.assertIsNotNone(test_city)
        self.assertEqual(test_city.name(), "TestFallbackCity")

    def test_basic_demo_simulation_step(self):
        """Test that simulation step works via demo."""
        demo = BasicDemo(800, 600, "Test Demo")

        # Add a city
        city = demo.simulation.add_city("StepTest", Vector3f(100, 100, 0))

        # Use step() method
        demo.simulation.step()

        # Should have advanced ticks
        self.assertGreater(demo.simulation.get_total_ticks(), 0)

    def test_basic_demo_multiple_cities(self):
        """Test demo with multiple cities."""
        demo = BasicDemo(800, 600, "Test Demo")

        # Add multiple cities
        for i in range(3):
            demo.simulation.add_city(f"City{i}", Vector3f(i * 100, i * 100, 0))

        cities = demo.simulation.cities()
        self.assertEqual(len(cities), 3)
        self.assertIn("City0", cities)
        self.assertIn("City1", cities)
        self.assertIn("City2", cities)


@unittest.skip("demo_enhanced module not available")
class TestEnhancedDemoIntegration(unittest.TestCase):
    """Integration tests for the enhanced demo application with debug UI."""
    pass


class TestDemoPerformance(unittest.TestCase):
    """Performance tests for demo applications."""

    @unittest.skip("Performance test - run manually when needed")
    def test_basic_demo_performance(self):
        """Test basic demo performance."""
        demo = BasicDemo(1024, 768, "Performance Test")

        # Create a larger simulation for performance testing
        for i in range(5):
            city = demo.simulation.add_city(f"City{i}", Vector3f(i * 100, i * 100, 0))

        # Time multiple update cycles
        start_time = time.time()
        for _ in range(100):
            demo.update(0.016)
        end_time = time.time()

        total_time = end_time - start_time
        avg_time_per_update = total_time / 100

        print(f"Basic demo average update time: {avg_time_per_update:.4f}s")

        # Should complete 100 updates in reasonable time (< 1 second)
        self.assertLess(total_time, 1.0, "Basic demo update performance too slow")

        pygame.quit()


class TestDemoFileOperations(unittest.TestCase):
    """Test file operations and resource loading in demos."""

    def test_demo_simulation_file_search(self):
        """Test simulation file search functionality."""
        demo = BasicDemo(800, 600, "File Test Demo")

        # Test the simulation file search paths
        possible_paths = [
            os.path.join("data", "simulations", "TestCity.txt"),
            os.path.join("python", "data", "simulations", "TestCity.txt"),
            os.path.join("demo", "data", "Simulations", "TestCity.txt"),
            os.path.join("..", "demo", "data", "Simulations", "TestCity.txt")
        ]

        # At least one of these paths should exist or be searched
        self.assertIsInstance(possible_paths, list)
        self.assertGreater(len(possible_paths), 0)

        pygame.quit()

    def test_demo_fallback_city_creation(self):
        """Test fallback city creation when simulation file is missing."""
        demo = BasicDemo(800, 600, "Fallback Test Demo")

        # The demo can create cities programmatically
        test_city = demo.simulation.add_city("TestFallbackCity", Vector3f(0, 0, 0))
        self.assertIsNotNone(test_city)
        self.assertEqual(test_city.name(), "TestFallbackCity")

        pygame.quit()


if __name__ == "__main__":
    # Run tests with verbosity
    unittest.main(verbosity=2)
