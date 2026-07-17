"""Headless verification of component grounding and native-body wrapping, run
via FreeCADCmd.exe:

    FreeCADCmd.exe test_grounding.py

Covers:
- ensure_component() wraps a native root body (one not imported through Pipe
  Harness) in an App::Part in place, grounded by default, without moving it;
- is_grounded()/set_grounded() round-trip;
- snapping.connect() refuses to move a grounded component;
- joint propagation never drags a grounded neighbour, but a grounded component
  moved *directly* still drags its non-grounded neighbours;
- joint_propagation.suppress() stops propagation entirely for its scope.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "PipeHarness"))

import FreeCAD as App

from pipeharness import objects
from pipeharness import snapping
from pipeharness import joint_propagation
from pipeharness.joint_propagation import JointPropagationObserver


def make_component(doc, name, pos, grounded=False):
    block = doc.addObject("Part::Box", name + "Block")
    block.Length = block.Width = block.Height = 10
    part = doc.addObject("App::Part", name)
    part.addObject(block)
    part.Placement = App.Placement(App.Vector(*pos), App.Rotation())
    if grounded:
        objects.set_grounded(part, True)
    return part


def main():
    observer = JointPropagationObserver()
    App.addDocumentObserver(observer)

    # --- ensure_component wraps a native root body, grounded, in place --------
    doc = App.newDocument("GroundingTest")
    native = doc.addObject("Part::Box", "NativeBody")
    native.Length = native.Width = native.Height = 20
    native.Placement = App.Placement(App.Vector(7, 0, 0), App.Rotation())
    doc.recompute()
    center_before = native.Shape.BoundBox.Center

    comp, wrapped = objects.ensure_component(doc, native)
    doc.recompute()
    assert wrapped, "a root native body should be wrapped in a new component"
    assert comp.TypeId == "App::Part"
    assert native in comp.Group, "the body should now live inside the new component"
    assert objects.get_parent_part(native) is comp
    assert objects.is_grounded(comp), "a wrapped existing body should be grounded by default"
    assert (native.Shape.BoundBox.Center - center_before).Length < 1e-6, (
        "wrapping must not move the body"
    )
    # calling again is a no-op (already inside a component)
    comp2, wrapped2 = objects.ensure_component(doc, native)
    assert comp2 is comp and not wrapped2

    # --- is_grounded / set_grounded round-trip -------------------------------
    plain = make_component(doc, "Plain", (200, 0, 0))
    assert not objects.is_grounded(plain)
    objects.set_grounded(plain, True)
    assert objects.is_grounded(plain)
    objects.set_grounded(plain, False)
    assert not objects.is_grounded(plain)

    # --- snapping.connect refuses to move a grounded component ---------------
    g = make_component(doc, "Grounded", (0, 0, 0), grounded=True)
    n = make_component(doc, "NewPart", (100, 0, 0))
    doc.recompute()
    gp = objects.create_connection_point(doc, g, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name="GP")
    npnt = objects.create_connection_point(doc, n, App.Vector(100, 5, 5), App.Vector(-1, 0, 0), name="NP")
    doc.recompute()

    raised = False
    try:
        snapping.connect(gp, npnt)  # gp fixed, npnt free -> would move the grounded 'Grounded'? no, npnt free
    except snapping.SnapError:
        raised = True
    # here the *free* one is 'NewPart' (not grounded), so it should succeed:
    assert not raised, "moving the non-grounded free part onto the grounded one should work"
    # but trying to move the grounded one (as the free/second point) must fail:
    raised = False
    try:
        snapping.connect(npnt, gp)  # now gp (grounded) is the free one -> refuse
    except snapping.SnapError:
        raised = True
    assert raised, "snapping must refuse to move a grounded component"

    # --- propagation never drags a grounded neighbour ------------------------
    doc2 = App.newDocument("PropGroundTest")
    existing = make_component(doc2, "Existing", (0, 0, 0), grounded=True)
    newp = make_component(doc2, "New", (100, 0, 0))
    doc2.recompute()
    ep = objects.create_connection_point(doc2, existing, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name="EP")
    np2 = objects.create_connection_point(doc2, newp, App.Vector(100, 5, 5), App.Vector(-1, 0, 0), name="NP2")
    doc2.recompute()
    snapping.connect(ep, np2)
    doc2.recompute()
    objects.create_joint(doc2, ep, np2)
    doc2.recompute()

    existing_before = App.Vector(existing.Placement.Base)
    newp_before = App.Vector(newp.Placement.Base)

    # Move the NEW part: the grounded existing assembly must stay put.
    newp.Placement = App.Placement(newp.Placement.Base + App.Vector(0, 0, 40), newp.Placement.Rotation)
    doc2.recompute()
    assert (App.Vector(existing.Placement.Base) - existing_before).Length < 1e-6, (
        "moving the new part must not drag the grounded existing assembly"
    )

    # Move the grounded existing part *directly*: it still drags the non-grounded new one.
    existing_now = App.Vector(existing.Placement.Base)
    new_now = App.Vector(newp.Placement.Base)
    existing.Placement = App.Placement(existing.Placement.Base + App.Vector(5, 0, 0), existing.Placement.Rotation)
    doc2.recompute()
    assert (App.Vector(newp.Placement.Base) - new_now - App.Vector(5, 0, 0)).Length < 1e-6, (
        "directly moving a grounded part should still drag its non-grounded neighbours"
    )

    # --- suppress() stops propagation for its scope --------------------------
    doc3 = App.newDocument("SuppressTest")
    a = make_component(doc3, "A", (0, 0, 0))
    b = make_component(doc3, "B", (100, 0, 0))
    doc3.recompute()
    pa = objects.create_connection_point(doc3, a, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name="PA")
    pb = objects.create_connection_point(doc3, b, App.Vector(100, 5, 5), App.Vector(-1, 0, 0), name="PB")
    doc3.recompute()
    snapping.connect(pa, pb)
    doc3.recompute()
    objects.create_joint(doc3, pa, pb)
    doc3.recompute()

    b_before = App.Vector(b.Placement.Base)
    with joint_propagation.suppress():
        a.Placement = App.Placement(a.Placement.Base + App.Vector(0, 0, 50), a.Placement.Rotation)
        doc3.recompute()
    assert (App.Vector(b.Placement.Base) - b_before).Length < 1e-6, (
        "with propagation suppressed, moving A must not drag B"
    )
    # outside suppress, propagation works again
    b_now = App.Vector(b.Placement.Base)
    a.Placement = App.Placement(a.Placement.Base + App.Vector(0, 0, 10), a.Placement.Rotation)
    doc3.recompute()
    assert (App.Vector(b.Placement.Base) - b_now - App.Vector(0, 0, 10)).Length < 1e-6, (
        "after the suppress scope, propagation should work normally again"
    )

    print("ALL CHECKS PASSED")


main()
