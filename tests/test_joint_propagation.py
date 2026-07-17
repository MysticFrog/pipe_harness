"""Headless verification of JointPropagationObserver, run via FreeCADCmd.exe:

    FreeCADCmd.exe test_joint_propagation.py

Covers round 7 item 4: moving one component in a jointed chain should drag
every other component/free hose connected to it (directly or transitively)
by the same rigid delta, so connection points travel with their owners
without anything being permanently "grounded" at the world origin.
"""
import sys
import os

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "PipeHarness"
))

import FreeCAD as App

from pipeharness import objects
from pipeharness import snapping
from pipeharness.joint_propagation import JointPropagationObserver


def make_component(doc, name, position):
    block = doc.addObject("Part::Box", name + "Block")
    block.Length = 10
    block.Width = 10
    block.Height = 10
    part = doc.addObject("App::Part", name)
    part.addObject(block)
    part.Placement = App.Placement(position, App.Rotation())
    return part


def main():
    doc = App.newDocument("JointPropagationTest")
    observer = JointPropagationObserver()
    App.addDocumentObserver(observer)

    # A -- B -- C: a three-component chain, jointed A<->B and B<->C, so
    # propagation must walk two hops to reach C from a move of A.
    a = make_component(doc, "PartA", App.Vector(0, 0, 0))
    b = make_component(doc, "PartB", App.Vector(100, 0, 0))
    c = make_component(doc, "PartC", App.Vector(200, 0, 0))
    doc.recompute()

    point_a = objects.create_connection_point(doc, a, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name="PointA1")
    point_b1 = objects.create_connection_point(doc, b, App.Vector(100, 5, 5), App.Vector(-1, 0, 0), name="PointB1")
    point_b2 = objects.create_connection_point(doc, b, App.Vector(110, 5, 5), App.Vector(1, 0, 0), name="PointB2")
    point_c = objects.create_connection_point(doc, c, App.Vector(200, 5, 5), App.Vector(-1, 0, 0), name="PointC1")
    doc.recompute()

    # Mirror real usage (the Connect Points command): snap the points
    # coincident first, *then* record the mate as a Joint - otherwise the two
    # points start out apart and the test setup itself would look like a bug.
    snapping.connect(point_a, point_b1)
    doc.recompute()
    snapping.connect(point_b2, point_c)
    doc.recompute()
    objects.create_joint(doc, point_a, point_b1)
    objects.create_joint(doc, point_b2, point_c)
    doc.recompute()

    # An unrelated, un-jointed component should be left alone.
    d = make_component(doc, "PartD", App.Vector(-500, -500, -500))
    doc.recompute()
    d_before = App.Vector(d.Placement.Base)

    b_before = App.Vector(b.Placement.Base)
    c_before = App.Vector(c.Placement.Base)
    point_c_before = objects.global_placement(point_c).Base

    delta = App.Vector(37, -14, 8)
    a.Placement = App.Placement(a.Placement.Base + delta, a.Placement.Rotation)
    doc.recompute()

    assert (App.Vector(b.Placement.Base) - b_before - delta).Length < 1e-4, (
        "Directly jointed PartB should move by the same delta as PartA: "
        "got %s" % (App.Vector(b.Placement.Base) - b_before)
    )
    assert (App.Vector(c.Placement.Base) - c_before - delta).Length < 1e-4, (
        "Transitively jointed PartC (A->B->C) should also move by the same "
        "delta: got %s" % (App.Vector(c.Placement.Base) - c_before)
    )
    assert (objects.global_placement(point_c).Base - point_c_before - delta).Length < 1e-4, (
        "PartC's connection point should travel with its owner"
    )
    assert (App.Vector(d.Placement.Base) - d_before).Length < 1e-4, (
        "An un-jointed component should not move at all"
    )

    # A free-floating hose jointed onto a component (via its EndAnchor) should
    # also be dragged along when that component moves.
    hose = objects.create_hose(doc, None, name="FreeHose")
    doc.recompute()
    e = make_component(doc, "PartE", App.Vector(0, 0, 0))
    doc.recompute()
    point_e = objects.create_connection_point(doc, e, App.Vector(5, 5, 5), App.Vector(1, 0, 0), name="PointE1")
    doc.recompute()
    snapping.connect(hose.EndAnchor, point_e)
    doc.recompute()
    objects.create_joint(doc, hose.EndAnchor, point_e)
    doc.recompute()

    hose_before = App.Vector(hose.Placement.Base)
    e_delta = App.Vector(-9, 21, 3)
    e.Placement = App.Placement(e.Placement.Base + e_delta, e.Placement.Rotation)
    doc.recompute()
    assert (App.Vector(hose.Placement.Base) - hose_before - e_delta).Length < 1e-4, (
        "A free-floating hose jointed to a moved component should be dragged "
        "along by the same delta: got %s" % (App.Vector(hose.Placement.Base) - hose_before)
    )

    # Moving the *inner shape* directly (e.g. clicking the visible solid in
    # the 3D view and editing its own Placement, instead of the wrapping
    # App::Part's) is an easy mistake to make - it should still keep sibling
    # connection points (and anything jointed through them) correctly
    # attached, not leave them behind.
    f = make_component(doc, "PartF", App.Vector(1000, 0, 0))
    g = make_component(doc, "PartG", App.Vector(2000, 0, 0))
    doc.recompute()
    point_f = objects.create_connection_point(doc, f, App.Vector(1010, 5, 5), App.Vector(1, 0, 0), name="PointF1")
    point_g = objects.create_connection_point(doc, g, App.Vector(2000, 5, 5), App.Vector(-1, 0, 0), name="PointG1")
    doc.recompute()
    snapping.connect(point_f, point_g)
    doc.recompute()
    objects.create_joint(doc, point_f, point_g)
    doc.recompute()

    f_shape = f.Group[0]
    assert f_shape.TypeId == "Part::Box"
    point_f_before = objects.global_placement(point_f).Base
    g_before = App.Vector(g.Placement.Base)
    shape_delta = App.Vector(3, -2, 6)
    f_shape.Placement = App.Placement(f_shape.Placement.Base + shape_delta, f_shape.Placement.Rotation)
    doc.recompute()

    assert (objects.global_placement(point_f).Base - point_f_before - shape_delta).Length < 1e-4, (
        "PartF's own connection point should have been compensated to follow "
        "its shape after the shape's own Placement (not the App::Part's) was "
        "edited directly: expected +%s, got %s"
        % (shape_delta, objects.global_placement(point_f).Base - point_f_before)
    )
    assert (App.Vector(g.Placement.Base) - g_before - shape_delta).Length < 1e-4, (
        "PartG (jointed to PartF through their connection points) should have "
        "been dragged along too: got %s" % (App.Vector(g.Placement.Base) - g_before)
    )

    # Undo of a jointed move must revert the whole propagation, not just the
    # directly-moved part - the observer's edits to the neighbours have to land
    # inside the same transaction. (Undo is off by default in console mode, so
    # this is only meaningful with UndoMode enabled, as the GUI always has it.)
    # (observer is already registered globally from the top of main(); it
    # receives events for this new document too - don't re-add it, or it fires
    # twice per change.)
    undoc = App.newDocument("JointPropagationUndoTest")
    undoc.UndoMode = 1
    ua = make_component(undoc, "UA", App.Vector(0, 0, 0))
    ub = make_component(undoc, "UB", App.Vector(100, 0, 0))
    undoc.recompute()
    upa = objects.create_connection_point(undoc, ua, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name="UPA")
    upb = objects.create_connection_point(undoc, ub, App.Vector(100, 5, 5), App.Vector(-1, 0, 0), name="UPB")
    undoc.recompute()
    snapping.connect(upa, upb)
    undoc.recompute()
    objects.create_joint(undoc, upa, upb)
    undoc.recompute()

    ub_before = App.Vector(ub.Placement.Base)
    upb_before = objects.global_placement(upb).Base
    undoc.openTransaction("move UA")
    ua.Placement = App.Placement(ua.Placement.Base + App.Vector(0, 0, 50), ua.Placement.Rotation)
    undoc.recompute()
    undoc.commitTransaction()
    assert (App.Vector(ub.Placement.Base) - ub_before - App.Vector(0, 0, 50)).Length < 1e-4, (
        "UB should have propagated during the transaction"
    )
    undoc.undo()
    undoc.recompute()
    assert (App.Vector(ub.Placement.Base) - ub_before).Length < 1e-4, (
        "Undo should revert the propagated neighbour UB, not just the moved UA: "
        "got %s" % (App.Vector(ub.Placement.Base) - ub_before)
    )
    assert (objects.global_placement(upb).Base - upb_before).Length < 1e-4, (
        "Undo should revert UB's connection point too"
    )

    print("ALL CHECKS PASSED")


main()
