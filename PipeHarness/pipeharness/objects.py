"""Custom document objects for the Pipe Harness workbench.

ConnectionPoint - a hydraulic port marker (Part::FeaturePython) placed on an
imported component, following the Draft ``Point`` FeaturePython pattern
(Mod/Draft/draftobjects/point.py).

Joint - a record (Part::FeaturePython) of a mate between two ConnectionPoints,
drawn as a small connector glyph between them so it has a real presence in the
3D view and can be selected there directly (not just via the tree).

Hose - a flexible hose/pipe run (Part::FeaturePython) starting at a
ConnectionPoint (or the world origin), built from an ordered chain of
PipeStraight/PipeBend child objects (see Hose.Segments) swept into a solid
tube. Each child is its own separate document object with only the
properties relevant to its type, nested under the Hose in the Model tree via
ViewProviderHose.claimChildren().
"""
import math

import FreeCAD as App
import Part

from . import fitting_library

if App.GuiUp:
    import FreeCADGui as Gui


GENDERS = ["Unset", "Male", "Female"]

# Local-space marker: a small cone/dart pointing along +Z, representing the
# port's outward axis direction. Size is in mm.
_MARKER_LENGTH = 8.0
_MARKER_RADIUS = 2.0

_JOINT_RADIUS = 1.5

_DEFAULT_SEGMENT_LENGTH = 50.0
_DEFAULT_BEND_RADIUS = 15.0
_DEFAULT_DIAMETER = 12.0
_DEFAULT_SWEPT_ANGLE = 0.0  # 0 = dead straight, no bend; 180 = a full U-turn

_DEFAULT_DASH_SIZE = "-8"


def get_parent_part(obj):
    """Return the App::Part that directly contains obj in its Group, or None."""
    for parent in obj.InList:
        if parent.TypeId == "App::Part" and obj in parent.Group:
            return parent
    return None


def is_grounded(part):
    """True if `part` (an App::Part component) is marked grounded - a fixed
    reference that Connect Points snaps other parts onto without moving it, and
    that joint propagation never drags along when a neighbour moves.
    """
    return bool(part is not None and getattr(part, "Grounded", False))


def set_grounded(part, value=True):
    """Ground/unground a component, adding the (dynamic, persistent) Grounded
    property the first time. No-op for anything that isn't an App::Part.
    """
    if part is None or part.TypeId != "App::Part":
        return
    if not hasattr(part, "Grounded"):
        part.addProperty(
            "App::PropertyBool", "Grounded", "PipeHarness",
            "When on, this component is a fixed reference: Connect Points snaps other "
            "parts onto it without moving it, and it isn't dragged along when a jointed "
            "neighbour moves."
        )
    part.Grounded = bool(value)


def ensure_component(doc, obj, ground_if_wrapped=True):
    """The App::Part component that should own a connection point placed on `obj`.

    If `obj` is already an App::Part, or a shape inside one, that component is
    returned untouched. If `obj` is a plain body at the document root (a native
    FreeCAD Part::Box / Part::Feature / PartDesign Body etc. that was never
    imported through Pipe Harness), it is wrapped in a new App::Part *in place*
    (the App::Part starts at identity, so the body doesn't visibly move) so it
    can host connection points and take part in snapping. Such a wrapped
    existing body is grounded by default (see is_grounded).

    Returns (component, wrapped) where `wrapped` is True only if a new App::Part
    was just created.
    """
    if obj.TypeId == "App::Part":
        return obj, False
    parent = get_parent_part(obj)
    if parent is not None:
        return parent, False

    part = doc.addObject("App::Part", "Component")
    part.Label = getattr(obj, "Label", None) or obj.Name
    part.addObject(obj)
    if ground_if_wrapped:
        set_grounded(part, True)
    doc.recompute()
    return part, True


def global_placement(connection_point):
    """The world-space Placement of a ConnectionPoint, composing its own Placement
    (defined relative to its parent component) with that parent App::Part's Placement.
    """
    parent = get_parent_part(connection_point)
    if parent is None:
        return connection_point.Placement
    return parent.Placement * connection_point.Placement


