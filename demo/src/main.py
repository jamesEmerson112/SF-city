#!/usr/bin/env python3
"""
Main entry point for the OpenGlassBox Python demo.
This file mirrors the functionality of demo/src/main.cpp in the C++ implementation.
"""

import sys
import os
import argparse

def main():
    """Main entry point for the OpenGlassBox demo."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='OpenGlassBox Simulation Demo')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging for agents and other components')
    parser.add_argument('--no-record', action='store_true',
                        help='Disable recording simulation state to a JSON file')
    args = parser.parse_args()

    # Set global debug flag
    if args.debug:
        os.environ['OPENGLASSBOX_DEBUG'] = '1'
        print("🐛 Debug mode enabled - agent debug logging activated")

    # Set up paths
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Import the demo using relative import
    print("Starting OpenGlassBox Demo...")
    from .demo import GlassBoxDemo

    # Create the demo object
    record = not args.no_record
    demo = GlassBoxDemo(1024, 768, "OpenGlassBox Simulation", record=record)

    # Try to initialize with TestCity.txt using absolute path
    simfile = os.path.abspath(os.path.join(script_dir, "../data/Simulations/TestCity.txt"))
    print(f"Attempting to initialize simulation with {simfile}")
    if not demo.init_demo_cities(simfile):
        print(f"Failed to initialize simulation with {simfile}")
        print("Exiting (no fallback to hardcoded setup).")
        sys.exit(1)

    # Set up recording after cities are initialised
    if record:
        from .session_recorder import SessionRecorder
        demo.recorder = SessionRecorder(demo.simulation, simfile)
        demo.recorder.attach_to_cities()
        print("Recording enabled - session will be saved on exit")

    # Run the demo
    demo.run()


if __name__ == "__main__":
    main()
