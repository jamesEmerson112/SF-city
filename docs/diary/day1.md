# Porting OpenGlassBox to Python – Integrated Plan

---

## 🚩 Todo List for Porting to Python

- [x] **1. Preparation & Scoping**
  - [x] Review C++ classes, relationships, and simulation flow
  - [x] Identify all core modules to port
  - [x] Set up `python/` directory and initialize a Python virtual environment
  - [x] Choose and configure a test framework (e.g., `pytest`)
  - [x] Plan to use modern Python tools (`dataclasses`, `typing`, etc.)

- [ ] **2. Iterative Porting (Repeat for Each Module)**
  - **C++ test files to port (in order):**
    - [x] TestsResource.cpp
    - [x] TestsAgent.cpp
    - [x] TestsCity.cpp
    - [x] TestsCommand.cpp
    - [x] TestsCoordInsideRadius.cpp
    - [x] TestsMap.cpp
    - [x] TestsPath.cpp
    - [x] TestsResources.cpp
    - [x] TestsScriptParser.cpp
    - [x] TestsSimulation.cpp
    - [x] TestsUnit.cpp
    - [x] TestsValue.cpp
  - **All C++ test files have been ported to Python.**
  - **Each Python test file includes a descriptive docstring summarizing its coverage and purpose.**
  - **A test runner script (`python/tests/test_all.py`) is provided to run all tests at once.**
  - **All tests are passing, and the Python port mirrors the C++ test suite in a test-driven manner.**