class ConnectionPoint:
    """Proxy for a Part::FeaturePython representing a hydraulic port."""

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyEnumeration", "FittingStandard", "PipeHarness",
            "Hydraulic fitting standard for this port"
        )
        obj.FittingStandard = fitting_library.standard_codes()
        obj.FittingStandard = "UNSET"

        obj.addProperty(
            "App::PropertyEnumeration", "Size", "PipeHarness",
            "Fitting size for the selected standard"
        )
        obj.Size = fitting_library.sizes_for("UNSET")

        obj.addProperty(
            "App::PropertyEnumeration", "Gender", "PipeHarness",
            "Male/female fitting gender"
        )
        obj.Gender = GENDERS
        obj.Gender = "Unset"

        obj.addProperty(
            "App::PropertyBool", "Reversed", "PipeHarness",
            "Reverse this point's outward normal (its +Z facing axis). Toggle it "
            "with 'Flip Normal' in the right-click menu; for an auto-managed hose "
            "anchor this is what makes the flip survive the next recompute."
        )
        obj.Reversed = False

    def onChanged(self, obj, prop):
        if prop == "FittingStandard" and hasattr(obj, "Size"):
            sizes = fitting_library.sizes_for(obj.FittingStandard)
            if list(obj.getEnumerationsOfProperty("Size")) != sizes:
                obj.Size = sizes

    def execute(self, obj):
        cone = Part.makeCone(_MARKER_RADIUS, 0.0, _MARKER_LENGTH)
        shaft = Part.makeCylinder(_MARKER_RADIUS * 0.35, _MARKER_LENGTH * 0.6)
        obj.Shape = Part.makeCompound([cone, shaft])

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ViewProviderConnectionPoint:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = (0.95, 0.55, 0.05)

    def getIcon(self):
        return _icon_path("ConnectionPoint.svg")

    def attach(self, vobj):
        # Deliberately store nothing: keeping a reference to vobj (or its
        # Object) on the proxy makes FreeCAD choke serializing the proxy's
        # __dict__ to JSON on save/insert. This ViewProvider doesn't need it.
        pass

    def setupContextMenu(self, vobj, menu):
        # Adds "Flip Normal" to this point's right-click menu, in both the model
        # tree and the 3D view. menu.addAction returns a QAction regardless of
        # PySide2/PySide6 (QAction itself moved to QtGui under Qt6, but going
        # through the QMenu avoids importing it directly).
        action = menu.addAction("Flip Normal")
        # The bound object is captured now rather than read from self at click
        # time, so this stays correct even if the same ViewProvider instance is
        # reused; triggered() passes a checked bool we don't care about.
        action.triggered.connect(lambda *a, o=vobj.Object: flip_connection_point(o))

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def flip_connection_point(cp):
    """Reverse a ConnectionPoint's outward normal (its local +Z axis) - what
    another port mates against. Flips the Placement directly for an immediate
    result, and also toggles the Reversed flag so the change survives the next
    recompute for the auto-managed hose anchors (whose Placement is otherwise
    overwritten from the hose geometry every cycle - see _update_anchor); for
    an ordinary user-placed point the flag is just carried along, harmless.

    Wrapped in its own transaction so a single Ctrl+Z reverts the flip.
    """
    doc = cp.Document
    flip = App.Rotation(App.Vector(1, 0, 0), 180)
    if doc is not None:
        doc.openTransaction("Flip connection point normal")
    if hasattr(cp, "Reversed"):
        cp.Reversed = not cp.Reversed
    cp.Placement = App.Placement(cp.Placement.Base, cp.Placement.Rotation * flip)
    if doc is not None:
        doc.commitTransaction()
        doc.recompute()


