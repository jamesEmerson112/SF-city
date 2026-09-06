"""
Session recorder for capturing tick-by-tick simulation state to JSON.

Records agents, units, map summaries, and events each tick, then writes
the full session to a timestamped JSON file on exit.
"""

import json
import os
from datetime import datetime

from openglassbox.city import City
from openglassbox.config import TICKS_PER_SECOND


class _RecordingListener(City.Listener):
    """City listener that buffers agent/unit add/remove events."""

    def __init__(self, city_name, event_buffer):
        super().__init__()
        self.city_name = city_name
        self.event_buffer = event_buffer

    def on_agent_added(self, agent):
        self.event_buffer.append({
            "type": "agent_added",
            "city": self.city_name,
            "agent_id": agent.id(),
            "agent_type": agent.type(),
        })

    def on_agent_removed(self, agent):
        self.event_buffer.append({
            "type": "agent_removed",
            "city": self.city_name,
            "agent_id": agent.id(),
            "agent_type": agent.type(),
        })

    def on_unit_added(self, unit):
        self.event_buffer.append({
            "type": "unit_added",
            "city": self.city_name,
            "unit_type": unit.type(),
        })


class SessionRecorder:
    """Captures simulation state each tick and writes it to a JSON file."""

    def __init__(self, simulation, simfile):
        self.simulation = simulation
        self.tick_number = 0
        self.event_buffer = []
        self.ticks = []
        self.metadata = {
            "timestamp": datetime.now().isoformat(),
            "simfile": os.path.basename(simfile),
            "grid_size": [simulation.sizeU(), simulation.sizeV()],
            "ticks_per_second": TICKS_PER_SECOND,
        }

    def attach_to_cities(self):
        """Set recording listeners on each city to capture events."""
        for city_name, city in self.simulation.cities().items():
            listener = _RecordingListener(city_name, self.event_buffer)
            city.set_listener(listener)

    def capture_tick(self):
        """Snapshot all cities and append a tick record."""
        self.tick_number += 1
        cities_data = {}
        for city_name, city in self.simulation.cities().items():
            cities_data[city_name] = self._snapshot_city(city)

        self.ticks.append({
            "tick": self.tick_number,
            "cities": cities_data,
            "events": list(self.event_buffer),
        })
        self.event_buffer.clear()

    def save(self, output_dir):
        """Write the recorded session to a JSON file.

        Args:
            output_dir: Directory to write the session file into.

        Returns:
            The path of the written file.
        """
        os.makedirs(output_dir, exist_ok=True)
        filename = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            json.dump({"metadata": self.metadata, "ticks": self.ticks}, f, indent=2)
        return filepath

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot_city(self, city):
        agents = []
        for agent in city.agents():
            pos = agent.position()
            resources = [
                {
                    "type": r.type(),
                    "amount": r.get_amount(),
                    "capacity": r.get_capacity(),
                }
                for r in agent.resources()
            ]
            agents.append({
                "id": agent.id(),
                "type": agent.type(),
                "position": [pos.x, pos.y, pos.z],
                "target": agent.m_searchTarget,
                "resources": resources,
            })

        units = []
        for unit in city.units():
            pos = unit.position()
            resources = [
                {
                    "type": r.type(),
                    "amount": r.get_amount(),
                    "capacity": r.get_capacity(),
                }
                for r in unit.resources().container()
            ]
            units.append({
                "type": unit.type(),
                "position": [pos.x, pos.y, pos.z],
                "resources": resources,
            })

        maps = {}
        for map_name, map_obj in city.maps().items():
            cells = map_obj.m_resources
            non_zero = [c for c in cells if c > 0]
            total = sum(non_zero)
            maps[map_name] = {
                "total": total,
                "max_cell": max(cells) if cells else 0,
                "min_cell": min(cells) if cells else 0,
            }

        return {
            "agents": agents,
            "units": units,
            "maps": maps,
            "agent_count": len(city.agents()),
            "unit_count": len(city.units()),
        }
