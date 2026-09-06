"""
Test suite for the RuleValue class and related value types.

This file covers:
- Construction and evaluation of different RuleValue types.
- Testing global values, local values, map values, and constants.
- Verification of resource access through rule values.
- Testing type() method on all value types.

The tests ensure that RuleValue objects behave correctly for simulation logic,
rule evaluation, and resource management within the OpenGlassBox engine.
"""

import pytest

from openglassbox.resource import Resource
from openglassbox.resources import Resources
from openglassbox.rule_value import RuleValueGlobal, RuleValueLocal, RuleValueMap
from openglassbox.rule import RuleContext


def _make_context_with_globals(**kwargs):
    """Helper to create a RuleContext with global resources."""
    ctx = RuleContext()
    ctx.globals = Resources()
    ctx.locals = Resources()
    for name, amount in kwargs.items():
        ctx.globals.add_resource(name, amount)
    return ctx


def _make_context_with_locals(**kwargs):
    """Helper to create a RuleContext with local resources."""
    ctx = RuleContext()
    ctx.globals = Resources()
    ctx.locals = Resources()
    for name, amount in kwargs.items():
        ctx.locals.add_resource(name, amount)
    return ctx


def test_rule_value_global():
    """Test global rule values."""
    resource = Resource("TestResource")
    global_value = RuleValueGlobal(resource)

    assert global_value.m_resource is resource
    assert global_value.type() == "TestResource"

    # Test get with context
    ctx = _make_context_with_globals(TestResource=42)
    result = global_value.get(ctx)
    assert result == 42

    # Test with missing resource (returns 0)
    ctx2 = _make_context_with_globals()
    result2 = global_value.get(ctx2)
    assert result2 == 0


def test_rule_value_local():
    """Test local rule values."""
    resource = Resource("LocalResource")
    local_value = RuleValueLocal(resource)

    assert local_value.m_resource is resource
    assert local_value.type() == "LocalResource"

    # Test get with context
    ctx = _make_context_with_locals(LocalResource=25)
    result = local_value.get(ctx)
    assert result == 25

    # Test with missing resource
    ctx2 = _make_context_with_locals()
    result2 = local_value.get(ctx2)
    assert result2 == 0


def test_rule_value_map():
    """Test map rule values."""
    map_value = RuleValueMap("MapResource")

    assert map_value.m_mapId == "MapResource"
    assert map_value.type() == "MapResource"


def test_rule_context():
    """Test the RuleContext container."""
    context = RuleContext()

    # Test default initialization
    assert context.city is None
    assert context.unit is None
    assert context.u == 0
    assert context.v == 0
    assert context.radius == 0

    # Test setting resources
    context.globals = Resources()
    context.locals = Resources()
    context.globals.add_resource("Global", 100)
    context.locals.add_resource("Local", 50)

    assert context.globals.get_amount("Global") == 100
    assert context.locals.get_amount("Local") == 50


def test_rule_value_add_and_remove():
    """Test add and remove operations through rule values."""
    resource = Resource("Gold")
    global_value = RuleValueGlobal(resource)

    ctx = _make_context_with_globals(Gold=100)

    # Test add
    global_value.add(ctx, 50)
    assert global_value.get(ctx) == 150

    # Test remove
    global_value.remove(ctx, 30)
    assert global_value.get(ctx) == 120


def test_rule_value_capacity():
    """Test capacity access through rule values."""
    resource = Resource("Water")
    global_value = RuleValueGlobal(resource)

    ctx = _make_context_with_globals(Water=50)
    ctx.globals.set_capacity("Water", 200)

    assert global_value.capacity(ctx) == 200
    assert global_value.get(ctx) == 50


def test_rule_value_local_add_remove():
    """Test add and remove on local values."""
    resource = Resource("Housing")
    local_value = RuleValueLocal(resource)

    ctx = _make_context_with_locals(Housing=50)

    local_value.add(ctx, 10)
    assert local_value.get(ctx) == 60

    local_value.remove(ctx, 20)
    assert local_value.get(ctx) == 40


def test_rule_value_types():
    """Test different rule value type instantiation."""
    global_val = RuleValueGlobal(Resource("test_global"))
    local_val = RuleValueLocal(Resource("test_local"))
    map_val = RuleValueMap("test_map")

    # Test type properties
    assert global_val.type() == "test_global"
    assert local_val.type() == "test_local"
    assert map_val.type() == "test_map"


def test_rule_value_string_representation():
    """Test string representation of rule values."""
    global_val = RuleValueGlobal(Resource("TestGlobal"))
    local_val = RuleValueLocal(Resource("TestLocal"))
    map_val = RuleValueMap("TestMap")

    # Test that str() doesn't crash
    global_str = str(global_val)
    local_str = str(local_val)
    map_str = str(map_val)

    assert isinstance(global_str, str)
    assert isinstance(local_str, str)
    assert isinstance(map_str, str)
