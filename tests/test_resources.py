"""
Test suite for the Resources container class.

This file covers:
- Construction and initialization of Resources containers.
- Adding, retrieving, and manipulating Resource objects within containers.
- Testing resource queries, searches, and collection operations.
- Verification of resource transfer and transformation methods.

The tests ensure that Resources containers behave correctly for resource management,
providing efficient storage and manipulation of Resource collections.
"""

import pytest

from openglassbox.resource import Resource
from openglassbox.resources import Resources


def test_constructor():
    """Test Resources container construction and basic operations."""
    resources = Resources()

    # Test initial state
    assert len(resources) == 0
    assert resources.is_empty()
    assert resources.empty()

    # Test adding resources via add_resource
    resources.add_resource("Water", 100)
    resources.add_resource("Food", 50)

    assert len(resources) == 2
    assert not resources.is_empty()


def test_resource_access():
    """Test resource access and retrieval methods."""
    resources = Resources()

    # Add some test resources
    resources.add_resource("Water", 75)
    resources.add_resource("Gold", 25)

    # Test find_resource method
    retrieved_water = resources.find_resource("Water")
    assert retrieved_water is not None
    assert retrieved_water.type() == "Water"
    assert retrieved_water.get_amount() == 75

    # Test find_resource with non-existent resource
    missing = resources.find_resource("NonExistent")
    assert missing is None

    # Test has_resource method
    assert resources.has_resource("Water")
    assert resources.has_resource("Gold")
    assert not resources.has_resource("Silver")


def test_resource_modification():
    """Test resource modification and manipulation."""
    resources = Resources()

    # Add initial resource
    resources.add_resource("Energy", 100)

    # Test set_capacity
    resources.set_capacity("Energy", 200)
    energy = resources.find_resource("Energy")
    assert energy.get_capacity() == 200

    # Test adding more
    resources.add_resource("Energy", 50)
    assert resources.get_amount("Energy") == 150

    # Test remove_resource
    resources.remove_resource("Energy", 25)
    assert resources.get_amount("Energy") == 125


def test_resource_removal():
    """Test resource removal operations."""
    resources = Resources()

    # Add test resources
    resources.add_resource("Iron", 100)
    resources.add_resource("Coal", 200)
    resources.add_resource("Stone", 300)

    assert len(resources) == 3

    # Test remove_resource reduces amount
    result = resources.remove_resource("Coal", 200)
    assert result is True
    assert resources.get_amount("Coal") == 0

    # Test remove non-existent
    result = resources.remove_resource("NonExistent", 10)
    assert result is False


def test_resource_iteration():
    """Test iteration over resources."""
    resources = Resources()

    # Add test data
    test_data = [
        ("Wood", 50),
        ("Stone", 75),
        ("Metal", 100)
    ]

    for name, amount in test_data:
        resources.add_resource(name, amount)

    # Test iteration via __iter__
    found_resources = []
    for resource in resources:
        found_resources.append((resource.type(), resource.get_amount()))

    # Sort both lists for comparison
    found_resources.sort(key=lambda x: x[0])
    test_data.sort(key=lambda x: x[0])

    assert found_resources == test_data


def test_resource_transfer():
    """Test resource transfer between containers."""
    source = Resources()
    destination = Resources()

    # Set up source resources
    source.add_resource("Wheat", 100)
    source.add_resource("Corn", 50)

    # Set up destination with capacity limits
    destination.set_capacity("Wheat", 200)
    destination.add_resource("Wheat", 25)

    # Transfer all resources from source to destination
    source.transfer_resources_to(destination)

    # Check destination received wheat
    assert destination.get_amount("Wheat") == 125  # 25 + 100

    # Source should be empty after transfer
    assert source.get_amount("Wheat") == 0


def test_resource_copying():
    """Test resource container copying via add_resources."""
    original = Resources()
    original.add_resource("Lumber", 200)
    original.add_resource("Nails", 500)

    # Copy via add_resources
    copy = Resources()
    copy.add_resources(original)
    assert len(copy) == len(original)
    assert copy.get_amount("Lumber") == 200
    assert copy.get_amount("Nails") == 500

    # Test that modifying copy doesn't affect original
    copy.add_resource("Lumber", 100)
    assert original.get_amount("Lumber") == 200  # Original unchanged
    assert copy.get_amount("Lumber") == 300


def test_resource_empty_state():
    """Test empty state of resources."""
    resources = Resources()

    # Initially empty
    assert resources.is_empty()
    assert resources.empty()

    # Add resources
    resources.add_resource("Oil", 100)
    assert not resources.is_empty()

    # Remove all amount
    resources.remove_resource("Oil", 100)
    assert resources.is_empty()


def test_resource_capacity_limits():
    """Test resource capacity and overflow handling."""
    resources = Resources()

    # Set capacity first
    resources.set_capacity("Water", 100)

    # Add within capacity
    resources.add_resource("Water", 50)
    assert resources.get_amount("Water") == 50

    # Try to add beyond capacity
    resources.add_resource("Water", 75)
    assert resources.get_amount("Water") == 100  # Capped at capacity

    # Verify capacity
    assert resources.get_capacity("Water") == 100


def test_find_or_add_resource():
    """Test find_or_add_resource creates if needed."""
    resources = Resources()

    # Should create new resource
    r = resources.find_or_add_resource("NewType")
    assert r is not None
    assert r.type() == "NewType"
    assert len(resources) == 1

    # Should find existing
    r2 = resources.find_or_add_resource("NewType")
    assert r2 is r
    assert len(resources) == 1