class Joint:
    """Proxy for a Part::FeaturePython recording a mate between two ConnectionPoints,
    drawn as a small dumbbell-shaped connector between them so it's visible and
    directly clickable in the 3D view (it has no home component of its own, so its
    Shape is built in world/global coordinates rather than a local frame).

    Convention: PointB's component was the one moved to mate with PointA
    (PointA's component is treated as the fixed reference).
    """

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyLinkGlobal", "PointA", "PipeHarness",
            "Fixed-side connection point"
        )
        obj.addProperty(
            "App::PropertyLinkGlobal", "PointB", "PipeHarness",
            "Free-side connection point that was moved to mate"
        )
        # Shape is built directly in world coordinates from PointA/PointB (see
        # execute() below), so the object's own Placement is never used - hide it
        # rather than leave a property visible that silently does nothing if edited.
        obj.setEditorMode("Placement", 2)

    def execute(self, obj):
        if not obj.PointA or not obj.PointB:
            return
        pos_a = global_placement(obj.PointA).Base
        pos_b = global_placement(obj.PointB).Base
        ball_a = Part.makeSphere(_JOINT_RADIUS * 1.4, pos_a)
        ball_b = Part.makeSphere(_JOINT_RADIUS * 1.4, pos_b)
        gap = pos_b - pos_a
        if gap.Length > 1e-6:
            link = Part.makeCylinder(_JOINT_RADIUS, gap.Length, pos_a, gap)
            obj.Shape = Part.makeCompound([ball_a, ball_b, link])
        else:
            obj.Shape = Part.makeCompound([ball_a, ball_b])

    def onChanged(self, obj, prop):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ViewProviderJoint:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = (0.2, 0.6, 0.3)

    def getIcon(self):
        return _icon_path("Joint.svg")

    def attach(self, vobj):
        # Deliberately store nothing: keeping a reference to vobj (or its
        # Object) on the proxy makes FreeCAD choke serializing the proxy's
        # __dict__ to JSON on save/insert. This ViewProvider doesn't need it.
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class PipeStraight:
    """Proxy for an App::FeaturePython representing one straight run of a Hose -
    a child object, so it shows as its own entry in the Model tree (nested under
    its Hose via ViewProviderHose.claimChildren()) with just the one property
    relevant to a straight run. Has no Shape of its own; the parent Hose reads
    Length directly when building its swept tube.
    """

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyLength", "Length", "PipeHarness",
            "Straight (tangent) length of this run, not including adjacent bends"
        )
        obj.Length = _DEFAULT_SEGMENT_LENGTH

    def onChanged(self, obj, prop):
        pass

    def execute(self, obj):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ViewProviderPipeStraight:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return _icon_path("PipeStraight.svg")

    def attach(self, vobj):
        # Deliberately store nothing: keeping a reference to vobj (or its
        # Object) on the proxy makes FreeCAD choke serializing the proxy's
        # __dict__ to JSON on save/insert. This ViewProvider doesn't need it.
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class PipeBend:
    """Proxy for an App::FeaturePython representing one bend of a Hose - a child
    object, so it shows as its own entry in the Model tree (nested under its Hose
    via ViewProviderHose.claimChildren()) with just the properties relevant to a
    bend. Has no Shape of its own; the parent Hose reads these directly when
    building its swept tube.
    """

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyLength", "Radius", "PipeHarness",
            "Radius of this bend"
        )
        obj.Radius = _DEFAULT_BEND_RADIUS
        obj.addProperty(
            "App::PropertyFloat", "SweptAngle", "PipeHarness",
            "Swept angle (degrees) of this bend - 0 is dead straight, 180 is a "
            "full U-turn; this is how far the bend actually turns, matching how "
            "tube-bending specs usually describe a bend"
        )
        obj.SweptAngle = _DEFAULT_SWEPT_ANGLE
        obj.addProperty(
            "App::PropertyFloat", "Yaw", "PipeHarness",
            "Yaw (degrees) choosing which axis this bend leans around, relative to "
            "the previous heading"
        )
        obj.addProperty(
            "App::PropertyFloat", "Pitch", "PipeHarness",
            "Pitch (degrees) choosing which axis this bend leans around, applied "
            "after Yaw"
        )
        obj.addProperty(
            "App::PropertyFloat", "Roll", "PipeHarness",
            "Roll (degrees) twisting the heading frame about the direction of "
            "travel, applied after the bend - doesn't bend the path itself, but "
            "re-orients the reference frame later bends lean relative to"
        )

    def onChanged(self, obj, prop):
        pass

    def execute(self, obj):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ViewProviderPipeBend:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return _icon_path("PipeBend.svg")

    def attach(self, vobj):
        # Deliberately store nothing: keeping a reference to vobj (or its
        # Object) on the proxy makes FreeCAD choke serializing the proxy's
        # __dict__ to JSON on save/insert. This ViewProvider doesn't need it.
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class Hose:
    """Proxy for a Part::FeaturePython representing a flexible hose/pipe run.

    Starts at a ConnectionPoint - or, if StartPoint is left unset, at the
    world origin (0,0,0) facing +Z, so a run can be sketched out before any
    component/port exists. Built from an ordered list of segments (Segments -
    each one a separate PipeStraight or PipeBend child object, so each shows up
    as its own entry in the Model tree with only the properties relevant to its
    type), swept into a solid tube of the given Diameter.

    Both ends are tracked by their own auto-managed ConnectionPoints -
    StartAnchor and EndAnchor - neither parented inside any App::Part, but
    still usable as the fixed side of a Connect Points mate, so another
    component's port can be attached at either end. Their Placement is
    overwritten on every recompute to track the hose's actual current
    geometry (whichever end things were added/edited), and if something is
    already mated to one of them (via a Joint), that mate is re-applied too -
    so a fitting attached to a hose's end follows along as the hose grows.
    """

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyLinkGlobal", "StartPoint", "PipeHarness",
            "Connection point this hose starts from (leave unset to start at the "
            "world origin, facing +Z)"
        )
        obj.addProperty(
            "App::PropertyLinkGlobal", "StartAnchor", "PipeHarness",
            "Auto-managed connection point tracking this hose's start - its "
            "Placement is overwritten on every recompute, don't hand-edit it"
        )
        obj.addProperty(
            "App::PropertyLinkGlobal", "EndAnchor", "PipeHarness",
            "Auto-managed connection point tracking this hose's open end - its "
            "Placement is overwritten on every recompute, don't hand-edit it"
        )
        obj.addProperty(
            "App::PropertyLinkList", "Segments", "PipeHarness",
            "Ordered chain of PipeStraight/PipeBend child objects making up this hose"
        )
        obj.addProperty(
            "App::PropertyLength", "Diameter", "PipeHarness",
            "Outer diameter of the hose"
        )
        obj.Diameter = _DEFAULT_DIAMETER
        obj.addProperty(
            "App::PropertyBool", "HydraulicHose", "PipeHarness",
            "Treat this as a hydraulic hose: size Diameter from DashSize instead "
            "of a raw value"
        )
        obj.HydraulicHose = False
        obj.addProperty(
            "App::PropertyEnumeration", "DashSize", "PipeHarness",
            "SAE dash size - only used to set Diameter while HydraulicHose is on"
        )
        obj.DashSize = fitting_library.dash_sizes()
        obj.DashSize = _DEFAULT_DASH_SIZE
        obj.setEditorMode("DashSize", 2)

    def onChanged(self, obj, prop):
        if prop == "HydraulicHose" and hasattr(obj, "DashSize"):
            obj.setEditorMode("DashSize", 0 if obj.HydraulicHose else 2)
            if obj.HydraulicHose:
                obj.Diameter = fitting_library.dash_size_od_mm(obj.DashSize)
        elif prop == "DashSize" and getattr(obj, "HydraulicHose", False):
            obj.Diameter = fitting_library.dash_size_od_mm(obj.DashSize)

    def execute(self, obj):
        segments = list(obj.Segments)
        if not segments:
            return

        # This is the *local* start frame - i.e. relative to obj.Placement, not
        # the true world frame - because the Shape built from it is positioned
        # by FreeCAD's own Placement*Shape compositing (obj.Placement is applied
        # on top automatically at render time). When StartPoint is set,
        # obj.Placement is expected to stay at identity (the port supplies the
        # real position instead), so local and world coincide there anyway.
        if obj.StartPoint:
            local_start_gp = global_placement(obj.StartPoint)
        else:
            local_start_gp = App.Placement(App.Vector(0, 0, 0), App.Rotation())

        try:
            edges, end_pos, first_dir = _walk_segments(local_start_gp, segments)
            path = Part.Wire(edges)
        except Exception as exc:
            App.Console.PrintWarning(
                "Hose '%s': could not route segments (%s).\n" % (obj.Name, exc)
            )
            return

        last_dir = _segment_end_direction(local_start_gp, segments)

        # StartAnchor/EndAnchor are independent document objects, not children
        # whose display is auto-composited with obj.Placement - so unlike the
        # Shape above, their Placement needs obj.Placement folded in explicitly,
        # or they'd stay behind when a free-floating hose is moved by editing
        # its own Placement.
        world_start = obj.Placement.multVec(local_start_gp.Base)
        world_end = obj.Placement.multVec(end_pos)
        world_first_dir = obj.Placement.Rotation.multVec(first_dir)
        world_last_dir = obj.Placement.Rotation.multVec(last_dir)
        # An anchor's +Z is its *outward* facing direction (what another port
        # mates against - Connect Points opposes the two +Z axes). At the open
        # (end) anchor, "outward" is the direction of travel. At the start
        # anchor it's the opposite: travel points *into* the hose there, so the
        # outward face is -travel. Without this negation the start anchor faced
        # backwards and anything snapped onto it pointed the wrong way.
        _update_anchor(obj, obj.StartAnchor, world_start, world_first_dir * -1.0)
        _update_anchor(obj, obj.EndAnchor, world_end, world_last_dir)

        diameter = obj.Diameter.Value if hasattr(obj.Diameter, "Value") else obj.Diameter
        profile = Part.Wire([Part.makeCircle(diameter / 2.0, local_start_gp.Base, first_dir)])

        try:
            shape = path.makePipeShell([profile], True, False)
        except Exception as exc:
            App.Console.PrintWarning(
                "Hose '%s': pipe sweep failed (%s); showing centerline path instead.\n"
                % (obj.Name, exc)
            )
            shape = path

        obj.Shape = shape

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ViewProviderHose:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = (0.15, 0.15, 0.15)

    def getIcon(self):
        return _icon_path("Hose.svg")

    def attach(self, vobj):
        # Store only JSON-serializable identifiers, never the vobj/object
        # itself: FreeCAD serializes a Python ViewProvider proxy's __dict__ to
        # JSON when the document is saved or an object is copied/inserted, and a
        # stored ViewProviderDocumentObject/DocumentObject isn't serializable -
        # which spams "PropertyPythonObject::toString(): failed ... not JSON
        # serializable" on every save/insert. attach() re-runs on restore, so
        # these names are always repopulated before claimChildren() needs them.
        self.object_name = vobj.Object.Name
        self.document_name = vobj.Object.Document.Name

    def _object(self):
        name = getattr(self, "object_name", None)
        doc_name = getattr(self, "document_name", None)
        if not name or not doc_name:
            return None
        try:
            return App.getDocument(doc_name).getObject(name)
        except Exception:
            return None

    def claimChildren(self):
        obj = self._object()
        if obj is None:
            return []
        children = list(obj.Segments)
        if obj.StartAnchor:
            children.append(obj.StartAnchor)
        if obj.EndAnchor:
            children.append(obj.EndAnchor)
        return children

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def _update_anchor(hose, anchor, position, direction):
    """Update one of a Hose's auto-managed anchor connection points (StartAnchor/
    EndAnchor) to the given world position/direction, and re-apply any existing
    mate to it - so if a fitting is already connected to this end (via a Joint,
    with this anchor as the fixed side), it follows along when the hose's
    geometry changes (e.g. a new segment is added, moving the open end).
    """
    if not anchor:
        return
    # Honor a user's Flip Normal on this auto-managed anchor: its Placement is
    # recomputed from the hose geometry every cycle, so the flip only sticks if
    # re-applied here from the persisted Reversed flag.
    if getattr(anchor, "Reversed", False):
        direction = direction * -1.0
    anchor.Placement = App.Placement(position, App.Rotation(App.Vector(0, 0, 1), direction))
    # Confirms the anchor is fully settled after this deliberate side-effect
    # write, so FreeCAD's recompute bookkeeping doesn't flag it as an
    # unexpected leftover "touched" object once this recompute pass ends.
    anchor.purgeTouched()

    from . import snapping  # deferred import: snapping.py imports from this module
    doc = hose.Document
    for other in doc.Objects:
        if isinstance(getattr(other, "Proxy", None), Joint) and other.PointA is anchor and other.PointB:
            try:
                moved = snapping.connect(other.PointA, other.PointB)
                moved.purgeTouched()
            except snapping.SnapError:
                pass


