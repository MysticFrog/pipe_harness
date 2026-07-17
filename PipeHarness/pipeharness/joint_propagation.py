"""Propagates a moved component's (or free-floating hose's) Placement change
through any Joint connecting it to other components/hoses, so a whole jointed
assembly moves together instead of only the one piece you directly moved or
dragged - nothing should be treated as permanently "grounded" just because it
happened to be the fixed side of some earlier Connect Points mate.

Also compensates for the common case of moving the *wrong* object: clicking a
visible solid in the 3D view (or expanding a Component in the tree) selects
the underlying shape object (e.g. a Part::Feature/Part::Box), not the
App::Part wrapping it - editing that inner object's own Placement moves the
geometry but, without this, would silently leave its sibling connection
points (and anything jointed through them) behind, since a ConnectionPoint's
own Placement is calibrated once at creation time relative to the *component*
(App::Part), not the shape inside it. See `_classify()` below.

Registered via App.addDocumentObserver only while the Pipe Harness workbench is
the active one (added in InitGui.py's Activated(), removed in Deactivated()), so
it has no effect on other documents/workbenches when Pipe Harness isn't in use.
Because changes aren't tracked while it's inactive, resync() re-seeds the
placement baselines from the open documents each time the workbench is
re-activated.
"""
import FreeCAD as App

from . import objects


# Propagation is globally suppressed while this depth is > 0. Connect Points uses
# it (via suppress()) so snapping a new part onto an assembly moves only that
# part - it must not cascade back through an existing joint and shove the
# assembly the user is snapping onto.
_suppress_depth = 0


class _Suppress:
    def __enter__(self):
        global _suppress_depth
        _suppress_depth += 1
        return self

    def __exit__(self, *exc):
        global _suppress_depth
        _suppress_depth -= 1
        return False


def suppress():
    """Context manager: temporarily stop joint propagation from reacting to
    Placement changes (baselines are still kept up to date)."""
    return _Suppress()


def _movable_owner(point):
    """The rigid object that owns a connection point and can be moved as a
    whole: its parent App::Part for an ordinary port, or the Hose itself if
    `point` is one of that Hose's own StartAnchor/EndAnchor - but only if that
    Hose is free-floating (no StartPoint), since an anchored hose's position
    is entirely derived from its StartPoint, not independently movable.
    """
    parent = objects.get_parent_part(point)
    if parent is not None:
        return parent
    doc = point.Document
    for obj in doc.Objects:
        if isinstance(getattr(obj, "Proxy", None), objects.Hose) and not obj.StartPoint:
            if obj.StartAnchor is point or obj.EndAnchor is point:
                return obj
    return None


def _same_placement(a, b):
    return a.Base == b.Base and a.Rotation.Q == b.Rotation.Q


def _classify(obj):
    """What a Placement change on `obj` means for propagation:

    - ("part", obj): obj itself is the rigid thing that moved - an App::Part
      component, or a free-floating Hose (no StartPoint). Its own Placement IS
      the thing to diff and propagate.
    - ("shape", owner): obj is a plain shape object (e.g. the Part::Feature/
      Part::Box a STEP import produces) sitting inside some App::Part `owner`
      alongside sibling ConnectionPoints. Its own Placement is relative to
      `owner`, not the world - so *editing this object's Placement directly*
      (easy to do by mistake: clicking a visible solid in the 3D view selects
      this object, not the App::Part wrapping it) moves the visible geometry
      but does NOT, by itself, move the sibling connection points, since their
      own Placement was calibrated once (at creation) against `owner`, with no
      dependency on this shape object going forward. Detected here so that
      drift can be compensated (see slotChangedObject) instead of silently
      leaving connection points behind.
    - None: not something propagation cares about (a ConnectionPoint or Joint
      itself, or an object with no App::Part parent at all).
    """
    if obj.TypeId == "App::Part":
        return "part", obj
    if isinstance(getattr(obj, "Proxy", None), objects.Hose) and not obj.StartPoint:
        return "part", obj
    if isinstance(getattr(obj, "Proxy", None), (objects.ConnectionPoint, objects.Joint)):
        return None
    parent = objects.get_parent_part(obj)
    if parent is not None:
        return "shape", parent
    return None


