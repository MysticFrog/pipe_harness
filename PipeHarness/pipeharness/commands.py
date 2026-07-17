# SPDX-License-Identifier: MIT
"""Toolbar/menu commands for the Pipe Harness workbench.

Each Command class follows FreeCAD's standard pattern (GetResources / Activated /
IsActive), matching Mod/Draft/draftguitools/gui_labels.py, and registers itself
with Gui.addCommand() at import time.
"""
import os

import FreeCAD as App
import FreeCADGui as Gui
import Import

from .qtcompat import QtGui, QtCore
from .dialogs import StraightSegmentDialog, BendSegmentDialog
from . import objects
from . import snapping
from . import joint_propagation
from . import library
from . import library_panel

_ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "Resources", "icons")

QT_TRANSLATE_NOOP = QtCore.QT_TRANSLATE_NOOP  # mark UI strings for translation (no-op at runtime)



def _icon(name):
    return os.path.join(_ICON_DIR, name)


def _same_placement(a, b):
    return a.Base == b.Base and a.Rotation.Q == b.Rotation.Q


def _unit(vector):
    length = vector.Length
    if length < 1e-9:
        return App.Vector(0, 0, 1)
    return App.Vector(vector.x / length, vector.y / length, vector.z / length)


def _position_and_direction(shape_obj, subnames):
    """Combine up to two selected sub-elements (on the same object) into a single
    position + direction: a Face supplies the direction (its normal); the exact
    position prefers a circular edge's true center, then a vertex, then falls
    back to the face's own center of mass. A lone Edge or Vertex still works too.

    Both values come *only* from the shape's own intrinsic geometry (never from
    a picked click point) - shape_obj.Shape is always expressed in shape_obj's
    own local frame, not accounting for its parent App::Part's placement, so
    mixing in a picked point (which reflects the *current*, possibly-moved
    on-screen position) would mix two different reference frames. The caller
    is responsible for converting this local result into world coordinates via
    the component's current Placement.
    """
    faces, edges, verts = [], [], []
    for name in subnames:
        sub = shape_obj.Shape.getElement(name)
        if sub.ShapeType == "Face":
            faces.append(sub)
        elif sub.ShapeType == "Edge":
            edges.append(sub)
        elif sub.ShapeType == "Vertex":
            verts.append(sub)

    direction = None
    position = None

    if faces:
        face = faces[0]
        ref_point = face.CenterOfMass
        try:
            u, v = face.Surface.parameter(ref_point)
            direction = face.normalAt(u, v)
        except Exception:
            direction = face.normalAt(0.5, 0.5)

    if edges:
        edge = edges[0]
        curve = edge.Curve
        if hasattr(curve, "Center"):
            position = curve.Center
            if direction is None and hasattr(curve, "Axis"):
                direction = curve.Axis
        else:
            position = edge.CenterOfMass
            if direction is None:
                try:
                    param = edge.Curve.parameter(position)
                except Exception:
                    param = edge.FirstParameter
                direction = edge.tangentAt(param)

    if position is None and verts:
        vert = verts[0]
        position = App.Vector(vert.X, vert.Y, vert.Z)

    if position is None and faces:
        position = faces[0].CenterOfMass

    if direction is None:
        direction = App.Vector(0, 0, 1)

    return position, _unit(direction)


class ImportSTEPCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("ImportSTEP.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Import STEP as Component"),
            "ToolTip": "Import a STEP file and wrap it as a new component (App::Part)",
        }

    def Activated(self):
        doc = App.ActiveDocument or App.newDocument()
        filename, _filter = QtGui.QFileDialog.getOpenFileName(
            Gui.getMainWindow(), "Import STEP file", "", "STEP files (*.stp *.step)"
        )
        if not filename:
            return

        before = set(o.Name for o in doc.Objects)
        Import.insert(filename, doc.Name)
        doc.recompute()
        new_objs = [o for o in doc.Objects if o.Name not in before]
        top_level = [o for o in new_objs if not any(p in new_objs for p in o.InList)]

        part = doc.addObject("App::Part", "Component")
        part.Label = os.path.splitext(os.path.basename(filename))[0]
        for o in top_level:
            part.addObject(o)

        doc.recompute()
        Gui.SendMsgToActiveView("ViewFit")

    def IsActive(self):
        return True


class AddConnectionPointCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("AddConnectionPoint.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Add Connection Point"),
            "ToolTip": "Select a face on a component (optionally Ctrl+click a vertex or "
                       "circular edge too, for an exact center), then add a hydraulic "
                       "connection point there",
        }

    def Activated(self):
        sel = Gui.Selection.getSelectionEx()
        if len(sel) != 1 or not sel[0].SubElementNames:
            App.Console.PrintError(
                "Select a face (optionally plus a vertex or circular edge for an exact "
                "center) on a single component first.\n"
            )
            return

        selobj = sel[0]
        shape_obj = selobj.Object
        doc = shape_obj.Document

        component = objects.get_parent_part(shape_obj)
        if component is None:
            if shape_obj.TypeId == "App::Part":
                component = shape_obj
            else:
                # A native FreeCAD body (or any object created directly, not
                # imported through Pipe Harness) - wrap it in a component in place
                # so it can host connection points. Existing bodies are grounded
                # by default so new parts snap onto them without shoving them.
                component, wrapped = objects.ensure_component(doc, shape_obj)
                if wrapped:
                    App.Console.PrintMessage(
                        "Pipe Harness: wrapped '%s' in a new grounded component so it can "
                        "host connection points (use the right-click 'Toggle Grounded' if "
                        "you want it movable).\n" % shape_obj.Label
                    )

        local_position, local_direction = _position_and_direction(
            shape_obj, selobj.SubElementNames
        )

        # shape_obj.Shape (and so local_position/local_direction) is expressed in
        # shape_obj's own local frame, which does *not* include its parent
        # App::Part's placement - only shape_obj's own (normally identity)
        # Placement. Compose through both to get true, current world coordinates
        # (matters once the component has been moved/snapped from its original
        # position - using local_position directly here would place the point
        # where that face *used to be*, not where it is now).
        shape_to_world = component.Placement * shape_obj.Placement
        world_position = shape_to_world.multVec(local_position)
        world_direction = shape_to_world.Rotation.multVec(local_direction)

        objects.create_connection_point(doc, component, world_position, world_direction)
        doc.recompute()

    def IsActive(self):
        return App.ActiveDocument is not None


class ConnectPointsCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("ConnectPoints.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Connect Points"),
            "ToolTip": "Select a fixed connection point, then a free connection point (in "
                       "that order), and snap the free component into place",
        }

    def Activated(self):
        selection = Gui.Selection.getSelection()
        points = [o for o in selection if isinstance(getattr(o, "Proxy", None), objects.ConnectionPoint)]
        if len(points) != 2:
            App.Console.PrintError(
                "Select exactly two connection points: the fixed one first, then the free one.\n"
            )
            return

        fixed_point, free_point = points[0], points[1]
        fixed_owner = objects.get_parent_part(fixed_point)
        free_owner = objects.get_parent_part(free_point)

        # A grounded component is a fixed reference and must not be the one that
        # moves. If the user selected the grounded part *second* (as the "free"
        # point), swap the roles so the grounded one stays put and the other
        # part snaps onto it - regardless of click order.
        if (free_owner is not None and objects.is_grounded(free_owner)
                and not (fixed_owner is not None and objects.is_grounded(fixed_owner))):
            fixed_point, free_point = free_point, fixed_point
            fixed_owner, free_owner = free_owner, fixed_owner

        before = App.Placement(free_owner.Placement.Base, free_owner.Placement.Rotation) if free_owner else None
        App.Console.PrintMessage(
            "Pipe Harness Connect Points: fixed='%s' (component '%s'), "
            "free='%s' (component '%s', grounded=%s), free Placement before=%s\n"
            % (
                fixed_point.Name,
                fixed_owner.Name if fixed_owner else "<none - no App::Part parent>",
                free_point.Name,
                free_owner.Name if free_owner else "<none - no App::Part parent>",
                objects.is_grounded(free_owner),
                before,
            )
        )

        doc = fixed_point.Document
        # Suppress joint propagation for the whole snap: moving the free part onto
        # the fixed point must not cascade back through any *existing* joint and
        # shove the assembly being snapped onto.
        try:
            with joint_propagation.suppress():
                moved = snapping.connect(fixed_point, free_point)
                objects.create_joint(doc, fixed_point, free_point)
                doc.recompute()
        except snapping.SnapError as exc:
            App.Console.PrintError(str(exc) + "\n")
            return

        App.Console.PrintMessage(
            "Pipe Harness Connect Points: moved component '%s', Placement after=%s\n"
            % (moved.Name, App.Placement(moved.Placement.Base, moved.Placement.Rotation))
        )
        if before is not None and _same_placement(before, moved.Placement):
            App.Console.PrintWarning(
                "Pipe Harness Connect Points: the free component's Placement did not "
                "actually change - it may already have been correctly positioned, or "
                "the two points may already have been coincident before this click.\n"
            )

    def IsActive(self):
        return App.ActiveDocument is not None


class BreakJointCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("BreakJoint.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Break Joint"),
            "ToolTip": "Select a Joint (the small ball-and-link marker between two mated "
                       "points, in the 3D view or the tree) and remove it - the components "
                       "stay where they are, just no longer tracked as mated",
        }

    def Activated(self):
        selection = Gui.Selection.getSelection()
        joints = [o for o in selection if isinstance(getattr(o, "Proxy", None), objects.Joint)]
        if len(joints) != 1:
            App.Console.PrintError(
                "Select exactly one Joint to break (click its ball-and-link marker in the "
                "3D view, or select it in the model tree).\n"
            )
            return

        doc = joints[0].Document
        doc.removeObject(joints[0].Name)
        doc.recompute()

    def IsActive(self):
        return App.ActiveDocument is not None


class ToggleConnectionPointsCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("ToggleConnectionPoints.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Hide/Show Connection Points"),
            "ToolTip": "Toggle visibility of every connection point in the active document",
        }

    def Activated(self):
        doc = App.ActiveDocument
        points = [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), objects.ConnectionPoint)]
        if not points:
            return

        currently_visible = any(p.ViewObject.Visibility for p in points if p.ViewObject)
        for p in points:
            if p.ViewObject:
                p.ViewObject.Visibility = not currently_visible

    def IsActive(self):
        return App.ActiveDocument is not None


def _resolve_target_hose(doc, selection):
    """Shared by Add Straight/Bend Segment: figure out which Hose to extend from
    the current selection. Returns (hose, error_message); error_message is None
    on success. Selecting a Hose extends it; selecting a connection point (or
    nothing) starts a brand-new, empty hose there (or at the world origin).
    """
    hoses = [o for o in selection if isinstance(getattr(o, "Proxy", None), objects.Hose)]
    points = [o for o in selection if isinstance(getattr(o, "Proxy", None), objects.ConnectionPoint)]

    if len(hoses) > 1 or len(points) > 1 or (hoses and points):
        return None, (
            "Select at most one Hose (to extend) or one connection point (to start a "
            "new hose there) - or nothing, to start a new hose at the world origin.\n"
        )

    if hoses:
        return hoses[0], None

    start_point = points[0] if points else None
    return objects.create_hose(doc, start_point, with_default_segment=False), None


class AddHoseCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("AddHose.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Add Hose"),
            "ToolTip": "Select one connection point to start a hose from (or select "
                       "nothing to start one at the world origin) - a first straight "
                       "segment is added automatically; use Add Straight/Bend Segment "
                       "to extend it further",
        }

    def Activated(self):
        selection = [o for o in Gui.Selection.getSelection() if isinstance(getattr(o, "Proxy", None), objects.ConnectionPoint)]
        if len(selection) > 1:
            App.Console.PrintError(
                "Select at most one connection point to start the hose from (or none, "
                "to start at the world origin).\n"
            )
            return

        start_point = selection[0] if selection else None
        doc = App.ActiveDocument or App.newDocument()
        objects.create_hose(doc, start_point)
        doc.recompute()

    def IsActive(self):
        return True


class AddStraightSegmentCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("AddStraightSegment.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Add Straight Segment"),
            "ToolTip": "Select a Hose to extend it (or a connection point to start a new "
                       "one there, or nothing to start one at the world origin), then fill "
                       "in the straight length for the new segment - appended to the open "
                       "end of the selected hose",
        }

    def Activated(self):
        doc = App.ActiveDocument or App.newDocument()
        hose, error = _resolve_target_hose(doc, Gui.Selection.getSelection())
        if error:
            App.Console.PrintError(error)
            return

        # The dialog creates the segment immediately (with default values) and
        # live-updates it as fields change, so there's a preview before OK is
        # pressed; it removes the segment itself if the dialog is cancelled.
        # Shown non-modally (not run_modal) so the 3D view stays interactive
        # while it's open - the reference is kept on self so Qt doesn't garbage
        # collect the window the moment Activated() returns.
        self._dialog = StraightSegmentDialog(hose, Gui.getMainWindow())
        self._dialog.setModal(False)
        self._dialog.show()

    def IsActive(self):
        return True


class AddBendSegmentCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("AddBendSegment.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Add Bend Segment"),
            "ToolTip": "Select a Hose to extend it (or a connection point to start a new "
                       "one there, or nothing to start one at the world origin), then fill "
                       "in the bend radius, swept angle, and yaw for the new bend - appended "
                       "to the open end of the selected hose (Pitch defaults to 0; edit it "
                       "afterward on the new PipeBend object if a specific bend plane is "
                       "needed)",
        }

    def Activated(self):
        doc = App.ActiveDocument or App.newDocument()
        hose, error = _resolve_target_hose(doc, Gui.Selection.getSelection())
        if error:
            App.Console.PrintError(error)
            return

        self._dialog = BendSegmentDialog(hose, Gui.getMainWindow())
        self._dialog.setModal(False)
        self._dialog.show()

    def IsActive(self):
        return True


class ExportToLibraryCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("ExportToLibrary.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Export to Parts Library"),
            "ToolTip": "Save the selected component (with its connection points) into "
                       "the local parts library",
        }

    def Activated(self):
        selection = Gui.Selection.getSelection()
        parts = [o for o in selection if o.TypeId == "App::Part"]
        if len(parts) != 1:
            App.Console.PrintError("Select exactly one component (App::Part) to export.\n")
            return
        part = parts[0]

        panel = library_panel.get_or_create_panel()
        dialog = library_panel.ExportTargetDialog(
            part.Label, panel.current_relative_folder(), Gui.getMainWindow()
        )
        if dialog.exec_() != QtGui.QDialog.Accepted:
            return
        name, folder = dialog.values()
        if not name:
            App.Console.PrintError("Pipe Harness: a part name is required to export.\n")
            return

        try:
            path = library.export_part(part, name, folder)
        except Exception as exc:
            App.Console.PrintError("Pipe Harness: could not export '%s' (%s)\n" % (part.Label, exc))
            return
        App.Console.PrintMessage("Pipe Harness: exported '%s' to %s\n" % (part.Label, path))
        panel.refresh()

    def IsActive(self):
        return len(Gui.Selection.getSelection()) > 0


class ToggleLibraryPanelCommand:
    def GetResources(self):
        return {
            "Pixmap": _icon("PartsLibrary.svg"),
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Show/Hide Parts Library"),
            "ToolTip": "Show or hide the Pipe Harness Parts Library panel",
        }

    def Activated(self):
        panel = library_panel.get_or_create_panel()
        panel.setVisible(not panel.isVisible())
        if panel.isVisible():
            panel.raise_()

    def IsActive(self):
        return True


class ToggleGroundedCommand:
    def GetResources(self):
        return {
            "MenuText": QT_TRANSLATE_NOOP("PipeHarness", "Toggle Grounded"),
            "ToolTip": "Ground/unground the selected component(s). A grounded component is "
                       "a fixed reference: Connect Points snaps other parts onto it without "
                       "moving it, and it isn't dragged when a jointed neighbour moves.",
        }

    def Activated(self):
        parts = [o for o in Gui.Selection.getSelection() if o.TypeId == "App::Part"]
        if not parts:
            App.Console.PrintError(
                "Select one or more components (App::Part) to toggle grounding.\n"
            )
            return
        for part in parts:
            objects.set_grounded(part, not objects.is_grounded(part))
            App.Console.PrintMessage(
                "Pipe Harness: '%s' grounded = %s\n" % (part.Label, objects.is_grounded(part))
            )
        if App.ActiveDocument:
            App.ActiveDocument.recompute()

    def IsActive(self):
        return App.ActiveDocument is not None


Gui.addCommand("PipeHarness_ImportSTEP", ImportSTEPCommand())
Gui.addCommand("PipeHarness_AddConnectionPoint", AddConnectionPointCommand())
Gui.addCommand("PipeHarness_ConnectPoints", ConnectPointsCommand())
Gui.addCommand("PipeHarness_BreakJoint", BreakJointCommand())
Gui.addCommand("PipeHarness_ToggleConnectionPoints", ToggleConnectionPointsCommand())
Gui.addCommand("PipeHarness_AddHose", AddHoseCommand())
Gui.addCommand("PipeHarness_AddStraightSegment", AddStraightSegmentCommand())
Gui.addCommand("PipeHarness_AddBendSegment", AddBendSegmentCommand())
Gui.addCommand("PipeHarness_ExportToLibrary", ExportToLibraryCommand())
Gui.addCommand("PipeHarness_ToggleLibraryPanel", ToggleLibraryPanelCommand())
Gui.addCommand("PipeHarness_ToggleGrounded", ToggleGroundedCommand())
