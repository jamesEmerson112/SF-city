# OpenGlassBox Simulation Script DSL Specification

This document describes the custom domain-specific language (DSL) used for simulation scenario files (e.g., `TestCity.txt`) as parsed by `script_parser.py`.

---

## Overview

The DSL is a plain-text, section-based format. Each section begins with a keyword (e.g., `resources`, `maps`, `units`) and ends with `end`. Entities are defined within each section, with their properties specified by keywords and values. Arrays are enclosed in square brackets `[ ... ]`.

---

## Top-Level Structure

A script file consists of any combination of the following sections, in any order:

- `resources ... end`
- `maps ... end`
- `paths ... end`
- `segments ... end`
- `agents ... end`
- `units ... end`
- `rules ... end`

Each section contains one or more entity definitions.

---

## Section and Entity Syntax

### 1. Resources

```txt
resources
  resource <name>
  ...
end
```

**Example:**
```
resources
  resource Water
  resource Grass
  resource People
end
```

---

### 2. Maps

```txt
maps
  map <name>
    color <hex>
    capacity <int>
    rules [ <ruleName1> <ruleName2> ... ]
  ...
end
```

**Example:**
```
maps
  map Water
    color 0000FF
    capacity 100
  map Grass
    color 00FF00
    capacity 100
end
```

---

### 3. Paths

```txt
paths
  path <name>
    color <hex>
  ...
end
```

**Example:**
```
paths
  path Road
    color 888888
end
```

---

### 4. Segments (Ways)

```txt
segments
  segment <name>
    color <hex>
  ...
end
```

**Example:**
```
segments
  segment Dirt
    color 8B4513
end
```

---

### 5. Agents

```txt
agents
  agent <name>
    color <hex>
    speed <float>
  ...
end
```

**Example:**
```
agents
  agent People
    color FFFF00
    speed 50.0
  agent Worker
    color 00FFFF
    speed 30.0
end
```

---

### 6. Units

```txt
units
  unit <name>
    color <hex>
    mapRadius <int>
    targets [ <target1> <target2> ... ]
    caps [ <resource> <capacity> ... ]
    resources [ <resource> <amount> ... ]
    rules [ <ruleName1> <ruleName2> ... ]
  ...
end
```

**Example:**
```
units
  unit Home
    color FF69B4
    mapRadius 1
    targets [ People Worker ]
    caps [ Water 10 ]
    resources [ Water 5 ]
  unit Work
    color 00FFFF
    mapRadius 1
    targets [ People Worker ]
    caps [ Water 10 ]
    resources [ Water 0 ]
end
```

---

### 7. Rules

```txt
rules
  mapRule <name>
    rate <int>
    randomTiles <true|false>
    randomTilesPercent <int>
    <command> ...
    end
  unitRule <name>
    rate <int>
    <command> ...
    end
  ...
end
```

**Example:**
```
rules
  mapRule WaterRule
    rate 1
    randomTiles true
    local Water add 1
    end
  unitRule HomeRule
    rate 1
    local People add 1
    end
end
```

---

## Arrays

Arrays are enclosed in square brackets `[ ... ]` and are used for:
- targets
- caps (capacities)
- resources
- rules (references)

**Example:**
```
targets [ People Worker ]
caps [ Water 10 ]
resources [ Water 5 ]
rules [ WaterRule ]
```

---

## Colors

Colors are specified as hexadecimal strings (e.g., `FF69B4` for pink, `00FFFF` for cyan, `FFFF00` for yellow).

---

## Error Handling

- The parser will raise an error if it encounters an unknown token, missing section, or malformed array.
- All sections must be closed with `end`.
- All arrays must be enclosed in `[ ... ]`.

---

## Example Full Script