- [x] **3. Module Implementation Checklist**
  - [x] **Data Classes & Utilities**
    - [x] **Resource** (Resource.hpp/cpp → resource.py)
      - [x] Implement `Resource` class with proper type hints
      - [x] Ensure proper initialization with name and value
      - [x] Implement methods for modification and query (`Clone`, `Equals`, `ToString`)
      - [x] Add Python-specific utility methods and properties
      - [x] Complete type hints for all methods and properties
      - [x] Add comprehensive docstrings

    - [x] **RuleValue** (RuleValue.hpp/cpp → rule_value.py)
      - [x] Port `RuleValue` class with type annotations
      - [x] Implement different value types (constants, variables, operations)
      - [x] Add evaluation methods
      - [x] Implement ToString() and other debug utilities
      - [x] Add proper docstrings and type information
      - [x] Support operations (Add, Subtract, Multiply, Divide)

    - [x] **Vector** (Vector.hpp → vector.py)
      - [x] Create Vector2D class with type hints
      - [x] Implement methods for vector operations (+, -, *, /)
      - [x] Add utility methods (magnitude, normalization, etc.)
      - [x] Implement equality and comparison operations
      - [x] Add docstrings and examples

  - [x] **Core Entities**
    - [x] **Agent** (Agent.hpp/cpp → agent.py)
      - [x] Port `Agent` class with proper type hints
      - [x] Implement movement logic along paths
      - [x] Add resource carrying capability
      - [x] Implement update/simulation methods
      - [x] Add proper initialization and reset methods
      - [x] Ensure compatibility with Path and Resource classes
      - [x] Add relevant agent status properties (position, resources, etc.)
      - [x] Tests match original C++ tests in TestsAgent.cpp

    - [x] **City** (City.hpp/cpp → city.py)
      - [x] Port `City` class with all methods and properties
      - [x] Implement map, path, and unit management
      - [x] Add agent tracking and management
      - [x] Implement entity creation methods
      - [x] Handle simulation step processing
      - [x] Ensure coordination of all simulation components
      - [x] Add docstrings and examples
      - [x] Basic tests for constructors and grid position
      - [x] Additional tests for complex functionality (building, unit addition, etc.)

    - [x] **Unit** (Unit.hpp/cpp → unit.py)
      - [x] Port `Unit` class with proper type hints
      - [x] Implement resource production/consumption logic
      - [x] Add agent creation capabilities
      - [x] Implement update/simulation methods
      - [x] Handle activation/deactivation logic
      - [x] Add proper initialization
      - [x] Connect with city and path components
      - [x] Enhanced tests including rule execution functionality

    - [x] **Map** (Map.hpp/cpp → map.py)
      - [x] Implement base `Map` class
      - [x] Add grid functionality and coordinate system
      - [x] Implement map cell access and modification methods
      - [x] Create visualization utilities
      - [x] Support resource spread mechanisms
      - [x] Add map query operations
      - [x] Include bounds checking and safety mechanisms

    - [x] **Path** (Path.hpp/cpp → path.py)
      - [x] Port `Path` class with Node and Way components
      - [x] Add methods for path traversal and manipulation
      - [x] Ensure Node-Way connectivity is properly maintained
      - [x] Implement path queries and searches
      - [x] Add path utility methods (length, magnitude, etc.)
      - [x] Comprehensive tests for path graph structure

    - [x] **Node** (part of Path implementation → node.py)
      - [x] Create Node class for path nodes
      - [x] Implement connection management
      - [x] Add position and property data
      - [x] Include search-related metadata
      - [x] Add utility methods for node operations

  - [x] **Next Steps - Phase 3B Completion**
    - [x] Complete City test suite in test_city.py
      - [x] Basic tests for constructors and grid position are done
      - [x] test_building_city: Test creating maps and paths with properties (port from TestsCity.cpp)
      - [x] test_add_unit_split_road: Test splitting ways when adding units (port from TestsCity.cpp)
      - [x] test_translate: Test translating all entities together (port from TestsCity.cpp)
      - [x] test_update and test_update_remove_agent: Test simulation step logic (port from TestsCity.cpp)

  - [x] **Simulation Logic**
    - [x] **Simulation** (Simulation.hpp/cpp → simulation.py)
      - [x] Port `Simulation` class as main control system
      - [x] Implement simulation loop and update methods
      - [x] Add proper time management
      - [x] Create initialization and reset capabilities
      - [x] Implement rule processing and triggering
      - [x] Add event handling system
      - [x] Support saving/loading simulation state

    - [x] **Rule** (Rule.hpp/cpp → rule.py)
      - [x] Port `Rule` class with condition and action components
      - [x] Implement rule evaluation logic
      - [x] Add command execution capabilities
      - [x] Ensure proper rule triggering
      - [x] Add rule management utilities
      - [x] Include rule ordering and priority system

    - [x] **RuleCommand** (RuleCommand.hpp/cpp → rule_command.py)
      - [x] Port command types and execution logic
      - [x] Implement all command actions from C++ version
      - [x] Add parameter handling
      - [x] Create command factory methods
      - [x] Include execution context management
      - [x] Support command sequencing

    - [x] **ScriptParser** (ScriptParser.hpp/cpp → script_parser.py)
      - [x] Port script parsing functionality
      - [x] Implement token parsing and interpretation
      - [x] Add error handling and reporting
      - [x] Support comment handling
      - [x] Create utilities for script validation
      - [x] Add script debugging aids

    - [x] **Resources** (Resources.hpp/cpp → resources.py)
      - [x] Port `Resources` container class
      - [x] Implement collection management methods
      - [x] Add query and search capabilities
      - [x] Include resource manipulation operations
      - [x] Add serialization/deserialization support
      - [x] Implement resource transfer mechanisms

    - [x] **Dijkstra** (Dijkstra.hpp/cpp → dijkstra.py)
      - [x] Port pathfinding algorithm
      - [x] Implement priority queue and path tracking
      - [x] Add cost calculations
      - [x] Create path reconstruction
      - [x] Include optimizations for large graphs
      - [x] Support custom path cost functions

    - [x] **MapCoordinatesInsideRadius** (MapCoordinatesInsideRadius.hpp/cpp → map_coordinates_inside_radius.py)
      - [x] Port coordinate calculation within radius
      - [x] Implement efficient radius searches
      - [x] Add various radius shapes (circle, square)
      - [x] Support weighted searches
      - [x] Include boundary handling

    - [x] **MapRandomCoordinates** (MapRandomCoordinates.hpp/cpp → map_random_coordinates.py)
      - [x] Port random coordinate generation
      - [x] Implement various distribution patterns
      - [x] Add seed management for reproducibility
      - [x] Include bounds checking and validation
      - [x] Support constrained randomization

  - [x] **Demo/UI**
    - [x] **Choose Python UI Framework** (for demo.py)
      - [x] Research suitable Python UI frameworks (pygame, pyglet, kivy, etc.)
      - [x] Evaluate compatibility with simulation requirements
      - [x] Assess performance for real-time simulation rendering
      - [x] Consider cross-platform compatibility
      - [x] Determine learning curve and documentation quality
      - [x] Selected Pygame as the UI framework due to its similarity to SDL

    - [x] **Port Demo Logic** (demo/src/* → demo.py)
      - [x] Create base application structure
      - [x] Implement rendering loop
      - [x] Add user input handling
      - [x] Port camera and view controls
      - [x] Implement entity visualization
      - [x] Create UI controls and panels
      - [x] Add simulation control interface
      - [x] Implement debug visualization options
      - [x] Created demo.py with a GlassBoxDemo class for visualization
      - [x] Created run_demo.py script to easily launch the demo
      - [x] Created proper data directory structure for Python port (python/data/simulations)

- [ ] **4. Testing & Validation**
  - [ ] Ensure all tests pass for each ported module
  - [ ] Use code coverage tools (e.g., `pytest --cov`)
  - [ ] Compare Python and C++ test results for validation

- [ ] **5. Documentation & Examples**
  - [ ] Add docstrings to all Python modules and tests
  - [ ] Create example scripts in `python/` to demonstrate simulations

- [ ] **6. Continuous Improvement**
  - [ ] Refactor for Pythonic style and idioms
  - [ ] Add new tests for edge cases and new features
  - [ ] Optimize after correctness is established

---

**Migration will follow a "tests first" approach:**
For each module, port the C++ test file to Python first, then implement only enough of the Python module to make the test pass. This ensures correctness and incremental progress.

This document provides a comprehensive, actionable plan for porting the OpenGlassBox simulation engine from C++ to Python, integrating best practices from both traditional and test-driven development (TDD) approaches.

---

## 1. Preparation & Scoping

- **Understand the Codebase:** Review C++ classes, relationships, and simulation flow.
- **Identify Core Modules:** List all major components (Agent, City, Unit, Map, Resource, Rule, Simulation, etc.).
- **Set Up Python Environment:** Create a `python/` directory, initialize a virtual environment, and decide on a test framework (e.g., `pytest`).
- **Leverage Python Ecosystem:** Plan to use `dataclasses`, `typing`, `pytest`, and other modern Python tools.

---

## 2. Project Structure Overview

### Main Source Files (`src/` and `include/OpenGlassBox/`)
- Agent.cpp / Agent.hpp
- City.cpp / City.hpp
- Dijkstra.cpp / Dijkstra.hpp
- Map.cpp / Map.hpp
- MapCoordinatesInsideRadius.cpp / MapCoordinatesInsideRadius.hpp
- MapRandomCoordinates.cpp / MapRandomCoordinates.hpp
- Path.cpp / Path.hpp
- Resource.cpp / Resource.hpp
- Resources.cpp / Resources.hpp
- Rule.cpp / Rule.hpp
- RuleCommand.cpp / RuleCommand.hpp
- RuleValue.cpp / RuleValue.hpp
- ScriptParser.cpp / ScriptParser.hpp
- Simulation.cpp / Simulation.hpp
- Unit.cpp / Unit.hpp
- Vector.hpp (header only)

### Tests (`tests/`)
- main.cpp, main.hpp (test runner)
- TestsAgent.cpp
- TestsCity.cpp
- TestsCommand.cpp
- TestsCoordInsideRadius.cpp
- TestsMap.cpp
- TestsPath.cpp
- TestsResource.cpp
- TestsResources.cpp
- TestsScriptParser.cpp
- TestsSimulation.cpp
- TestsUnit.cpp
- TestsValue.cpp

---

## 3. Test-First, Iterative Porting Workflow

For each component (e.g., Agent), follow this detailed process:

### a. Port the Test

- **Translate the C++ test file** (e.g., `TestsAgent.cpp`) to Python (`test_agent.py`).
  - Map C++ test macros (e.g., `TEST`, `ASSERT_EQ`, `ASSERT_STREQ`) to Python's `unittest` or `pytest` assertions.
  - If the Python class does not exist yet, create stubs or mocks so the test can be written and run first.
- **Tips:**
  - Use `@unittest.skip` or `pytest.mark.skip` for incomplete tests.
  - Write docstrings for each test to clarify intent.

### b. Port the Implementation

- **Translate the C++ class** (e.g., `Agent`) to Python (`agent.py`).
  - Use Python idioms: classes, `@dataclass` for simple data holders, `list`/`dict` for containers.
  - Implement only enough to make the test pass.
- **Tips:**
  - Use type hints for clarity.
  - Document class and methods with docstrings.

### c. Run and Refine

- **Run the test** with `pytest` or `python -m unittest`.
  - Fix any issues in the implementation or test until the test passes.
  - Refactor for clarity and Pythonic style as you go.
- **Tips:**
  - Use code coverage tools (`pytest --cov`) to ensure all logic is tested.
  - Commit frequently to track progress and enable easy rollbacks.

### d. Repeat

- **Move to the next component** and repeat steps a–c.
  - Port the next test and its corresponding implementation.
  - Maintain a steady, incremental pace for reliability and maintainability.

---

## 4. Divide and Conquer: Migration Checklist

**For each item below, port the test file first, then the implementation.**
Use the C++ test output as a reference for expected results and edge cases.

The implementation follows a bottom-up approach based on the dependency hierarchy of the simulation engine:

### Phase 1-2: Foundation Classes & Utilities (COMPLETED)
- [x] Resource.hpp/cpp → resource.py, test_resource.py
- [x] RuleValue.hpp/cpp → rule_value.py, test_rule_value.py
- [x] Vector.hpp → vector.py, test_vector.py

### Phase 3A: Spatial Foundation
- [x] Map.hpp/cpp → map.py, test_map.py
  - [x] Implement core Map class with grid functionality
  - [x] Add resource management methods (set, get, add, remove)
  - [x] Implement coordinate conversion between grid and world
  - [x] Add support for resource distribution within radius
  - [x] Implement rule execution for maps
  - [ ] Add proper test coverage in test_map.py
    - [ ] Test cell validation and bounds checking
    - [ ] Test resource capacity limits
    - [ ] Test resource spreading across cells
    - [ ] Test coordinate conversion edge cases
  - [ ] Finalize documentation and examples
    - [ ] Add comprehensive docstrings to all methods
    - [ ] Include examples showing resource flow
    - [ ] Document grid coordinate system

- [x] MapCoordinatesInsideRadius.hpp/cpp → map_coordinates_inside_radius.py
  - [x] Create efficient coordinate caching mechanism
  - [x] Implement radius-based coordinate generation
  - [x] Add support for randomized coordinate ordering
  - [x] Implement boundary checking for coordinates
  - [ ] Create comprehensive tests in test_coord_inside_radius.py
    - [ ] Test different radius shapes (circle, square)
    - [ ] Test coordinates at grid boundaries
    - [ ] Test coordinates with various grid sizes
    - [ ] Test randomization of coordinate order
    - [ ] Test performance with large radius values

- [x] MapRandomCoordinates.hpp/cpp → map_random_coordinates.py
  - [x] Implement random coordinate generation within grid
  - [x] Add methods for coordinate selection and distribution
  - [x] Implement utility methods (reset, remaining_count, etc.)
  - [ ] Create tests in test_map_random_coordinates.py
    - [ ] Test distribution patterns across grid
    - [ ] Test coordinate selection with various constraints
    - [ ] Test reproducibility with fixed seeds
    - [ ] Test edge cases (empty grid, very large grid)
    - [ ] Test all utility methods (reset, start, next, etc.)

- [x] Path.hpp/cpp → path.py
  - [x] Implement Node class with connectivity management
    - [x] Create constructor with ID and position
    - [x] Add methods for unit and way management
    - [x] Implement position translation
    - [x] Add getters for connected ways and units
    - [x] Implement map position conversion

  - [x] Implement Way class for connecting nodes
    - [x] Create constructor with type, from/to nodes
    - [x] Add length/magnitude calculation
    - [x] Implement position and direction getters
    - [x] Add type and color properties

  - [x] Create Path class as graph container
    - [x] Implement node and way management
    - [x] Add methods for path construction and modification
    - [x] Implement way splitting functionality
    - [x] Add position translation for entire path

  - [ ] Add comprehensive tests in test_path.py
    - [ ] Test node creation and properties
    - [ ] Test way creation and node connections
    - [ ] Test path construction and management
    - [ ] Test way splitting and path modification
    - [ ] Test position interpolation along ways
    - [ ] Test node finding by position/proximity

- [x] Dijkstra.hpp/cpp → dijkstra.py
  - [x] Core algorithm implementation
    - [x] Implement Dijkstra class with search parameters
    - [x] Create priority queue using Python's heapq module
    - [x] Implement distance tracking using dictionaries
    - [x] Add visited node set for tracking explored nodes
    - [x] Create path reconstruction with parent tracking
    - [x] Add target node early termination optimization

  - [x] Advanced pathfinding features
    - [x] Implement custom cost functions for different way types
    - [x] Add bidirectional search capability
    - [x] Implement path filtering based on way properties
    - [x] Create mechanism for handling one-way connections
    - [x] Add pathfinding limitations (max distance, node count)

  - [x] Optimization strategies
    - [x] Implement path caching for frequent routes
    - [x] Add heuristic-based priority (A* variant)
    - [x] Create incremental path updates for dynamic graphs
    - [x] Implement batch processing for multiple targets
    - [x] Add multi-threaded pathfinding for large graphs (optional)

  - [x] Utility methods
    - [x] Create path distance/cost calculation
    - [x] Add path simplification for straight segments
    - [x] Implement path interpolation for smooth movement
    - [x] Create path visualization helper methods
    - [x] Add path comparison and validation utilities

  - [x] Tests and documentation
    - [x] Create test_dijkstra.py with comprehensive tests
    - [x] Test basic pathfinding in simple graphs
    - [x] Test pathfinding with various cost functions
    - [x] Test edge cases (disconnected graphs, no valid path)
    - [x] Test performance with large networks (100+ nodes)
    - [x] Add detailed docstrings with algorithmic complexity
    - [x] Include examples of common pathfinding scenarios

### Phase 3B: Entity Components
- [x] Unit.hpp/cpp → unit.py, test_unit.py
  - [x] Core unit structure and properties
    - [x] Create Unit class with comprehensive type hints
    - [x] Implement constructor with unit type, node/position binding
    - [x] Add unit state tracking (active/inactive, production state)
    - [x] Implement unique ID generation and tracking
    - [x] Create unit type registry and properties system
    - [x] Add debug visualization properties (color, shape, size)

  - [x] Resource production and management
    - [x] Implement input/output resource definitions
    - [x] Create resource storage containers with capacity limits
    - [x] Add production rate and efficiency calculations
    - [x] Implement resource transformation rules and ratios
    - [x] Create resource shortage and excess handling
    - [x] Add resource flow monitoring and statistics

  - [x] Agent interaction and coordination
    - [x] Implement agent creation with resource requests
    - [x] Add agent dispatching and routing capabilities
    - [x] Create target selection algorithm for optimal distribution
    - [x] Implement resource transfer protocols with agents
    - [x] Add agent queueing and scheduling system
    - [x] Create agent management for multiple resource types

  - [x] Simulation integration
    - [x] Implement update method for simulation steps
    - [x] Add rule application and triggering
    - [x] Create event handling for state changes
    - [x] Implement serialization for save/load functionality
    - [x] Add unit lifecycle hooks (create, upgrade, destroy)

  - [x] Tests and documentation
    - [x] Create comprehensive test_unit.py
    - [x] Test resource production and consumption
    - [x] Test agent creation and interaction
    - [x] Test rule