def _walk_segments(start_gp, segments):
    """Walk an ordered list of PipeStraight/PipeBend children, building the swept
    path's edges. Returns (edges, end_pos, first_dir): end_pos is where the last
    segment finishes (the open end of the hose), first_dir is the heading at the
    very start (used to orient the sweep profile).
    """
    frame = start_gp.Rotation
    current = start_gp.Base
    first_dir = frame.multVec(App.Vector(0, 0, 1))
    edges = []

    for seg in segments:
        proxy = getattr(seg, "Proxy", None)
        if isinstance(proxy, PipeStraight):
            direction = frame.multVec(App.Vector(0, 0, 1))
            length = seg.Length.Value if hasattr(seg.Length, "Value") else seg.Length
            end = current + direction * length
            edges.append(Part.LineSegment(current, end).toShape())
            current = end
        elif isinstance(proxy, PipeBend):
            old_dir = frame.multVec(App.Vector(0, 0, 1))
            frame = _apply_bend(frame, seg.Yaw, seg.Pitch, seg.Roll, seg.SweptAngle)
            new_dir = frame.multVec(App.Vector(0, 0, 1))
            radius = seg.Radius.Value if hasattr(seg.Radius, "Value") else seg.Radius
            if radius > 1e-6:
                arc_edge, current = _tangent_arc(current, radius, old_dir, new_dir)
                if arc_edge is not None:
                    edges.append(arc_edge)

    return edges, current, first_dir


