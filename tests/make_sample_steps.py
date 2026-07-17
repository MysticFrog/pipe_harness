"""Generates two placeholder STEP files for manually testing the workbench in the
FreeCAD GUI (Import / AddConnectionPoint / Connect / Break). These are simple
primitives standing in for real fitting models, not actual hydraulic parts.

Run via: FreeCADCmd.exe make_sample_steps.py
"""
import os

import FreeCAD as App
import Part

out_dir = os.path.join(os.path.dirname(__file__), "..", "samples")
os.makedirs(out_dir, exist_ok=True)

doc = App.newDocument("Samples")

block = Part.makeBox(30, 30, 30)
block_obj = doc.addObject("Part::Feature", "FittingBlock")
block_obj.Shape = block
Part.export([block_obj], os.path.join(out_dir, "fitting_block.step"))

cyl = Part.makeCylinder(10, 40)
cyl_obj = doc.addObject("Part::Feature", "FittingCylinder")
cyl_obj.Shape = cyl
Part.export([cyl_obj], os.path.join(out_dir, "fitting_cylinder.step"))

print("Wrote sample STEP files to", out_dir)
