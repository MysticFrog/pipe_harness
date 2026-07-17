# SPDX-License-Identifier: MIT
"""Headless verification, run via the portable FreeCAD's FreeCADCmd.exe:

    FreeCADCmd.exe test_snapping.py

Exercises the core data model and snapping math directly (bypassing GUI
selection), since FreeCADCmd has no GUI to select things with.
"""
import sys
import os

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "PipeHarness"
))

import FreeCAD as App

from pipeharness import objects
from pipeharness import snapping
from pipeharness import fitting_library


def approx_equal_vec(a, b, tol=1e-6):
    return (a - b).Length < tol


def main():
    doc = App.newDocument("SnapTest")

    boxA = doc.addObject("Part::Box", "BoxA")
    boxA.Length = 20
    boxA.Width = 20
    boxA.Height = 20
    partA = doc.addObject("App::Part", "ComponentA")
    partA.addObject(boxA)

    cylB = doc.addObject("Part::Cylinder", "CylB")
    cylB.Radius = 5
    cylB.Height = 10
    partB = doc.addObject("App::Part", "ComponentB")
    partB.addObject(cylB)
    partB.Placement = App.Placement(App.Vector(100, 50, 0), App.Rotation())

    doc.recompute()

    cpA = objects.create_connection_point(
        doc, partA, App.Vector(20, 10, 10), App.Vector(1, 0, 0), name="CPA"
    )
    cpB_world_pos = partB.Placement.multVec(App.Vector(0, 0, 5))
    cpB = objects.create_connection_point(
        doc, partB, cpB_world_pos, App.Vector(0, 1, 0), name="CPB"
    )
    doc.recompute()

    assert objects.get_parent_part(cpA) is partA, "get_parent_part(cpA) wrong"
    assert objects.get_parent_part(cpB) is partB, "get_parent_part(cpB) wrong"

    moved = snapping.connect(cpA, cpB)
    doc.recompute()
    assert moved is partB, "connect() should move/return partB"

    cpA_global = partA.Placement.multVec(cpA.Placement.Base)
    cpB_global = partB.Placement.multVec(cpB.Placement.Base)
    assert approx_equal_vec(cpA_global, cpB_global), (
        "Points not coincident: %s vs %s" % (cpA_global, cpB_global)
    )

    cpA_dir = (partA.Placement.Rotation * cpA.Placement.Rotation).multVec(App.Vector(0, 0, 1))
    cpB_dir = (partB.Placement.Rotation * cpB.Placement.Rotation).multVec(App.Vector(0, 0, 1))
    assert approx_equal_vec(cpA_dir + cpB_dir, App.Vector(0, 0, 0)), (
        "Axes not opposed: %s vs %s" % (cpA_dir, cpB_dir)
    )

    assert "JIC" in fitting_library.standard_codes()
    assert "-8" in fitting_library.sizes_for("JIC")
    assert cpA.FittingStandard == "UNSET"
    cpA.FittingStandard = "JIC"
    doc.recompute()
    assert "-8" in cpA.getEnumerationsOfProperty("Size")

    joint = objects.create_joint(doc, cpA, cpB, name="TestJoint")
    doc.recompute()
    assert joint.PointA is cpA and joint.PointB is cpB
    assert joint.Shape is not None and not joint.Shape.isNull(), "Joint should have a visible Shape"
    assert joint.Shape.BoundBox.DiagonalLength > 0, "Joint shape should have real extent"
    doc.removeObject(joint.Name)
    doc.recompute()
    assert "TestJoint" not in [o.Name for o in doc.Objects]

    print("ALL CHECKS PASSED")


main()
