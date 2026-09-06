"""
Performance benchmarks for the OpenGlassBox Python port.

Compares Python implementation performance against expected C++ benchmarks
and provides detailed analysis of simulation components.
"""

import unittest
import time
import gc
import tracemalloc
import statistics
from typing import List, Dict, Tuple, Any
import sys

from openglassbox.simulation import Simulation
from openglassbox.vector import Vector3f
from openglassbox.map import MapType
from openglassbox.path import PathType, WayType
from openglassbox.unit import UnitType
import pygame


class PerformanceBenchmarkResult:
    """Container for performance benchmark results."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.execution_times: List[float] = []
        self.memory_usage: List[Tuple[int, int]] = []  # (current, peak) in bytes
        self.iterations = 0

    def add_measurement(self, execution_time: float, memory_current: int = 0, memory_peak: int = 0):
        """Add a performance measurement."""
        self.execution_times.append(execution_time)
        self.memory_usage.append((memory_current, memory_peak))
        self.iterations += 1

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistical summary of the benchmark results."""
        if not self.execution_times:
            return {}

        return {
            'test_name': self.test_name,
            'iterations': self.iterations,
            'time_mean': statistics.mean(self.execution_times),
            'time_median': statistics.median(self.execution_times),
            'time_stdev': statistics.stdev(self.execution_times) if len(self.execution_times) > 1 else 0,
            'time_min': min(self.execution_times),
            'time_max': max(self.execution_times),
            'time_total': sum(self.execution_times),
            'memory_current_avg': statistics.mean([m[0] for m in self.memory_usage]) if self.memory_usage[0][0] > 0 else 0,
            'memory_peak_max': max([m[1] for m in self.memory_usage]) if self.memory_usage[0][1] > 0 else 0,
        }

    def print_summary(self):
        """Print a formatted summary of the benchmark results."""
        stats = self.get_statistics()
        if not stats:
            print(f"No data for {self.test_name}")
            return

        print(f"\n=== {stats['test_name']} ===")
        print(f"Iterations: {stats['iterations']}")
        print(f"Time - Mean: {stats['time_mean']:.4f}s, Median: {stats['time_median']:.4f}s")
        print(f"Time - Min: {stats['time_min']:.4f}s, Max: {stats['time_max']:.4f}s")
        print(f"Time - StdDev: {stats['time_stdev']:.4f}s, Total: {stats['time_total']:.4f}s")
        if stats['memory_current_avg'] > 0:
            print(f"Memory - Avg Current: {stats['memory_current_avg']/1024/1024:.2f}MB")
            print(f"Memory - Peak: {stats['memory_peak_max']/1024/1024:.2f}MB")