def _segment_end_direction(start_gp, segments):
    """The heading direction at the very end of the segment chain."""
    frame = start_gp.Rotation
    for seg in segments:
        proxy = getattr(seg, "Proxy", None)
        if isinstance(proxy, PipeBend):
            frame = _apply_bend(frame, seg.Yaw, seg.Pitch, seg.Roll, seg.SweptAngle)
    return frame.multVec(App.Vector(0, 0, 1))


def _apply_bend(frame, yaw_deg, pitch_deg, roll_deg, swept_angle_deg):
    """Apply one bend to a heading frame (an App.Rotation whose local +Z is the
    direction of travel, +Y is "up", +X is "right"), in the standard tube-bending
    sense: Yaw and Pitch pick the axis the bend leans around (by tilting the
    frame's "up" reference - they don't themselves turn the heading), then the
    heading is rotated about that chosen axis by SweptAngle (0 = straight
    through, 180 = a full reversal - how far the bend actually turns), and
    finally Roll twists the resulting frame about the *new* heading - this
    doesn't bend the path at all, it only re-orients the reference frame later
    segments' Yaw/Pitch lean relative to.
    """
    axis_frame = frame
    if abs(yaw_deg) > 1e-9:
        axis = axis_frame.multVec(App.Vector(0, 0, 1))
        axis_frame = App.Rotation(axis, yaw_deg) * axis_frame
    if abs(pitch_deg) > 1e-9:
        axis = axis_frame.multVec(App.Vector(1, 0, 0))
        axis_frame = App.Rotation(axis, pitch_deg) * axis_frame
    bend_axis = axis_frame.multVec(App.Vector(0, 1, 0))

    new_frame = frame
    if abs(swept_angle_deg) > 1e-9:
        new_frame = App.Rotation(bend_axis, swept_angle_deg) * frame

    if abs(roll_deg) > 1e-9:
        roll_axis = new_frame.multVec(App.Vector(0, 0, 1))
        new_frame = App.Rotation(roll_axis, roll_deg) * new_frame

    return new_frame


