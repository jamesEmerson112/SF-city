"""
Coordinate system utilities for the UI renderer.
"""
from typing import Tuple

class CoordinateSystem:
    """Handles world-to-screen coordinate conversions."""
    
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
    
    def world_to_screen(self, world_x: float, world_y: float, zoom: float, 
                       camera_offset_x: float, camera_offset_y: float) -> Tuple[int, int]:
        """Convert world coordinates to screen coordinates."""
        screen_x = int((world_x * zoom) + self.width / 2 + camera_offset_x)
        screen_y = int((world_y * zoom) + self.height / 2 + camera_offset_y)
        return (screen_x, screen_y)
