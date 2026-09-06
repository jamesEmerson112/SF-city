"""
Test suite for the Resource class.

This file covers:
- Construction and initialization of Resource objects.
- Verification of member variables, type properties, and correct default values.
- Methods for adding, removing, and transferring resource amounts.
- Capacity management and edge cases for resource handling.

The tests ensure that Resource objects behave as expected for all basic operations, matching the logic and constraints of the original C++ simulation engine.
"""

import pytest
from openglassbox.resource import Resource

def test_constants():
    assert Resource.MAX_CAPACITY >= 65535

def test_constructor():
    oil = Resource("oil")
    assert oil.m_type == "oil"
    assert oil.m_amount == 0
    assert oil.m_capacity == Resource.MAX_CAPACITY
    assert oil.get_amount() == 0
    assert oil.has_amount() is False
    assert oil.get_capacity() == Resource.MAX_CAPACITY
    assert oil.type() == "oil"

def test_add_amount():
    oil = Resource("oil")
    assert oil.m_amount == 0
    assert oil.m_capacity == Resource.MAX_CAPACITY

    oil.add(32)
    assert oil.m_amount == 32
    assert oil.get_amount() == 32
    assert oil.has_amount() is True

    oil.add(32)
    assert oil.m_amount == 64
    assert oil.get_amount() == 64
    assert oil.has_amount() is True

    oil.set_capacity(32)
    assert oil.m_capacity == 32
    assert oil.get_capacity() == 32
    assert oil.m_amount == 32
    assert oil.get_amount() == 32
    assert oil.has_amount() is True

    oil.add(32)
    assert oil.m_capacity == 32
    assert oil.get_capacity() == 32
    assert oil.m_amount == 32
    assert oil.get_amount() == 32
    assert oil.has_amount() is True

    oil.set_capacity(0)
    assert oil.m_capacity == 0
    assert oil.get_capacity() == 0
    assert oil.m_amount == 0
    assert oil.get_amount() == 0
    assert oil.has_amount() is False

def test_add_amount_pathological_case():
    oil = Resource("oil")
    oil.add(32)
    assert oil.get_amount() == 32
    assert oil.has_amount() is True

    oil.add(Resource.MAX_CAPACITY)
    assert oil.get_amount() == Resource.MAX_CAPACITY
    assert oil.has_amount() is True

    oil.m_amount = 32
    oil.set_capacity(32)
    oil.add(Resource.MAX_CAPACITY)
    assert oil.get_amount() == 32
    assert oil.has_amount() is True

def test_remove_amount():
    oil = Resource("oil")
    oil.add(32)
    assert oil.get_amount() == 32
    assert oil.has_amount() is True

    oil.remove(16)
    assert oil.get_amount() == 16
    assert oil.has_amount() is True

    oil.remove(18)
    assert oil.get_amount() == 0
    assert oil.has_amount() is False

def test_transfert():
    oil = Resource("oil")
    gaz = Resource("gaz")

    assert oil.get_amount() == 0
    assert oil.get_capacity() == Resource.MAX_CAPACITY
    assert gaz.get_amount() == 0
    assert gaz.get_capacity() == Resource.MAX_CAPACITY

    oil.add(32)
    assert oil.get_amount() == 32
    assert oil.get_capacity() == Resource.MAX_CAPACITY

    oil.transfer_to(gaz)
    assert oil.get_amount() == 0
    assert oil.get_capacity() == Resource.MAX_CAPACITY
    assert gaz.get_amount() == 32
    assert gaz.get_capacity() == Resource.MAX_CAPACITY

    oil.transfer_to(gaz)
    assert oil.get_amount() == 0
    assert oil.get_capacity() == Resource.MAX_CAPACITY
    assert gaz.get_amount() == 32
    assert gaz.get_capacity() == Resource.MAX_CAPACITY

    oil.add(32)
    gaz.set_capacity(16)
    assert oil.get_amount() == 32
    assert oil.get_capacity() == Resource.MAX_CAPACITY
    assert gaz.get_amount() == 16
    assert gaz.get_capacity() == 16

    gaz.remove(1)
    assert gaz.get_amount() == 15
    assert gaz.get_capacity() == 16
    oil.transfer_to(gaz)
    assert oil.get_amount() == 31
    assert gaz.get_amount() == 16
    assert gaz.get_capacity() == 16
