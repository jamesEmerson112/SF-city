"""
Simulation module for OpenGlassBox simulation engine.

This module provides the main entry point for the simulation system,
exactly matching the C++ Simulation class behavior.
"""

from typing import Dict, Optional, Any
from abc import ABC, abstractmethod

from .city import City
from .vector import Vector3f
from .script_parser import Script
from .config import MAX_ITERATIONS_PER_UPDATE, TICKS_PER_SECOND


class Simulation(Script):
    """
    Entry point class managing a collection of Cities and running simulation on them.
    Equivalent to C++ Simulation class.

    Cities can be connected by sharing Nodes/Ways across their Path networks.
    """

    class Listener:
        """
        Simulation event listener.
        Equivalent to C++ Simulation::Listener class.
        """

        def __del__(self):
            """Virtual destructor equivalent."""
            pass

        def onCityAdded(self, city: City) -> None:
            """
            Called when a city is added to the simulation.
            Equivalent to C++ virtual void onCityAdded(City& city).

            Args:
                city: The city that was added
            """
            pass

        def onCityRemoved(self, city: City) -> None:
            """
            Called when a city is removed from the simulation.
            Equivalent to C++ virtual void onCityRemoved(City& city).

            Args:
                city: The city that was removed
            """
            pass

    def __init__(self, gridSizeU: int = 32, gridSizeV: int = 32):
        """
        Create a simulation game.
        Equivalent to C++ Simulation(uint32_t gridSizeU, uint32_t gridSizeV).

        Args:
            gridSizeU: The grid dimension along the U-axis for creating maps
            gridSizeV: The grid dimension along the V-axis for creating maps
        """
        super().__init__()
        self.m_gridSizeU = gridSizeU
        self.m_gridSizeV = gridSizeV
        self.m_time = 0.0
        self.m_totalTicks = 0  # Add tick counter for debug display
        self.m_cities: Dict[str, City] = {}

        # Static listener equivalent to C++ static Simulation::Listener listener
        static_listener = Simulation.Listener()
        self.set_listener(static_listener)

    def set_listener(self, listener: 'Simulation.Listener') -> None:
        """
        Set the listener for simulation events.
        Equivalent to C++ void setListener(Simulation::Listener& listener).

        Args:
            listener: The listener object to receive event notifications
        """
        self.m_listener = listener

    def update(self, deltaTime: float) -> None:
        """
        Update the game simulation.
        Equivalent to C++ void update(float const deltaTime).

        Args:
            deltaTime: The delta of time in seconds from the previous update
        """
        self.m_time += deltaTime

        # Rules are execute at TICKS_PER_SECOND intervals
        maxIterations = MAX_ITERATIONS_PER_UPDATE
        while (self.m_time >= 1.0 / TICKS_PER_SECOND) and (maxIterations > 0):
            self.m_time -= 1.0 / TICKS_PER_SECOND
            maxIterations -= 1
            self.m_totalTicks += 1  # Increment tick counter

            for city in self.m_cities.values():
                city.update()

    def get_total_ticks(self) -> int:
        """
        Get the total number of simulation ticks that have elapsed.
        
        Returns:
            The total tick count
        """
        return self.m_totalTicks

    def add_city(self, name: str, position: Vector3f) -> City:
        """
        Create a new City and replace the previous city if already exists.
        Equivalent to C++ City& addCity(std::string const& name, Vector3f position).

        Args:
            name: The name of the city to add
            position: The position of the city in world coordinates

        Returns:
            The newly created City object
        """
        city = City(name, position, self.m_gridSizeU, self.m_gridSizeV)
        self.m_cities[name] = city
        self.m_listener.onCityAdded(city)
        print(f"City {name} added")
        return city

    def get_city(self, name: str) -> City:
        """
        Get the City referred to by its name or throw an exception if the
        given name does not match any held cities.
        Equivalent to C++ City& getCity(std::string const& name).

        Args:
            name: The name of the city to retrieve

        Returns:
            The City object with the given name

        Raises:
            KeyError: If the given name does not match any held cities
        """
        try:
            return self.m_cities[name]
        except KeyError:
            raise KeyError(f"City '{name}' not found")

    def get_city_const(self, name: str) -> City:
        """
        Get the City referred to by its name or throw an exception if the
        given name does not match any held cities (const version).
        Equivalent to C++ City const& getCity(std::string const& name) const.

        Args:
            name: The name of the city to retrieve

        Returns:
            The City object with the given name

        Raises:
            KeyError: If the given name does not match any held cities
        """
        try:
            return self.m_cities[name]
        except KeyError:
            raise KeyError(f"City '{name}' not found")

    def cities(self) -> Dict[str, City]:
        """
        Getter: return the collection of cities.
        Equivalent to C++ Cities const& cities() const.

        Returns:
            Dictionary mapping city names to City objects
        """
        return self.m_cities

    def step(self) -> None:
        """
        Convenience method to advance the simulation by one step.
        Equivalent to calling update(1.0).
        """
        self.update(1.0)

    def sizeU(self) -> int:
        """Get the grid size along the U-axis."""
        return self.m_gridSizeU

    def sizeV(self) -> int:
        """Get the grid size along the V-axis."""
        return self.m_gridSizeV
