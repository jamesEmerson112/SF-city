"""
Input and event handling for the OpenGlassBox demo.
Handles keyboard, mouse events, and restart functionality.
"""

import pygame
import os
import sys

class InputHandler:
    """Handles all input events and restart functionality for the demo."""
    
    def __init__(self, demo):
        """Initialize input handler with reference to the demo."""
        self.demo = demo
        
    def restart_simulation(self):
        """Restart the simulation from scratch."""
        print("🔄 RESTARTING SIMULATION...")
        
        # Reset demo state
        self.demo.camera_offset_x = 0
        self.demo.camera_offset_y = 0
        self.demo.zoom = 2.0
        self.demo.paused = True
        
        # Reinitialize simulation
        from openglassbox.simulation import Simulation
        self.demo.simulation = Simulation(12, 12)
        
        # Recreate city setup with new simulation
        from .city_setup import CitySetup
        self.demo.city_setup = CitySetup(self.demo.simulation)
        
        # Reload the same scenario file
        simfile = getattr(self.demo, 'current_simfile', None)
        if simfile:
            success = self.demo.city_setup.init_demo_cities(simfile)
            if success:
                print(f"✅ Successfully restarted with {simfile}")
            else:
                print(f"❌ Failed to restart with {simfile}")
        else:
            # No stored simfile, try defaults
            simfiles_to_try = [
                "demo/data/Simulations/TestCity.txt",
                "../data/Simulations/TestCity.txt", 
                "data/Simulations/TestCity.txt"
            ]
            
            success = False
            for simfile in simfiles_to_try:
                if os.path.exists(simfile):
                    success = self.demo.city_setup.init_demo_cities(simfile)
                    if success:
                        self.demo.current_simfile = simfile
                        print(f"✅ Successfully restarted with {simfile}")
                        break
            
            if not success:
                print("❌ Could not find TestCity.txt, creating default demo")
                self.demo.city_setup.init_demo_cities()
        
        # Re-setup simulation listeners
        self.demo.setup_listeners()
        
        print("🎮 Simulation restarted! Press P to play.")
    
    def handle_events(self):
        """Handle pygame events like keyboard and mouse input."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.demo.running = False

            elif event.type == pygame.VIDEORESIZE:
                # Handle window resize events
                self.demo.handle_window_resize(event.w, event.h)

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.demo.running = False
                elif event.key == pygame.K_p:
                    self.demo.paused = not self.demo.paused
                    print(f"Simulation {'paused' if self.demo.paused else 'resumed'}")
                elif event.key == pygame.K_d:
                    self.demo.show_debug = not self.demo.show_debug
                elif event.key == pygame.K_i:
                    # Toggle color details panel
                    self.demo.show_color_details = not self.demo.show_color_details
                    if self.demo.show_color_details:
                        print("🎨 Color details panel enabled - shows entity colors!")
                    else:
                        print("📊 Color details panel disabled")
                elif event.key == pygame.K_c:
                    # Toggle comprehensive debug panel
                    self.demo.show_comprehensive_debug = not self.demo.show_comprehensive_debug
                    if self.demo.show_comprehensive_debug:
                        print("🔬 Comprehensive debug panel enabled - detailed simulation introspection!")
                    else:
                        print("📋 Comprehensive debug panel disabled")
                elif event.key == pygame.K_t:
                    self.demo.show_tick_counter = not self.demo.show_tick_counter
                elif event.key == pygame.K_m:
                    self.demo.show_maps = not self.demo.show_maps
                elif event.key == pygame.K_l:
                    self.demo.show_paths = not self.demo.show_paths
                elif event.key == pygame.K_u:
                    self.demo.show_units = not self.demo.show_units
                elif event.key == pygame.K_a:
                    self.demo.show_agents = not self.demo.show_agents
                elif event.key == pygame.K_r:
                    # Reset view
                    self.demo.camera_offset_x = 0
                    self.demo.camera_offset_y = 0
                    self.demo.zoom = 2.0
                    print("🎯 View reset")
                elif event.key == pygame.K_F5 or (event.key == pygame.K_r and pygame.key.get_pressed()[pygame.K_LCTRL]):
                    # F5 or Ctrl+R for restart
                    self.restart_simulation()
                elif event.key == pygame.K_F11:
                    # F11 for fullscreen toggle
                    self.demo.toggle_fullscreen()
                elif event.key == pygame.K_RETURN and (pygame.key.get_pressed()[pygame.K_LALT] or pygame.key.get_pressed()[pygame.K_RALT]):
                    # Alt+Enter for fullscreen toggle (alternative binding)
                    self.demo.toggle_fullscreen()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left mouse button
                    # Handle mouse clicks
                    self.demo.handle_mouse_click(event.pos)
                    
                    self.demo.dragging = True
                    self.demo.last_mouse_x, self.demo.last_mouse_y = event.pos
                elif event.button == 4:  # Mouse wheel up
                    self.demo.zoom *= 1.1
                elif event.button == 5:  # Mouse wheel down
                    self.demo.zoom /= 1.1

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:  # Left mouse button
                    self.demo.dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if self.demo.dragging:
                    dx = event.pos[0] - self.demo.last_mouse_x
                    dy = event.pos[1] - self.demo.last_mouse_y
                    self.demo.camera_offset_x += dx
                    self.demo.camera_offset_y += dy
                    self.demo.last_mouse_x, self.demo.last_mouse_y = event.pos