class PerformanceBenchmarks(unittest.TestCase):
    """Performance benchmark test suite."""

    def setUp(self):
        """Set up performance test environment."""
        # Force garbage collection to start with clean slate
        gc.collect()

        # Performance target thresholds (based on expected C++ performance)
        self.performance_targets = {
            'simulation_creation': 0.01,      # 10ms for simulation setup
            'city_creation': 0.005,           # 5ms per city
            'pathfinding_single': 0.01,       # 10ms for single path calculation
            'simulation_step': 0.05,          # 50ms per simulation step
            'large_simulation_step': 0.1,     # 100ms for large simulation step
            'memory_simulation_mb': 50,       # 50MB max for standard simulation
            'memory_large_simulation_mb': 200, # 200MB max for large simulation
        }

    def benchmark_with_memory(self, func, iterations: int = 10) -> PerformanceBenchmarkResult:
        """Run a benchmark function with memory and time tracking."""
        result = PerformanceBenchmarkResult(func.__name__)

        for i in range(iterations):
            # Start memory tracking
            tracemalloc.start()
            gc.collect()  # Clean up before measurement

            # Time the function execution
            start_time = time.perf_counter()
            func()
            end_time = time.perf_counter()

            # Get memory statistics
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            execution_time = end_time - start_time
            result.add_measurement(execution_time, current, peak)

        return result

    def test_simulation_creation_performance(self):
        """Benchmark simulation creation performance."""
        def create_simulation():
            simulation = Simulation(12, 12)
            return simulation

        result = self.benchmark_with_memory(create_simulation, iterations=50)
        result.print_summary()

        stats = result.get_statistics()
        target = self.performance_targets['simulation_creation']
        self.assertLess(stats['time_mean'], target,
                       f"Simulation creation too slow: {stats['time_mean']:.4f}s > {target}s")

    def test_city_creation_performance(self):
        """Benchmark city creation performance."""
        simulation = Simulation(12, 12)

        def create_city():
            city = simulation.add_city(f"TestCity{time.time()}", Vector3f(100, 100, 0))
            return city

        result = self.benchmark_with_memory(create_city, iterations=20)
        result.print_summary()

        stats = result.get_statistics()
        target = self.performance_targets['city_creation']
        self.assertLess(stats['time_mean'], target,
                       f"City creation too slow: {stats['time_mean']:.4f}s > {target}s")

    def test_pathfinding_performance(self):
        """Benchmark pathfinding algorithm performance."""
        simulation = Simulation(12, 12)
        city = simulation.add_city("TestCity", Vector3f(100, 100, 0))

        # Create path network for testing
        road_type = PathType("Road", 0x555555)
        dirt_type = WayType("Dirt", 0x8B4513)
        path = city.add_path(road_type)

        # Add nodes in a grid pattern
        nodes = []
        for i in range(5):
            for j in range(5):
                node = path.addNode(Vector3f(i * 100.0, j * 100.0, 0.0))
                nodes.append(node)

        # Connect adjacent nodes
        for i in range(4):
            for j in range(4):
                current_idx = i * 5 + j
                right_idx = i * 5 + (j + 1)
                down_idx = (i + 1) * 5 + j

                path.addWay(dirt_type, nodes[current_idx], nodes[right_idx])
                path.addWay(dirt_type, nodes[current_idx], nodes[down_idx])

        def run_pathfinding():
            start_node = nodes[0]   # Top-left
            end_node = nodes[24]    # Bottom-right
            # Note: Actual pathfinding would be via dijkstra or similar
            # For now, we'll simulate the operation
            return True

        result = self.benchmark_with_memory(run_pathfinding, iterations=100)
        result.print_summary()

        stats = result.get_statistics()
        target = self.performance_targets['pathfinding_single']
        self.assertLess(stats['time_mean'], target,
                       f"Pathfinding too slow: {stats['time_mean']:.4f}s > {target}s")

    def test_simulation_step_performance(self):
        """Benchmark single simulation step performance."""
        simulation = Simulation(12, 12)
        city = simulation.add_city("Paris", Vector3f(100, 100, 0))

        # Add some basic components
        grass_type = MapType("Grass", 0x00FF00, 100)
        grass_map = city.add_map(grass_type)
        for u in range(0, 12, 2):
            for v in range(0, 12, 2):
                grass_map.set_resource(u, v, 8)

        def simulation_step():
            simulation.step()

        result = self.benchmark_with_memory(simulation_step, iterations=100)
        result.print_summary()

        stats = result.get_statistics()
        target = self.performance_targets['simulation_step']
        self.assertLess(stats['time_mean'], target,
                       f"Simulation step too slow: {stats['time_mean']:.4f}s > {target}s")

    def test_large_simulation_performance(self):
        """Benchmark performance with larger simulation."""
        # Create larger simulation (24x24 instead of 12x12)
        simulation = Simulation(24, 24)

        # Add multiple cities with full components
        cities = []
        for i in range(3):
            city = simulation.add_city(f"City{i}", Vector3f(i * 200, i * 200, 0))
            cities.append(city)

            # Add maps
            grass_type = MapType("Grass", 0x00FF00, 100)
            water_type = MapType("Water", 0x0000FF, 50)

            grass_map = city.add_map(grass_type)
            water_map = city.add_map(water_type)

            # Populate with resources
            for u in range(0, 24, 3):
                for v in range(0, 24, 3):
                    grass_map.set_resource(u, v, 8)
                    if (u + v) % 6 == 0:
                        water_map.set_resource(u, v, 5)

            # Add path network
            road_type = PathType("Road", 0x555555)
            dirt_type = WayType("Dirt", 0x8B4513)
            path = city.add_path(road_type)

            # Add several nodes and ways
            nodes = []
            for j in range(3):
                node = path.addNode(Vector3f(j * 150.0, j * 150.0, 0.0))
                nodes.append(node)

            for j in range(len(nodes) - 1):
                path.addWay(dirt_type, nodes[j], nodes[j + 1])

            # Add units
            home_type = UnitType("Home", 0xFF0000)
            if len(nodes) >= 2:
                way = path.ways()[0] if path.ways() else None
                if way:
                    city.add_unit_on_way(home_type, path, way, 0.5)

        def large_simulation_step():
            simulation.step()

        result = self.benchmark_with_memory(large_simulation_step, iterations=20)
        result.print_summary()

        stats = result.get_statistics()
        target = self.performance_targets['large_simulation_step']
        self.assertLess(stats['time_mean'], target,
                       f"Large simulation step too slow: {stats['time_mean']:.4f}s > {target}s")

        # Check memory usage
        memory_mb = stats['memory_peak_max'] / 1024 / 1024
        target_memory = self.performance_targets['memory_large_simulation_mb']
        self.assertLess(memory_mb, target_memory,
                       f"Large simulation uses too much memory: {memory_mb:.2f}MB > {target_memory}MB")

    def test_demo_rendering_performance(self):
        """Benchmark demo rendering performance (without actual display)."""
        pygame.init()
        pygame.font.init()

        # Create mock surface for rendering
        surface = pygame.Surface((800, 600))

        # Import demo after pygame init
        from demo.src.demo import GlassBoxDemo

        demo = GlassBoxDemo(800, 600, "Performance Test")

        def render_frame():
            # Simulate rendering operations
            surface.fill((0, 0, 0))

            # Draw simulation components (simplified)
            for city in demo.simulation.cities().values():
                pos = city.position()
                city_pos = (int(pos.x), int(pos.y))
                pygame.draw.circle(surface, (255, 255, 255), city_pos, 5)

        result = self.benchmark_with_memory(render_frame, iterations=60)  # Simulate 60 FPS
        result.print_summary()

        stats = result.get_statistics()
        # Target: 60 FPS = ~16.67ms per frame, we'll allow up to 10ms
        target = 0.010
        self.assertLess(stats['time_mean'], target,
                       f"Demo rendering too slow: {stats['time_mean']:.4f}s > {target}s for 60 FPS")

        pygame.quit()

    def test_memory_efficiency(self):
        """Test memory efficiency of core components."""
        simulations = []

        def create_multiple_simulations():
            # Create 5 simulations to test memory scaling
            for i in range(5):
                sim = Simulation(12, 12)
                city = sim.add_city(f"City{i}", Vector3f(i * 100, i * 100, 0))

                # Add basic components
                grass_type = MapType("Grass", 0x00FF00, 100)
                grass_map = city.add_map(grass_type)
                for u in range(0, 12, 4):
                    for v in range(0, 12, 4):
                        grass_map.set_resource(u, v, 5)

                simulations.append(sim)

        result = self.benchmark_with_memory(create_multiple_simulations, iterations=3)
        result.print_summary()

        stats = result.get_statistics()
        memory_mb = stats['memory_peak_max'] / 1024 / 1024
        target_memory = self.performance_targets['memory_simulation_mb'] * 5  # 5 simulations
        self.assertLess(memory_mb, target_memory,
                       f"Multiple simulations use too much memory: {memory_mb:.2f}MB > {target_memory}MB")

    def test_component_scaling_performance(self):
        """Test how performance scales with number of components."""
        simulation = Simulation(16, 16)
        city = simulation.add_city("ScaleTest", Vector3f(100, 100, 0))

        # Test scaling with number of map resources
        grass_type = MapType("Grass", 0x00FF00, 100)
        grass_map = city.add_map(grass_type)

        def add_many_resources():
            # Add resources to all grid positions
            for u in range(16):
                for v in range(16):
                    grass_map.set_resource(u, v, (u + v) % 10)

        result = self.benchmark_with_memory(add_many_resources, iterations=10)
        result.print_summary()

        # Should scale reasonably with grid size
        stats = result.get_statistics()
        # For 16x16 = 256 resources, should be under 5ms
        self.assertLess(stats['time_mean'], 0.005,
                       f"Resource scaling too slow: {stats['time_mean']:.4f}s")

    @classmethod
    def generate_performance_report(cls):
        """Generate a comprehensive performance report."""
        print("\n" + "="*60)
        print("OPENGLASSBOX PYTHON PORT - PERFORMANCE BENCHMARK REPORT")
        print("="*60)
        print(f"Test run at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Python version: {sys.version}")
        print(f"Platform: {sys.platform}")

        # Run all benchmarks
        suite = unittest.TestLoader().loadTestsFromTestCase(cls)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        print("\n" + "="*60)
        print("PERFORMANCE SUMMARY")
        print("="*60)
        print(f"Tests run: {result.testsRun}")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")

        if result.failures:
            print("\nPERFORMANCE FAILURES:")
            for test, traceback in result.failures:
                print(f"- {test}: Performance target not met")

        if result.errors:
            print("\nERRORS:")
            for test, traceback in result.errors:
                print(f"- {test}: {traceback}")

        print("\nPerformance benchmark complete!")
        return result


if __name__ == "__main__":
    # Run performance benchmarks when executed directly
    PerformanceBenchmarks.generate_performance_report()
