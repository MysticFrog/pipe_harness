# SPDX-License-Identifier: MIT
"""Placement math for the point-and-click magnet/snap join.

Given a fixed ConnectionPoint and a free ConnectionPoint, computes the new
Placement for the free component so that:
  - the two points become coincident (same world position)
  - the two points' local +Z axes become opposed (they face each other)

The *free* point must belong to a component (App::Part) - that's the thing
whose Placement actually gets changed. The *fixed* point does not - it may
also be a component's port, but it may instead be a standalone connection
point with no parent component at all (e.g. a Hose's own StartAnchor/EndAnchor,
tracking its ends); global_placement() already returns the right thing either way.

Each ConnectionPoint's own Placement property is defined relative to its
parent App::Part (see objects.create_connection_point). Only the parent
App::Part's Placement is changed by a snap - the ConnectionPoint's own
Placement property never changes after creation.
"""
import FreeCAD as App

from .objects import get_parent_part, global_placement, is_grounded

# 180 degree rotation about X so that a port's local +Z becomes -Z, flipping
# it to face the opposite direction it was pointing.
_FLIP = App.Rotation(App.Vector(1, 0, 0), 180)


class SnapError(Exception):
    pass


def connect(fixed_point, free_point):
    """Move free_point's parent App::Part so free_point mates with fixed_point.

    Returns the free component (App::Part) that was moved.
    """
    free_component = get_parent_part(free_point)
    if free_component is None:
        raise SnapError(
            "The free (second-selected) connection point must belong to a "
            "component (App::Part) - it's the one that gets moved."
        )
    if is_grounded(free_component):
        raise SnapError(
            "The component to move ('%s') is grounded, so it can't be moved onto the "
            "other point. Select the grounded/existing part's point first (as the fixed "
            "reference) and the movable part's point second - or unground it." % free_component.Label
        )

    fixed_component = get_parent_part(fixed_point)
    if fixed_component is not None and fixed_component is free_component:
        raise SnapError("Cannot connect two points on the same component.")

    fixed_global = global_placement(fixed_point)

    target_placement = App.Placement(
        fixed_global.Base,
        fixed_global.Rotation * _FLIP,
    )

    # We need: free_component.Placement * free_point.Placement == target_placement
    # => free_component.Placement == target_placement * free_point.Placement.inverse()
    free_component.Placement = target_placement * free_point.Placement.inverse()

    return free_component
