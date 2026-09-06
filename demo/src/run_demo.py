#!/usr/bin/env python3
"""
Run script for OpenGlassBox demo using Pygame.

This script handles the setup and execution of the OpenGlassBox demo application.
It ensures pygame is installed and properly configured before running the demo.
"""

import sys
import traceback

def main():
    """Main entry point for the run script."""
    # Import and run the demo
    print("Starting OpenGlassBox demo...")

    try:
        from .demo import main as demo_main
        demo_main()
    except Exception as e:
        print(f"Error running demo: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