```txt
resources
	resource Water
	resource Grass
	resource People
end

paths
	path Road color 0xAAAAAA
end

segments
	segment Dirt color 0xAAAAAA
end

agents
	agent People color 0xFFFF00 speed 10
	agent Worker color 0xFFFFFF speed 10
end

rules

	mapRule CreateGrass
		rate 7

		map Water remove 10 randomTilesPercent 90
		map Grass add 1
	end

	unitRule SendPeopleToWork
		rate 20

		local People remove 1

		agent People to Work add [ People 1 ]
	end

	unitRule SendPeopleToHome
		rate 100

		map Water greater 70

		local People remove 1

		agent Worker to Home add [ People 1 ]
	end

	unitRule UsePeopleToWater
		rate 5

		local People greater 1

		map Water add 30
	end

end

units

	unit Home color 0xFF00FF mapRadius 1 rules [ SendPeopleToWork ] targets [ Home ] caps [ People 4 ] resources [ People 4 ]

	unit Work color 0x00AAFF mapRadius 3 rules [ SendPeopleToHome UsePeopleToWater ] targets [ Work ] caps [ People 2 ] resources [ ]

end

maps
	map Water color 0x0000FF capacity 100 rules [  ]
	map Grass color 0x00FF00 capacity 10 rules [ CreateGrass ]
end
```

---

## Example Visualization and Rule Flow: `TestCity.txt`

Below is a conceptual diagram and explanation of how the scenario defined in `TestCity.txt` works, including the flow of resources and the effect of rules.

```
+-------------------+         +-------------------+
|      Home         |         |      Work         |
|   (Pink, static)  |         |   (Cyan, static)  |
| People: 4         |         | People: 0         |
+-------------------+         +-------------------+
         |                              ^
         |                              |
         | SendPeopleToWork             | SendPeopleToHome
         | (rate 20):                   | (rate 100, if Water > 70):
         | Remove 1 People,             | Remove 1 People,
         | send People agent ---------->| send Worker agent
         |                              |
         v                              |
+-------------------+         +-------------------+
|   Water Map       |         |   Grass Map       |
|   (Blue, dynamic) |         |   (Green, dynamic)|
+-------------------+         +-------------------+
         ^                              ^
         |                              |
         | UsePeopleToWater             | CreateGrass
         | (rate 5, if People > 1):     | (rate 7):
         | Add 30 Water <---------------| Remove 10 Water (90% random),
         |                              | Add 1 Grass
         +------------------------------+
```

### **Entity and Rule Summary**

- **Home (unit):**
  - Color: Pink (`0xFF00FF`)
  - Starts with 4 People.
  - Rule: `SendPeopleToWork` (rate 20)
    - Removes 1 People from Home.
    - Sends a People agent to Work.

- **Work (unit):**
  - Color: Cyan (`0x00AAFF`)
  - Rule: `SendPeopleToHome` (rate 100)
    - If Water > 70, removes 1 People from Work, sends a Worker agent to Home.
  - Rule: `UsePeopleToWater` (rate 5)
    - If People > 1, adds 30 Water to Water map.

- **Water Map:**
  - Color: Blue (`0x0000FF`)
  - Rule: None directly, but receives Water from Work.

- **Grass Map:**
  - Color: Green (`0x00FF00`)
  - Rule: `CreateGrass` (rate 7)
    - Removes 10 Water (with 90% randomization), adds 1 Grass.

- **Agents:**
  - People: Yellow (`0xFFFF00`)
  - Worker: White (`0xFFFFFF`)

### **Rule Flow Explanation**

- **People move from Home to Work** via the `SendPeopleToWork` rule.
- **If Water is abundant at Work**, the `SendPeopleToHome` rule sends People (as Worker agents) back to Home.
- **If there are enough People at Work**, the `UsePeopleToWater` rule generates Water.
- **Grass is created** on the Grass map by consuming Water, via the `CreateGrass` rule.

### **Color Legend**

- **Pink:** Home (static)
- **Cyan:** Work (static)
- **Yellow:** People agent (dynamic, Home → Work)
- **White:** Worker agent (dynamic, Work → Home)
- **Blue:** Water map (dynamic resource)
- **Green:** Grass map (dynamic resource)
- **Grey:** Roads/segments (static, not shown in diagram)

---


## Notes

- Section and entity order is flexible, but all sections must be closed with `end`.
- All keywords are case-sensitive.
- Comments are not supported in the current DSL.

---

For more details, see the implementation in `src/script_parser.py`.