class JointPropagationObserver:
    def __init__(self):
        self._last_placement = {}
        self._active = False
        self._recomputing = False

    def slotDeletedObject(self, obj):
        self._last_placement.pop(obj.Name, None)

    def resync(self):
        """Re-seed placement baselines from every open document. Called when the
        Pipe Harness workbench is (re)activated: while it was inactive this
        observer wasn't registered, so any Placement changes made in the
        meantime went untracked. Re-seeding to current positions means the next
        move computes a correct delta instead of one measured against a stale
        baseline.
        """
        self._last_placement.clear()
        self._recomputing = False
        self._active = False
        for doc in App.listDocuments().values():
            for obj in doc.Objects:
                classification = _classify(obj)
                if classification is not None and hasattr(obj, "Placement"):
                    self._last_placement[obj.Name] = App.Placement(obj.Placement.Base, obj.Placement.Rotation)

    def slotBeforeRecomputeDocument(self, doc):
        # Placement writes made *during* a recompute - notably Hose.execute()
        # re-snapping an attached fitting via _update_anchor/snapping.connect -
        # fire slotChangedObject too, but the _active guard doesn't catch them
        # (the recompute, not this observer, initiated them). Reacting to them
        # would call doc.recompute() re-entrantly ("Recursive calling of
        # recompute"), which corrupts positions. This flag makes
        # slotChangedObject skip propagation for the whole recompute pass and
        # merely refresh its baseline cache, so the next *genuine* user move
        # still computes a correct delta.
        self._recomputing = True

    def slotRecomputedDocument(self, doc):
        """Seed a Placement baseline for every not-yet-seen object relevant to
        propagation, right after a recompute - by which point Proxy classes
        and Group membership are guaranteed fully set up (unlike at object
        creation: FreeCAD's "Created" signal fires *before* the caller's
        follow-up `SomeProxyClass(obj)` / `part.addObject(obj)` calls run, so
        trying to identify a Hose/ConnectionPoint/its parent Part from
        slotCreatedObject alone is unreliable - confirmed empirically, Proxy
        is still None there). Since nearly every command in this workbench
        ends with doc.recompute(), this reliably establishes a baseline
        before the user's next manual Placement edit, so that edit is
        compensated/propagated instead of silently only setting a baseline.
        """
        for obj in doc.Objects:
            if obj.Name not in self._last_placement:
                classification = _classify(obj)
                if classification is not None and hasattr(obj, "Placement"):
                    self._last_placement[obj.Name] = App.Placement(obj.Placement.Base, obj.Placement.Rotation)
        self._recomputing = False

    def slotChangedObject(self, obj, prop):
        if prop != "Placement":
            return
        classification = _classify(obj)
        if classification is None:
            return
        kind, owner = classification

        # Tracked/diffed against obj's OWN Placement in both cases - for
        # "part" that's the same object as owner; for "shape" it's the inner
        # object whose Placement actually changed (owner's own Placement
        # didn't). Normally already seeded by slotRecomputedDocument; if not
        # (e.g. this is the very first recompute since the document opened),
        # this change just establishes the baseline and is otherwise skipped.
        new_placement = App.Placement(obj.Placement.Base, obj.Placement.Rotation)
        old_placement = self._last_placement.get(obj.Name)
        self._last_placement[obj.Name] = new_placement
        if old_placement is None or _same_placement(old_placement, new_placement):
            return

        if self._active or self._recomputing or _suppress_depth:
            # Skip propagation when: our own propagation is mid-flight (_active);
            # the change happened during a recompute (_recomputing) - e.g.
            # Hose.execute()'s own re-snap of an attached fitting; or propagation
            # is explicitly suppressed (_suppress_depth), as Connect Points does
            # so a snap doesn't shove the assembly being snapped onto. The cache
            # is still updated above so the *next* genuine user move computes a
            # correct delta.
            return

        delta = new_placement * old_placement.inverse()
        self._active = True
        try:
            if kind == "shape":
                App.Console.PrintMessage(
                    "Pipe Harness: '%s' (a shape inside component '%s') moved "
                    "directly - shifting its connection points to compensate "
                    "and propagating to any jointed neighbors\n"
                    % (obj.Name, owner.Name)
                )
                for sibling in owner.Group:
                    if sibling.Name != obj.Name and isinstance(
                        getattr(sibling, "Proxy", None), objects.ConnectionPoint
                    ):
                        sibling.Placement = delta * sibling.Placement
                        sibling.purgeTouched()
            moved_names = {owner.Name}
            self._propagate(owner, delta, moved_names)
            self._touch_anchored_hoses(obj.Document, moved_names)
            obj.Document.recompute()
        except Exception as exc:
            App.Console.PrintError(
                "Pipe Harness: joint propagation failed (%s)\n" % exc
            )
        finally:
            self._active = False

    def _propagate(self, moved_obj, delta, moved_names):
        doc = moved_obj.Document
        for jt in doc.Objects:
            if not isinstance(getattr(jt, "Proxy", None), objects.Joint):
                continue
            if not jt.PointA or not jt.PointB:
                continue
            a_owner = _movable_owner(jt.PointA)
            b_owner = _movable_owner(jt.PointB)

            neighbor = None
            if a_owner is moved_obj and b_owner is not None and b_owner.Name not in moved_names:
                neighbor = b_owner
            elif b_owner is moved_obj and a_owner is not None and a_owner.Name not in moved_names:
                neighbor = a_owner
            if neighbor is None:
                continue
            if objects.is_grounded(neighbor):
                # A grounded neighbour is a fixed reference: mark it visited so we
                # don't keep re-examining it, but never move it or recurse through
                # it. This is what lets a new part be jointed to an existing/native
                # assembly without that assembly getting dragged around.
                moved_names.add(neighbor.Name)
                continue

            moved_names.add(neighbor.Name)
            neighbor.Placement = delta * neighbor.Placement
            self._last_placement[neighbor.Name] = App.Placement(neighbor.Placement.Base, neighbor.Placement.Rotation)
            self._propagate(neighbor, delta, moved_names)

    def _touch_anchored_hoses(self, doc, moved_names):
        """A Hose whose StartPoint lives inside one of the objects that just
        moved needs to recompute too, since its geometry is derived from that
        point's (now different) world position - but FreeCAD's dependency
        graph doesn't know that on its own (the link is to the ConnectionPoint
        object, not to its container), so it has to be forced explicitly.
        """
        for obj in doc.Objects:
            if isinstance(getattr(obj, "Proxy", None), objects.Hose) and obj.StartPoint:
                owner = objects.get_parent_part(obj.StartPoint)
                if owner is not None and owner.Name in moved_names:
                    obj.touch()
