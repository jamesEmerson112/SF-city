# OpenGlassBox Python Implementation - Visual Developer Guide

**Welcome to OpenGlassBox!** This comprehensive visual guide will take you from complete newcomer to confident contributor in the OpenGlassBox Python ecosystem. Whether you're interested in simulation theory, game development, urban planning, or just curious about agent-based modeling, this guide has everything you need to understand and extend the system.

## Table of Contents

1. [🔍 What is OpenGlassBox?](#-what-is-openglassbox)
2. [🏗️ Architecture & Visual Concepts](#️-architecture--visual-concepts)
3. [🚀 Getting Started](#-getting-started)
4. [📖 Understanding the Codebase](#-understanding-the-codebase)
5. [⚙️ The Simulation Engine](#️-the-simulation-engine)
6. [📜 Script System Deep Dive](#-script-system-deep-dive)
7. [⚡ Rule System Deep Dive](#-rule-system-deep-dive)
8. [💰 Resource Management](#-resource-management)
9. [🏗️ Building Your First Simulation](#️-building-your-first-simulation)
10. [🎓 Advanced Topics](#-advanced-topics)
11. [📚 API Reference](#-api-reference)
12. [🛠️ Development Guide](#️-development-guide)
13. [🐛 Troubleshooting](#-troubleshooting)

---

## 🔍 What is OpenGlassBox?

### The Big Picture - Visual Overview

```
🌍 DIGITAL ECOSYSTEM
┌─────────────────────────────────────────────────────────────┐
│  🏙️ Cities contain...                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ 🏭 Units    │  │ 🚶 Agents   │  │ 📦 Resources│        │
│  │ (Buildings) │  │ (Movers)    │  │ (Materials) │        │
│  │             │  │             │  │             │        │
│  │ • Factories │  │ • Workers   │  │ • Water     │        │
│  │ • Houses    │  │ • Trucks    │  │ • Power     │        │
│  │ • Shops     │  │ • People    │  │ • Goods     │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                             │
│  ⚡ Rules control everything:                              │
│  "If unit has >10 water AND >5 power, then produce goods" │
└─────────────────────────────────────────────────────────────┘
```

### Real-World Applications

```
🏙️ URBAN PLANNING          🏭 SUPPLY CHAINS           🌱 ECOSYSTEMS
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ Traffic Flow    │       │ Manufacturing   │       │ Predator-Prey   │
│ Utilities       │  ←→   │ Logistics       │  ←→   │ Food Webs       │
│ Commerce        │       │ Trade Networks  │       │ Populations     │
└─────────────────┘       └─────────────────┘       └─────────────────┘

💰 ECONOMICS              🚀 SPACE COLONIES
┌─────────────────┐       ┌─────────────────┐
│ Markets         │       │ Life Support    │
│ Labor           │  ←→   │ Resources       │
│ Resource Flow   │       │ Population      │
└─────────────────┘       └─────────────────┘
```

### Why OpenGlassBox is Special

```
TRADITIONAL SYSTEMS  vs  OPENGLASSBOX
┌─────────────────┐     ┌─────────────────┐
│ Simple Agents   │     │ Complex Agents  │
│ Basic Rules     │     │ Rich Behaviors  │
│ No Pathfinding  │     │ A* Navigation   │
│ Static World    │     │ Dynamic Economy │
└─────────────────┘     └─────────────────┘
        ❌                      ✅

KEY FEATURES:
✅ Heterogeneous Agents: Different types, different behaviors
✅ Spatial Pathfinding: Real 2D/3D navigation using A* algorithms
✅ Resource Economics: Complex production, consumption, trading
✅ Rule-Based Behavior: Sophisticated scripting system
✅ Real-Time Simulation: Proper timing and rate limiting
✅ Scriptable Configuration: Define simulations via text files
```

### From C++ to Python - Visual Migration

```
🔄 PLATFORM EVOLUTION

C++ Version (Original)           Python Version (New)
┌─────────────────────┐         ┌─────────────────────┐
│ ⚡ High Performance │   ────▶ │ 🐍 Easy to Learn   │
│ 🔧 Complex Setup    │         │ 📚 Rich Ecosystem  │
│ 💻 Compilation      │         │ 🔬 Research Tools  │
│ 🏭 Production Ready │         │ 🎓 Educational     │
└─────────────────────┘         └─────────────────────┘

🎯 DESIGN PRINCIPLE: 100% Functional Compatibility
• Same algorithms, same behaviors
• Same simulation results
• Python ease of use + C++ power
```

---

## 🏗️ Architecture & Visual Concepts

### The Entity Hierarchy

```
🎯 OPENGLASSBOX ARCHITECTURE
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  🌍 Simulation (Master Controller)                         │
│  ├── ⏰ Time: Fixed 200 FPS                               │
│  ├── 🏙️ Cities: Multiple game worlds                      │
│  └── 📊 Events: Listener notifications                    │
│                                                             │
│    🏙️ City (Game World)                                   │
│    ├── 🗺️ Maps: Spatial data layers                       │
│    │   └── 📍 Tiles: Grid cells (64x64 = 4,096 tiles)     │
│    ├── 🛤️ Paths: Navigation network                        │
│    │   └── 📍 Nodes: Waypoints for agent movement         │
│    ├── 🏭 Units: Stationary entities                       │
│    │   └── 📦 Resources: Stored materials                 │
│    ├── 🚶 Agents: Mobile entities                          │
│    │   └── 📦 Resources: Carried materials                │
│    └── ⚡ Rules: Behavior logic                           │
│                                                             │
│  📜 Script Parser: Configuration system                    │
│  └── 🔧 Creates all entity types from text files          │
└─────────────────────────────────────────────────────────────┘
```

### Visual Entity Interaction Flow

```
🔄 COMPLETE ENTITY INTERACTION CYCLE

Step 1: Rule Execution
🏭 Factory ──rules──▶ ⚡ "Need water!"
│ Water: 2/20        │ Rule checks: "local Water less 5"
│ Triggers action    │ Decision: Spawn water truck
└─────────────────────┘

Step 2: Agent Creation
🏭 Factory ──spawn──▶ 🚚 Water Truck
│ Removes resources  │ ├── Target: Water Plant
│ Cost: 5 goods      │ ├── Carrying: [Empty]
│                    │ └── Route: A* pathfinding
└─────────────────────┘

Step 3: Navigation
🚚 Truck ──navigate──▶ 🛤️ Path Network
│ Current: Node 15   │ Route: [15→12→8→4→1]
│ Speed: 3.0 u/s     │ Algorithm: A* search
│ Target: Node 1     │ Cost: Distance + congestion
└─────────────────────┘

Step 4: Pickup & Delivery
💧 Water Plant ──transfer──▶ 🚚 Truck ──deliver──▶ 🏭 Factory
│ Water: 25/30       │ Carries │ Water: 8           │ Water: 2→10/20
│ Gives: 8 water     │ 8 water │ Unloads all        │ Receives: 8
└─────────────────────┘       └─────────────────────┘

Step 5: Lifecycle Complete
🚚 Truck ──destroy──▶ 💨 Memory Cleanup
│ Mission complete   │ Agent self-destructs
│ Resources empty    │ Memory released
└─────────────────────┘
```

### Information Flow Patterns

```
📊 SIMULATION UPDATE CYCLE (200 FPS = 5ms per tick)

🕐 Every 5ms:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  🌍 Simulation.update()                                    │
│  ├── 📊 Accumulate deltaTime                              │
│  ├── ⏰ Process fixed timesteps                           │
│  └── 🏙️ Update all cities                                │
│                                                             │
│    🏙️ City.update()                                       │
│    ├── 🏭 For each Unit:                                  │
│    │   ├── 🔢 Increment tick counter                      │
│    │   ├── ⚡ Execute rules (rate-limited)                │
│    │   ├── 🚶 Spawn agents if needed                      │
│    │   └── 📊 Update resource states                      │
│    │                                                       │
│    └── 🚶 For each Agent:                                 │
│        ├── 🛤️ Calculate next position                     │
│        ├── 🚚 Move along path                             │
│        ├── 🎯 Check arrival at destination                │
│        ├── 📦 Handle resource transfers                   │
│        └── 🗑️ Self-destruct if mission complete          │
│                                                             │
│  📈 Global Statistics Update                               │
│  └── 📢 Notify event listeners                            │
└─────────────────────────────────────────────────────────────┘
```

### Design Patterns Visualized

```
🏗️ DESIGN PATTERNS IN ACTION

1. Command Pattern (Rules)
┌─────────────────────────────────────────┐
│ Rule = Command                          │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐    │
│ │ Test    │ │ Add     │ │ Remove  │    │
│ │ Water>5 │ │ Goods+10│ │ Power-3 │    │
│ └─────────┘ └─────────┘ └─────────┘    │
│           Commands in sequence          │
│ Execute: Validate ALL → Execute ALL     │
└─────────────────────────────────────────┘

2. Observer Pattern (Events)
┌─────────────────────────────────────────┐
│ Event: "City Added"                     │
│ 🏙️ Subject ─notify─▶ 👂 Listeners     │
│                      ├── 📊 Statistics │
│                      ├── 💾 Logger     │
│                      └── 🎮 GUI        │
└─────────────────────────────────────────┘

3. Factory Pattern (Script Parser)
┌─────────────────────────────────────────┐
│ 📜 Script ─parse─▶ 🏭 Factory ─create─▶│
│ "unit House"      Unit Factory        🏠 │
│ "agent Worker"    Agent Factory       🚶 │
│ "rule Produce"    Rule Factory        ⚡ │
└─────────────────────────────────────────┘
```

---

## 🚀 Getting Started

### Visual Installation Guide

```
📦 INSTALLATION FLOWCHART

┌─── Start Here ────┐
│ Prerequisites:    │
│ • Python 3.8+    │
│ • Git             │
│ • Terminal/CMD    │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 1. Clone Repo     │
│ git clone ...     │
│ cd OpenGlassBox   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ 2. Install Deps   │
│ cd python         │
│ pip install -r    │
│ requirements.txt  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ 3. Test Install   │
│ python -c "from   │
│ src.simulation    │
│ import Simulation"│
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ 4. Run Demo       │
│ python demo/src/  │
│ demo.py          │
└─────────┬─────────┘
          │
          ▼
┌─── Success! ──────┐
│ ✅ Ready to code! │
└───────────────────┘
```

### Project Structure Visualization

```
📁 PROJECT STRUCTURE MAP

OpenGlassBox/python/
├── 📂 src/                    ← Core Implementation
│   ├── 🧠 simulation.py      ← Main engine
│   ├── 🏙️ city.py           ← World management
│   ├── 🏭 unit.py           ← Buildings/structures
│   ├── 🚶 agent.py          ← Mobile entities
│   ├── 📦 resources.py      ← Resource containers
│   ├── ⚡ rule*.py          ← Behavior system
│   ├── 📜 script_parser.py  ← Configuration parser
│   ├── 🛤️ path.py          ← Navigation
│   ├── 🗺️ map*.py          ← Spatial data
│   └── 📐 vector.py         ← Math utilities
│
├── 🧪 tests/                 ← Test suite
│   ├── test_unit.py         ← Unit tests
│   ├── test_agent.py        ← Agent tests
│   ├── test_resources.py    ← Resource tests
│   └── test_*.py           ← All component tests
│
├── 🎮 demo/                  ← Example simulations
│   ├── src/demo.py          ← Basic demo
│   ├── src/demo_enhanced.py ← Advanced demo
│   └── data/               ← Demo configuration
│
├── 📊 data/                  ← Simulation data
│   └── simulations/         ← Script files
│
└── 📚 docs/                  ← Documentation
    └── DEVELOPER_GUIDE.md   ← This file!
```

### Your First 5 Minutes - Visual Tutorial

```
⏱️ QUICK START (5 MINUTES)

Minute 1: Create Basic Simulation
┌─────────────────────────────────────────┐
│ from src.simulation import Simulation   │
│ from src.vector import Vector3f         │
│                                         │
│ # Create 10x10 world                    │
│ sim = Simulation(gridSizeU=10,          │
│                  gridSizeV=10)          │
└─────────────────────────────────────────┘

Minute 2: Add a City
┌─────────────────────────────────────────┐
│ # Add city at origin                    │
│ city = sim.addCity("TinyTown",          │
│                    Vector3f(0, 0, 0))   │
│                                         │
│ print(f"City: {city.name()}")           │
└─────────────────────────────────────────┘

Minute 3: Run Simulation
┌─────────────────────────────────────────┐
│ # Run one timestep                      │
│ sim.update(0.005)  # 5ms                │
│                                         │
│ # Check results                         │
│ print(f"Grid: {city.gridSizeU()}x"      │
│       f"{city.gridSizeV()}")            │
└─────────────────────────────────────────┘

Minutes 4-5: Understand What Happened
┌─────────────────────────────────────────┐
│ ✅ Created simulation engine            │
│ ✅ Set up 10x10 spatial grid           │
│ ✅ Added city "TinyTown"                │
│ ✅ Ran fixed timestep update            │
│ ✅ City is ready for entities!          │
│                                         │
│ Next: Add units, agents, rules...       │
└─────────────────────────────────────────┘
```

---

## 📖 Understanding the Codebase

### Visual Module Dependency Map

```
🕸️ MODULE DEPENDENCIES

┌─────────────────────────────────────────────────────────────┐
│                     Core Dependencies                      │
│                                                             │
│  📜 script_parser.py                                       │
│  ├── Parses configuration files                            │
│  └── Creates entity type definitions                       │
│                          │                                 │
│                          ▼                                 │
│  🧠 simulation.py ◄─── Inherits from Script               │
│  ├── Top-level controller                                  │
│  ├── Fixed timestep management                             │
│  └── Creates and manages cities                            │
│                          │                                 │
│                          ▼                                 │
│  🏙️ city.py                                               │
│  ├── Game world container                                  │
│  ├── Spatial grid management                               │
│  ├── Global resource pools                                 │
│  └── Entity coordination                                   │
│           │                     │                          │
│           ▼                     ▼                          │
│  🏭 unit.py              🚶 agent.py                      │
│  ├── Stationary         ├── Mobile entities               │
│  ├── Rule execution     ├── Pathfinding                   │
│  ├── Resource storage   ├── Resource transport            │
│  └── Agent spawning     └── Target seeking                │
│           │                     │                          │
│           └─────────┬───────────┘                          │
│                     ▼                                      │
│  📦 resources.py                                           │
│  ├── Resource containers                                   │
│  ├── Capacity management                                   │
│  ├── Transfer validation                                   │
│  └── Type safety                                           │
│                                                             │
│  Supporting Modules:                                       │
│  ├── 🗺️ map*.py (Spatial data)                           │
│  ├── 🛤️ path.py (Navigation)                              │
│  ├── ⚡ rule*.py (Behavior system)                        │
│  └── 📐 vector.py (Math utilities)                        │
└─────────────────────────────────────────────────────────────┘
```

### Core Classes Deep Dive

#### 🧠 Simulation - The Heart of the Engine

```
🧠 SIMULATION CLASS ANATOMY

┌─────────────────────────────────────────┐
│ class Simulation(Script):               │
│                                         │
│ 🎯 Purpose: Master controller          │
│ ├── Inherits script parsing            │
│ ├── Manages multiple cities            │
│ └── Controls global timing             │
│                                         │
│ ⏰ Timing System:                      │
│ ├── Fixed 200 FPS (5ms ticks)          │
│ ├── Accumulates real deltaTime         │
│ ├── Processes in fixed chunks          │
│ └── Safety limit: 20 iterations/frame  │
│                                         │
│ 🏙️ City Management:                   │
│ ├── m_cities = {}  # Dictionary        │
│ ├── addCity() → Creates new city       │
│ ├── getCity() → Retrieves by name      │
│ └── Update all cities each tick        │
│                                         │
│ 📢 Event System:                       │
│ ├── Listener pattern                   │
│ ├── notifyListeners()                  │
│ └── onCityAdded() events               │
└─────────────────────────────────────────┘

Key Methods Visual:
┌─────────────────────────────────────────┐
│ def update(self, deltaTime):            │
│   📊 self.m_time += deltaTime           │
│   🔄 while time >= tick_interval:       │
│     ⏰ Process one simulation tick      │
│     🏙️ Update all cities               │
│     📉 Subtract tick time               │
│   ✅ Ensure deterministic behavior      │
└─────────────────────────────────────────┘
```

#### 🏙️ City - The Game World

```
🏙️ CITY CLASS VISUALIZATION

┌─────────────────────────────────────────────────────────────┐
│ class City:                                                 │
│                                                             │
│ 🎯 Purpose: Complete game world                           │
│ ├── Contains all simulation entities                       │
│ ├── Manages spatial relationships                          │
│ └── Coordinates resource flows                             │
│                                                             │
│ 🗺️ Spatial Systems:                                       │
│ ┌─────────────────────────────────────┐                   │
│ │ Grid: 64x64 = 4,096 tiles          │                   │
│ │ ┌─┬─┬─┬─┐                          │                   │
│ │ │0│1│2│3│... (u coordinate)         │                   │
│ │ ├─┼─┼─┼─┤                          │                   │
│ │ │ │ │ │ │                          │                   │
│ │ │ │🏠│ │                          │                   │
│ │ │ │ │🏭│                          │                   │
│ │ └─┴─┴─┴─┘                          │                   │
│ │ v coordinate                        │                   │
│ └─────────────────────────────────────┘                   │
│                                                             │
│ 🛤️ Navigation Network:                                    │
│ ┌─────────────────────────────────────┐                   │
│ │ Nodes: Waypoints for movement       │                   │
│ │ 📍──📍──📍                         │                   │
│ │ │   │   │                          │                   │
│ │ 📍──📍──📍                         │                   │
│ │ │   │   │                          │                   │
│ │ 📍──📍──📍                         │                   │
│ │ Paths: A* algorithm                 │                   │
│ └─────────────────────────────────────┘                   │
│                                                             │
│ 📦 Resource Pools:                                         │
│ ├── Global utilities (power grid)                          │
│ ├── City-wide resources (water)                            │
│ └── Emergency reserves                                      │
│                                                             │
│ 🏭 Entity Collections:                                    │
│ ├── m_units = {}    # All buildings                        │
│ ├── m_agents = {}   # All mobile entities                  │
│ └── Efficient O(1) lookups                                 │
└─────────────────────────────────────────────────────────────┘
```

#### 🏭 Unit - Stationary Entities

```
🏭 UNIT CLASS DETAILED VIEW

┌─────────────────────────────────────────────────────────────┐
│ class Unit:                                                 │
│                                                             │
│ 🎯 Purpose: Stationary game entities                      │
│ ├── Buildings, factories, resource nodes                   │
│ ├── Rule-based behavior                                    │
│ └── Resource production/consumption                         │
│                                                             │
│ 🔗 Node Connection:                                        │
│ ┌─────────────────────────────────────┐                   │
│ │ Unit ◄──connected──► Node           │                   │
│ │ 🏭                   📍             │                   │
│ │ • Position           • Pathfinding   │                   │
│ │ • Resources          • Agent access  │                   │
│ │ • Rules              • Navigation    │                   │
│ └─────────────────────────────────────┘                   │
│                                                             │
│ ⚡ Rule Execution Pattern:                                 │
│ ┌─────────────────────────────────────┐                   │
│ │ def executeRules(self):             │                   │
│ │   🔢 self.m_ticks += 1              │                   │
│ │   🔄 for rule in reversed(rules):   │                   │
│ │     ⏰ if ticks % rate == 0:        │                   │
│ │       ⚡ rule.execute(context)       │                   │
│ │   ✅ Exact C++ algorithm match      │                   │
│ └─────────────────────────────────────┘                   │
│                                                             │
│ 📦 Resource Management:                                    │
│ ├── Local storage with capacities                          │
│ ├── Transfer validation                                     │
│ ├── Overflow protection                                     │
│ └── Type safety enforcement                                 │
│                                                             │
│ 🚶 Agent Interaction:                                     │
│ ├── Spawn agents via rules                                 │
│ ├── Accept deliveries                                      │
│ ├── Validate targets                                       │
│ └── Process resource transfers                             │
└─────────────────────────────────────────────────────────────┘
```

#### 🚶 Agent - Mobile Entities

```
🚶 AGENT CLASS PATHFINDING VISUAL

┌─────────────────────────────────────────────────────────────┐
│ class Agent:                                                │
│                                                             │
│ 🎯 Purpose: Mobile resource transporters                   │
│ ├── People, vehicles, traders                              │
│ ├── A* pathfinding navigation                              │
│ └── Resource delivery system                               │
│                                                             │
│ 🛤️ Pathfinding Visualization:                             │
│ ┌─────────────────────────────────────┐                   │
│ │ Start: 🏭 Factory (Node 15)        │                   │
│ │ Goal:  💧 Water Plant (Node 1)      │                   │
│ │                                     │                   │
│ │ A* Search Process:                  │                   │
│ │ 📍15 ──explore──▶ 📍12             │                   │
│ │  │                │                │                   │
│ │  ▼                ▼                │                   │
│ │ 📍11 ──explore──▶ 📍8              │                   │
│ │  │                │                │                   │
│ │  ▼                ▼                │                   │
│ │ 📍7  ──explore──▶ 📍4              │                   │
│ │  │                │                │                   │
│ │  ▼                ▼                │                   │
│ │ 📍3  ──explore──▶ 📍1 ✅ GOAL!     │                   │
│ │                                     │                   │
│ │ Path: [15→12→8→4→1]                │                   │
│ │ Cost: Distance + congestion         │                   │
│ └─────────────────────────────────────┘                   │
│                                                             │
│ 🚚 Movement System:                                        │
│ ┌─────────────────────────────────────┐                   │
│ │ def update(self):                   │                   │
│ │   🛤️ Calculate next position        │                   │
│ │   📏 Apply speed and direction       │                   │
│ │   🎯 Check arrival at waypoint       │                   │
│ │   📦 Handle resource transfers       │                   │
│ │   🗑️ Self-destruct if complete      │                   │
│ └─────────────────────────────────────┘                   │
│                                                             │
│ 📦 Resource Carrying:                                      │
│ ├── Typed resource containers                              │
│ ├── Capacity constraints                                   │
│ ├── Pickup validation                                      │
│ └── Delivery verification                                  │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow Patterns Visualized

#### Resource Flow Example

```
💧 WATER DISTRIBUTION SYSTEM FLOW

T=0: Initial State
┌─────────────────────────────────────────────────────────────┐
│ 💧 Water Plant          🏭 Factory          🏠 House        │
│ Water: 25/30           Water: 2/20          Water: 8/10    │
│ Status: Producing      Status: LOW!         Status: OK     │
└─────────────────────────────────────────────────────────────┘

T=1: Rule Triggers (Factory needs water)
┌─────────────────────────────────────────────────────────────┐
│ 🏭 Factory Rule Execution:                                 │
│ ├── Check: "local Water less 5" ✅ (2 < 5)                 │
│ ├── Action: "agent WaterTruck to WaterPlant get Water 8"   │
│ └── Result: Spawn truck, reserve 8 water                   │
└─────────────────────────────────────