def _tangent_arc(start, radius, dir_in, dir_out):
    """The tangent arc of the given radius bending from dir_in to dir_out, starting
    exactly at `start` (which is already the first tangent point - the straight
    segment's own length is untouched by the bend, per the tube-routing convention
    that segment length is measured to the start of the bend, not through it).

    Returns (edges, end_point) where edges is a list of Part edges (a line to make
    the imaginary sharp corner reachable is not included - only the arc itself) and
    end_point is the second tangent point, where the next straight segment begins.
    Returns (None, start) if the turn is degenerate (straight through, or a
    directly-reversed dead end) and no arc is needed.
    """
    ray1 = dir_in * -1.0
    ray2 = dir_out

    cos_phi = max(-1.0, min(1.0, ray1.dot(ray2)))
    phi = math.acos(cos_phi)
    if phi < 1e-6 or phi > math.pi - 1e-6:
        return None, start

    trim = radius / math.tan(phi / 2.0)
    vertex = start + dir_in * trim
    tangent_out = vertex + dir_out * trim

    bisector = ray1 + ray2
    if bisector.Length < 1e-9:
        return None, start
    bisector = bisector * (1.0 / bisector.Length)
    # The arc's center O sits at vertex + bisector*(radius/sin(phi/2)); the correct
    # arc-midpoint (on the near/minor-arc side, not the far/major-arc side) is the
    # point on the circle closest to the vertex, i.e. O offset back by radius.
    far_point = vertex + bisector * (radius / math.sin(phi / 2.0) - radius)

    return Part.Arc(start, far_point, tangent_out).toShape(), tangent_out


