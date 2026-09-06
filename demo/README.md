# OpenGlassBox Python Demo

This directory contains the Python implementation of the OpenGlassBox demo, mirroring the functionality of the C++ demo in the root `demo/` directory.

## Directory Structure

```
python/demo/
├── data/
│   ├── Fonts/             # Font assets for UI
│   └── Simulations/       # Simulation definition files
│       ├── TestCity.txt
│       └── TestCity1.txt
└── src/
    ├── Display/           # UI and display related code
    │   └── debug_ui.py    # Debug UI implementation
    ├── demo.py            # Basic demo implementation
    ├── demo_enhanced.py   # Enhanced demo with debug UI
    ├── main.py            # Main entry point (mirrors C++ main.cpp)
    └── run_demo.py        # Setup utility script
```

## Running the Demo

### Primary Entry Point (Recommended)

Use `main.py` as the main entry point - this mirrors the C++ architectural pattern:

```bash
cd python

# Run basic demo
python demo/src/main.py

# Run enhanced demo with debug UI
python demo/src/main.py --enhanced

# Load custom simulation file
python demo/src/main.py --simulation MyCity.txt
```

### Alternative Setup Script

If you need to install dependencies or troubleshoot:

```bash
# Setup script that auto-installs pygame if needed
python demo/src/run_demo.py
```

## Demo Variants

- **Basic Demo** (`demo.py`): Simple visualization with basic debug overlay
- **Enhanced Demo** (`demo_enhanced.py`): Advanced Dear ImGui-style debug interface

## Controls

- **SPACE**: Pause/unpause simulation
- **D**: Toggle debug panel (matches C++ 'D' key)
- **M/P/U/A**: Toggle Maps/Paths/Units/Agents display
- **R**: Reset camera view
- **Mouse wheel**: Zoom in/out
- **Mouse drag**: Pan camera
- **ESC**: Exit demo

## Architecture

This Python demo follows the same architectural pattern as the C++ version:

- **C++**: `main.cpp` (entry point) + `Demo.cpp` (content)
- **Python**: `main.py` (entry point) + `demo.py`/`demo_enhanced.py` (content)

The demo creates the same simulation scenarios as the C++ version, including Paris and Versailles cities with identical layouts, units, and agents.
