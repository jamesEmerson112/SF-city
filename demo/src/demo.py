"""
Simplified OpenGlassBox Demo Application.

This is the main demo application that shows how the simulation works
with a visual interface. It loads scenario files and runs the simulation
with real-time visualization.
"""

import os
import sys
import time
import pygame
from typing import Dict, List, Optional, Tuple

# Import from the openglassbox package
from openglassbox.simulation import Simulation
from openglassbox.city import City
from openglassbox.script_parser import Script

# Import our modules using relative imports
from .ui_renderer import UIRenderer
from .city_setup import CitySetup
from .input_handler import InputHandler

class GlassBoxDemo:
    """
    Main demo application for visualizing OpenGlassBox simulations.

    This class handles the main game loop, user input, and coordinates
    between the simulation engine and the UI renderer.
    """

    def __init__(self, width: int = 800, height: int = 600, title: str = "OpenGlassBox Demo", record: bool = False):
        """Initialize the demo application."""
        pygame.init()
        self.width = width
        self.height = height
        self.title = title
        
        # Fullscreen support
        self.fullscreen = False
        self.windowed_width = width
        self.windowed_height = height
        
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        self.running = True
        self.paused = True  # Start paused to show instructions

        # Simulation components
        self.simulation = Simulation(12, 12)  # 12x12 grid like C++ demo
        self.script_parser = Script()

        # Rendering and setup modules
        self.ui_renderer = UIRenderer(width, height)
        self.city_setup = CitySetup(self.simulation)

        # Input handling
        self.input_handler = InputHandler(self)

        # Store simulation file for restart functionality
        self.current_simfile = None

        # Recording support (recorder is set externally by main.py)
        self.recording = record
        self.recorder = None

        # Camera/view settings
        self.camera_offset_x = 0
        self.camera_offset_y = 0
        self.zoom = 2.0

        # Debug flags
        self.show_debug = True
        self.show_color_details = False  # Toggle for color details panel
        self.show_comprehensive_debug = False  # Toggle for comprehensive debug panel
        self.show_tick_counter = True  # Show tick counter by default
        self.show_maps = True
        self.show_paths = True
        self.show_units = True
        self.show_agents = True

        # Input state
        self.dragging = False
        self.last_mouse_x = 0
        self.last_mouse_y = 0

        # Set up simulation listeners
        self.setup_listeners()

    def setup_listeners(self):
        """Set up event listeners for simulation components."""
        # Simple simulation listener
        class SimulationListener(Simulation.Listener):
            def __init__(self, demo):
                super().__init__()
                self.demo = demo

            def on_city_added(self, city):
                print(f"City {city.name()} added")

            def on_city_removed(self, city):
                print(f"City {city.name()} removed")

        self.simulation.set_listener(SimulationListener(self))

    def init_demo_cities(self, simfile=None):
        """Initialize demo cities using the CitySetup module."""
        # Store the simfile for restart functionality
        if simfile:
            self.current_simfile = simfile

        return self.city_setup.init_demo_cities(simfile)

    def handle_mouse_click(self, pos: Tuple[int, int]):
        """Handle mouse clicks."""
        pass

    def handle_window_resize(self, new_width: int, new_height: int):
        """Handle window resize events."""
        self.width = new_width
        self.height = new_height
        
        # Update the screen surface to the new size
        if self.fullscreen:
            self.screen = pygame.display.set_mode((new_width, new_height), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode((new_width, new_height), pygame.RESIZABLE)
            # Update windowed dimensions for toggling back from fullscreen
            self.windowed_width = new_width
            self.windowed_height = new_height
        
        pygame.display.set_caption(self.title)
        
        # Update UI renderer with new dimensions
        self.ui_renderer = UIRenderer(self.width, self.height)
        
        print(f"📏 Window resized to {new_width}x{new_height}")

    def toggle_fullscreen(self):
        """Toggle between fullscreen and windowed mode."""
        if self.fullscreen:
            # Switch to windowed mode
            self.screen = pygame.display.set_mode((self.windowed_width, self.windowed_height), pygame.RESIZABLE)
            self.width = self.windowed_width
            self.height = self.windowed_height
            self.fullscreen = False
            print("🗖 Switched to windowed mode")
        else:
            # Switch to fullscreen mode
            # Get the current display info to use native resolution
            display_info = pygame.display.Info()
            fullscreen_width = display_info.current_w
            fullscreen_height = display_info.current_h
            
            self.screen = pygame.display.set_mode((fullscreen_width, fullscreen_height), pygame.FULLSCREEN)
            self.width = fullscreen_width
            self.height = fullscreen_height
            self.fullscreen = True
            print(f"🖵 Switched to fullscreen mode ({fullscreen_width}x{fullscreen_height})")
        
        pygame.display.set_caption(self.title)
        
        # Update UI renderer with new dimensions
        self.ui_renderer = UIRenderer(self.width, self.height)

    def update(self, dt: float):
        """
        Update simulation state.

        This is the key method where the simulation progresses.
        The dt (delta time) controls how fast the simulation runs.
        """
        if not self.paused:
            # This is where the simulation actually updates!
            # The simulation.update() method should increment ticks
            # and run all the rules that move agents, update resources, etc.
            self.simulation.update(dt)

            if self.recording and self.recorder is not None:
                self.recorder.capture_tick()

    def render(self):
        """Render the current simulation state."""
        # Clear screen with dark blue background
        self.screen.fill((50, 50, 100))

        if self.paused:
            # Show instructions when paused
            self.ui_renderer.draw_instructions(self.screen)
        else:
            # Draw the game world when running
            self.ui_renderer.draw_grid(self.screen)

            # Draw all cities using the UI renderer
            for city_name, city in self.simulation.cities().items():
                self.ui_renderer.draw_city(
                    city, self.screen, self.zoom,
                    self.camera_offset_x, self.camera_offset_y,
                    self.show_maps, self.show_paths, self.show_units, self.show_agents
                )

        # Draw UI elements on top
        fps = int(self.clock.get_fps())
        self.ui_renderer.draw_status(self.screen, self.paused, fps)

        # Draw tick counter (this shows how many simulation steps have happened)
        tick_count = self.simulation.get_total_ticks()
        self.ui_renderer.draw_tick_counter(self.screen, tick_count, self.show_tick_counter)

        # Draw debug panel if enabled
        if self.show_debug:
            debug_options = {
                "Show Tick Counter": self.show_tick_counter,
                "Show Maps": self.show_maps,
                "Show Paths": self.show_paths,
                "Show Units": self.show_units,
                "Show Agents": self.show_agents
            }
            self.ui_renderer.draw_debug_panel(
                self.screen, debug_options,
                self.camera_offset_x, self.camera_offset_y, self.zoom
            )

        # Draw color details panel if enabled
        if self.show_color_details:
            self.ui_renderer.draw_color_details_panel(self.screen, self.simulation)

        # Draw comprehensive debug panel if enabled
        if self.show_comprehensive_debug:
            self.ui_renderer.draw_comprehensive_debug_panel(self.screen, self.simulation)

        # Flip display
        pygame.display.flip()

    def run(self):
        """
        Main game loop - this is the heart of the application.

        This method runs continuously until the user quits:
        1. Handle user input events
        2. Update the simulation state (if not paused)
        3. Render the current state to screen
        4. Control frame rate
        """
        print("Starting demo game loop...")
        print("🎮 CONTROLS:")
        print("  P = Pause/Resume")
        print("  F5 or Ctrl+R = RESTART SIMULATION")
        print("  R = Reset View")
        print("  D = Toggle Simple Debug Panel")
        print("  I = Toggle Color Details Panel")
        print("  C = Toggle Comprehensive Debug Panel")
        print("  ESC = Quit")
        print("📏 WINDOW: Drag corners to resize or use maximize button")

        # Target 60 FPS for smooth animation
        target_fps = 60

        while self.running:
            # Calculate delta time for smooth simulation updates
            dt = self.clock.tick(target_fps) / 1000.0  # Convert to seconds

            # Handle all user input using the InputHandler
            self.input_handler.handle_events()

            # Update simulation state (this increments ticks and runs rules)
            self.update(dt)

            # Render everything to screen
            self.render()

        # Save recording if enabled
        if self.recording and self.recorder is not None:
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "../data/recordings"
            )
            filepath = self.recorder.save(output_dir)
            print(f"Session recorded to {filepath}")

        # Clean up
        pygame.quit()
        print("Demo terminated")


def main():
    """
    Main entry point for the demo application.

    This sets up the demo, loads the scenario file, and starts the game loop.
    """
    print("OpenGlassBox Demo Starting...")

    # Create demo instance
    demo = GlassBoxDemo(800, 600, "OpenGlassBox Simulation Demo")

    # Try to load TestCity scenario using absolute path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    simfile = os.path.abspath(os.path.join(script_dir, "../data/Simulations/TestCity.txt"))
    if os.path.exists(simfile):
        print(f"Loading scenario: {simfile}")
        if not demo.init_demo_cities(simfile):
            print("Failed to load scenario, exiting...")
            return
    else:
        print(f"Scenario file not found: {simfile}")
        print("Creating default demo cities...")
        if not demo.init_demo_cities():
            print("Failed to create demo cities, exiting...")
            return

    # Start the main game loop
    demo.run()


if __name__ == "__main__":
    main()