def _icon_path(name):
    import os
    return os.path.join(os.path.dirname(__file__), "..", "Resources", "icons", name)


def create_connection_point(doc, component_part, position, direction, name="ConnectionPoint"):
    """Create a ConnectionPoint as a child of component_part at position, oriented so its
    local +Z axis points along `direction` (both App.Vector, in the document's global frame;
    they are converted to component_part's local frame automatically via its Placement).
    """
    obj = doc.addObject("Part::FeaturePython", name)
    ConnectionPoint(obj)
    if App.GuiUp:
        ViewProviderConnectionPoint(obj.ViewObject)

    local_position = component_part.Placement.inverse().multVec(position)
    local_rotation = component_part.Placement.Rotation.inverted() * App.Rotation(App.Vector(0, 0, 1), direction)
    obj.Placement = App.Placement(local_position, local_rotation)

    component_part.addObject(obj)
    return obj


def create_free_connection_point(doc, position, direction, name="ConnectionPoint"):
    """Create a ConnectionPoint that is *not* parented inside any App::Part component
    - used for a Hose's own StartAnchor/EndAnchor. Its Placement directly *is* the
    world placement (get_parent_part() returns None for it, so global_placement()
    already handles this correctly with no local-to-parent conversion needed).
    """
    obj = doc.addObject("Part::FeaturePython", name)
    ConnectionPoint(obj)
    if App.GuiUp:
        ViewProviderConnectionPoint(obj.ViewObject)
    obj.Placement = App.Placement(position, App.Rotation(App.Vector(0, 0, 1), direction))
    return obj


def create_joint(doc, point_a, point_b, name="Joint"):
    obj = doc.addObject("Part::FeaturePython", name)
    Joint(obj)
    if App.GuiUp:
        ViewProviderJoint(obj.ViewObject)
    obj.PointA = point_a
    obj.PointB = point_b
    return obj


def create_hose(doc, start_point=None, name="Hose", with_default_segment=True):
    """Create a Hose. If start_point is None, it starts at the world origin
    facing +Z instead of at a ConnectionPoint - lets a run be sketched out
    before any component/port exists. If with_default_segment is False, it
    starts with no segments at all (used by the "Add Straight/Bend Segment"
    commands, which append the first real segment themselves right after
    creating it).
    """
    obj = doc.addObject("Part::FeaturePython", name)
    Hose(obj)
    if App.GuiUp:
        ViewProviderHose(obj.ViewObject)
    if start_point is not None:
        obj.StartPoint = start_point
    obj.StartAnchor = create_free_connection_point(
        doc, App.Vector(0, 0, 0), App.Vector(0, 0, 1), name="%s_Start" % name
    )
    obj.EndAnchor = create_free_connection_point(
        doc, App.Vector(0, 0, 0), App.Vector(0, 0, 1), name="%s_End" % name
    )
    if with_default_segment:
        add_straight_to_hose(obj, _DEFAULT_SEGMENT_LENGTH)
    return obj


def add_straight_to_hose(hose, length, name="PipeStraight"):
    """Append a new straight run to the open (tail) end of a Hose's segment chain."""
    doc = hose.Document
    obj = doc.addObject("App::FeaturePython", name)
    PipeStraight(obj)
    if App.GuiUp:
        ViewProviderPipeStraight(obj.ViewObject)
    obj.Length = length

    segments = list(hose.Segments)
    segments.append(obj)
    hose.Segments = segments
    return obj


def add_bend_to_hose(hose, radius, swept_angle, yaw, pitch, roll, name="PipeBend"):
    """Append a new bend to the open (tail) end of a Hose's segment chain."""
    doc = hose.Document
    obj = doc.addObject("App::FeaturePython", name)
    PipeBend(obj)
    if App.GuiUp:
        ViewProviderPipeBend(obj.ViewObject)
    obj.Radius = radius
    obj.SweptAngle = swept_angle
    obj.Yaw = yaw
    obj.Pitch = pitch
    obj.Roll = roll

    segments = list(hose.Segments)
    segments.append(obj)
    hose.Segments = segments
    return obj
