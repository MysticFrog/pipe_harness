"""Headless verification of the Hose object, run via FreeCADCmd.exe:

    FreeCADCmd.exe test_hose.py

Covers: default single-segment hose (a PipeStraight child, nested under the
Hose via claimChildren), a multi-segment bent hose built by appending separate
PipeStraight/PipeBend children (independent per-bend radii, segment length
measured as the exact tangent run, SweptAngle convention), starting a hose
with no connection point at all (world origin), the incremental
add_straight_to_hose/add_bend_to_hose helpers, the auto-managed StartAnchor/
EndAnchor connection points at both ends, the HydraulicHose/DashSize-driven
diameter, and - the key behavior - that a fitting connected to a hose's
EndAnchor follows along automatically when the hose grows a new segment.
"""
import sys
import os

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "PipeHarness"
))

import FreeCAD as App

from pipeharness import objects
from pipeharness import snapping


def approx_equal(a, b, tol=1e-4):
    return abs(a - b) < tol


def main():
    doc = App.newDocument("HoseTest")

    block = doc.addObject("Part::Box", "Block")
    block.Length = 30
    block.Width = 30
    block.Height = 30
    part = doc.addObject("App::Part", "Component")
    part.addObject(block)
    doc.recompute()

    start = objects.create_connection_point(
        doc, part, App.Vector(30, 15, 15), App.Vector(1, 0, 0), name="StartPoint"
    )
    doc.recompute()

    hose = objects.create_hose(doc, start, name="TestHose")
    doc.recompute()

    # Single default segment: a real PipeStraight child, valid solid, and it
    # should be nested under the Hose in the tree (claimChildren).
    assert len(hose.Segments) == 1
    assert isinstance(hose.Segments[0].Proxy, objects.PipeStraight)
    assert hose.Shape is not None and not hose.Shape.isNull(), "Hose should have a Shape"
    assert hose.Shape.Solids, "Single-segment hose should sweep into a solid"
    single_volume = hose.Shape.Volume
    assert single_volume > 0, "Hose solid should have positive volume"

    # StartAnchor/EndAnchor: auto-managed ConnectionPoints tracking both ends,
    # neither parented inside any App::Part, but usable as the fixed side of a
    # Connect Points mate. The default single straight segment runs along the
    # start point's own +X axis for _DEFAULT_SEGMENT_LENGTH.
    assert isinstance(hose.StartAnchor.Proxy, objects.ConnectionPoint)
    assert isinstance(hose.EndAnchor.Proxy, objects.ConnectionPoint)
    assert objects.get_parent_part(hose.StartAnchor) is None
    assert objects.get_parent_part(hose.EndAnchor) is None

    expected_start = objects.global_placement(start).Base
    assert (hose.StartAnchor.Placement.Base - expected_start).Length < 1e-4, (
        "StartAnchor should track the hose's start: expected %s, got %s"
        % (expected_start, hose.StartAnchor.Placement.Base)
    )
    expected_end = expected_start + App.Vector(1, 0, 0) * objects._DEFAULT_SEGMENT_LENGTH
    assert (hose.EndAnchor.Placement.Base - expected_end).Length < 1e-4, (
        "EndAnchor should track the hose's open end: expected %s, got %s"
        % (expected_end, hose.EndAnchor.Placement.Base)
    )

    # An anchor's +Z is its *outward* facing direction (what another port mates
    # against). This hose runs along +X, so the open (end) anchor faces +X
    # (direction of travel) and the start anchor faces -X (the opposite - it's
    # the near end, travel points away into the hose). A start anchor facing +X
    # would be backwards, and anything snapped onto it would point the wrong way.
    start_normal = hose.StartAnchor.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    end_normal = hose.EndAnchor.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    assert (start_normal - App.Vector(-1, 0, 0)).Length < 1e-4, (
        "StartAnchor should face OUT of the hose (-X here), got %s" % start_normal
    )
    assert (end_normal - App.Vector(1, 0, 0)).Length < 1e-4, (
        "EndAnchor should face out the open end (+X here), got %s" % end_normal
    )

    # ViewProvider isn't available headless (App.GuiUp is False), but the proxy
    # method itself should still work given the object/document names it looks
    # up by (it stores only those names, not the vobj, to stay JSON-serializable
    # when FreeCAD saves/copies the document - see ViewProviderHose.attach).
    fake_vp = objects.ViewProviderHose.__new__(objects.ViewProviderHose)
    fake_vp.object_name = hose.Name
    fake_vp.document_name = hose.Document.Name
    assert fake_vp._object() is hose
    assert fake_vp.claimChildren() == list(hose.Segments) + [hose.StartAnchor, hose.EndAnchor]

    # Connect another component onto the hose's open end, then grow the hose
    # by one more segment - the attached component should follow automatically.
    fitting_block = doc.addObject("Part::Box", "FittingBlock")
    fitting_block.Length = 10
    fitting_block.Width = 10
    fitting_block.Height = 10
    fitting_part = doc.addObject("App::Part", "FittingComponent")
    fitting_part.addObject(fitting_block)
    fitting_part.Placement = App.Placement(App.Vector(500, 500, 500), App.Rotation())
    doc.recompute()
    fitting_point = objects.create_connection_point(
        doc, fitting_part, App.Vector(500, 500, 500), App.Vector(-1, 0, 0), name="FittingPoint"
    )
    doc.recompute()

    moved = snapping.connect(hose.EndAnchor, fitting_point)
    doc.recompute()
    assert moved is fitting_part
    end_before_growth = hose.EndAnchor.Placement.Base
    assert (objects.global_placement(fitting_point).Base - end_before_growth).Length < 1e-4, (
        "FittingComponent should have snapped onto the hose's EndAnchor"
    )
    joint = objects.create_joint(doc, hose.EndAnchor, fitting_point)
    doc.recompute()

    objects.add_straight_to_hose(hose, 25.0)
    doc.recompute()

    end_after_growth = hose.EndAnchor.Placement.Base
    assert (end_after_growth - end_before_growth).Length > 1.0, (
        "EndAnchor should actually have moved after growing the hose"
    )
    assert (objects.global_placement(fitting_point).Base - end_after_growth).Length < 1e-4, (
        "FittingComponent should have automatically followed the hose's new "
        "open end after it grew a segment, not stayed at the old position"
    )

    # Clear the segments and build a 3-segment path with two 90-degree bends
    # (via SweptAngle: 90 turns a quarter-circle), each with its own distinct
    # bend radius, using the incremental append helpers.
    doc.removeObject(joint.Name)
    for seg in list(hose.Segments):
        doc.removeObject(seg.Name)
    hose.Segments = []
    doc.recompute()

    seg1 = objects.add_straight_to_hose(hose, 40.0)
    bend1 = objects.add_bend_to_hose(hose, 5.0, 90.0, 0.0, 0.0, 0.0)
    seg2 = objects.add_straight_to_hose(hose, 30.0)
    bend2 = objects.add_bend_to_hose(hose, 20.0, 90.0, 90.0, 0.0, 0.0)
    seg3 = objects.add_straight_to_hose(hose, 40.0)
    hose.Diameter = 10.0
    doc.recompute()

    assert list(hose.Segments) == [seg1, bend1, seg2, bend2, seg3]
    assert isinstance(seg1.Proxy, objects.PipeStraight)
    assert isinstance(bend1.Proxy, objects.PipeBend)

    assert hose.Shape is not None and not hose.Shape.isNull()
    assert hose.Shape.Solids, "Multi-segment bent hose should still sweep into a solid"
    bent_volume = hose.Shape.Volume
    assert bent_volume > single_volume, (
        "Longer routed hose should have more volume than the short default one"
    )

    # Segment length must be the exact tangent length, regardless of the
    # (very different) bend radii on either side of it.
    start_gp = App.Placement(App.Vector(0, 0, 0), App.Rotation())
    edges, end_pos, first_dir = objects._walk_segments(start_gp, list(hose.Segments))
    line_lengths = [e.Length for e in edges if e.Curve.__class__.__name__ == "Line"]
    assert len(line_lengths) == 3, "Expected exactly 3 straight edges (one per PipeStraight)"
    for expected, actual in zip([40.0, 30.0, 40.0], line_lengths):
        assert approx_equal(expected, actual), (
            "Segment length should be the exact tangent length regardless of bend "
            "radius: expected %s, got %s" % (expected, actual)
        )

    arc_lengths = [e.Length for e in edges if e.Curve.__class__.__name__ != "Line"]
    assert len(arc_lengths) == 2, "Expected exactly 2 arcs (one per PipeBend)"
    assert not approx_equal(arc_lengths[0], arc_lengths[1], tol=0.5), (
        "The two bends used different radii (5 and 20) so their arcs should differ "
        "in length: got %s" % arc_lengths
    )

    # DashSize should drive Diameter automatically while HydraulicHose is on
    # (no crimp geometry anymore - just the diameter sizing).
    no_hydraulic_volume = hose.Shape.Volume
    assert "-8" in objects.fitting_library.dash_sizes()
    hose.HydraulicHose = True
    hose.DashSize = "-16"
    doc.recompute()
    assert approx_equal(hose.Diameter.Value, objects.fitting_library.dash_size_od_mm("-16")), (
        "Diameter should follow DashSize while HydraulicHose is on"
    )
    assert hose.Shape.Volume != no_hydraulic_volume, "Diameter change should change the swept volume"
    hose.HydraulicHose = False
    doc.recompute()

    # A hose with no connection point at all should default to the world origin.
    free_hose = objects.create_hose(doc, None, name="FreeHose")
    doc.recompute()
    assert free_hose.Shape.Solids, "A hose with no StartPoint should still build (at the origin)"
    assert (free_hose.Shape.BoundBox.Center - App.Vector(0, 0, 25)).Length < 30, (
        "Free hose should be built near the world origin"
    )

    # with_default_segment=False should start with no children at all.
    empty_hose = objects.create_hose(doc, None, name="EmptyHose", with_default_segment=False)
    doc.recompute()
    assert list(empty_hose.Segments) == [], "with_default_segment=False should start empty"

    # Moving a free-floating hose's own Placement by hand should carry its
    # Shape *and* its StartAnchor/EndAnchor along together (round 7 item 1) -
    # previously the anchors were computed from a hardcoded identity frame and
    # were left behind when only obj.Placement was edited.
    move_hose = objects.create_hose(doc, None, name="MoveHose")
    doc.recompute()
    shape_center_before = move_hose.Shape.BoundBox.Center
    start_before = App.Vector(move_hose.StartAnchor.Placement.Base)
    end_before = App.Vector(move_hose.EndAnchor.Placement.Base)
    delta = App.Vector(100, 200, 300)
    move_hose.Placement = App.Placement(move_hose.Placement.Base + delta, move_hose.Placement.Rotation)
    doc.recompute()
    shape_center_after = move_hose.Shape.BoundBox.Center
    assert (shape_center_after - shape_center_before - delta).Length < 1e-4, (
        "Hose Shape should shift by exactly the Placement delta"
    )
    assert (move_hose.StartAnchor.Placement.Base - start_before - delta).Length < 1e-4, (
        "StartAnchor should shift by exactly the same Placement delta as the Shape"
    )
    assert (move_hose.EndAnchor.Placement.Base - end_before - delta).Length < 1e-4, (
        "EndAnchor should shift by exactly the same Placement delta as the Shape"
    )

    # Flip Normal (the right-click action): reverses a point's +Z outward
    # normal. On an ordinary point it toggles instantly; on an auto-managed
    # hose anchor it must *survive* recompute (the Reversed flag is re-applied
    # by _update_anchor, whereas a bare Placement flip would be overwritten).
    flip_hose = objects.create_hose(doc, None, name="FlipHose")
    doc.recompute()

    def anchor_normal(a):
        return a.Placement.Rotation.multVec(App.Vector(0, 0, 1))

    start_normal_before = anchor_normal(flip_hose.StartAnchor)
    objects.flip_connection_point(flip_hose.StartAnchor)
    assert flip_hose.StartAnchor.Reversed is True, "Flip should set Reversed on the anchor"
    assert (anchor_normal(flip_hose.StartAnchor) + start_normal_before).Length < 1e-4, (
        "StartAnchor normal should be exactly reversed right after Flip Normal"
    )
    # Force the anchor to be rederived from geometry - the flip must persist.
    flip_hose.Segments[0].Length = 77.0
    doc.recompute()
    doc.recompute()
    assert (anchor_normal(flip_hose.StartAnchor) + start_normal_before).Length < 1e-4, (
        "A flipped anchor's reversed normal must survive later recomputes, not "
        "revert to the geometry-derived direction"
    )
    # Flipping back clears it.
    objects.flip_connection_point(flip_hose.StartAnchor)
    doc.recompute()
    assert flip_hose.StartAnchor.Reversed is False
    assert (anchor_normal(flip_hose.StartAnchor) - start_normal_before).Length < 1e-4, (
        "Flipping a second time should restore the original outward normal"
    )

    # An ordinary (component-parented) point flips immediately too.
    flip_block = doc.addObject("Part::Box", "FlipBlock")
    flip_block.Length = flip_block.Width = flip_block.Height = 10
    flip_part = doc.addObject("App::Part", "FlipComponent")
    flip_part.addObject(flip_block)
    doc.recompute()
    fcp = objects.create_connection_point(
        doc, flip_part, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name="FlipCP"
    )
    doc.recompute()
    normal_before = fcp.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    objects.flip_connection_point(fcp)
    assert (fcp.Placement.Rotation.multVec(App.Vector(0, 0, 1)) + normal_before).Length < 1e-4, (
        "An ordinary connection point's normal should reverse on Flip Normal"
    )

    print("ALL CHECKS PASSED")


main()
