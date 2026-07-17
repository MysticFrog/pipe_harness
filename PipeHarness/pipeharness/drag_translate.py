"""Extra 3D view interactions, active only while the Pipe Harness workbench is
the current one (see InitGui.py's Activated/Deactivated, which call
enable()/disable()): a "grab and move" translation of the selected App::Part
component, and Escape to clear the selection / cancel a move.

Why grab-move-drop instead of a literal press-hold-drag: FreeCAD's navigation
machinery *grabs the mouse while a button is held down*, and consumes the
mouse-move (SoLocation2) events for its own pan/rotate/zoom gestures before our
Coin event callback ever sees them - so a "hold the button and drag" gesture
gets the button-down and button-up but no motion in between, and the part never
moves (confirmed from live logs: DOWN and UP fire, zero motion callbacks land).
Free mouse-move events (no button held) *do* reach the scene-graph callbacks -
that's how hover pre-selection highlighting works - so this instead:

  1. Shift + middle mouse button  -> "grab" the selected component.
  2. move the mouse (no button held) -> the component follows the cursor,
     translating in the camera's focal plane.
  3. click any mouse button        -> "drop" it there.
  (Esc at any point cancels the move and restores the original position.)

This uses the same addEventCallbackPivy/removeEventCallbackSWIG mechanism
FreeCAD's own tools use for custom mouse interaction (see
Mod/Draft/draftguitools/gui_edit.py, which likewise moves points on free
mouse-move rather than during a button-held drag). The whole move is wrapped in
a single document transaction so one Ctrl+Z undoes it (and, via the always-on
joint-propagation observer, everything jointed to the moved part follows and
is undone with it).

A single instance is created once by InitGui.py and re-attached to whatever view
is current via a persistent App.DocumentObserver - this handles switching between
documents/opening new ones while the workbench stays active, rather than only
attaching once at the moment the workbench was switched to (which would silently
do nothing if no document was open yet at that exact moment).
"""
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from . import objects

# Coin3D/Open Inventor's classic convention is BUTTON1=left, BUTTON2=middle,
# BUTTON3=right, but this has been observed to vary by platform/Qt binding on some
# builds, so both BUTTON2 and BUTTON3 are accepted here as "middle click". This is
# checked only together with Shift, so even on a build where BUTTON3 actually means
# right-click, this can't hijack anything - Shift+right-click isn't a FreeCAD default.
_GRAB_BUTTON_CANDIDATES = (coin.SoMouseButtonEvent.BUTTON2, coin.SoMouseButtonEvent.BUTTON3)

# Buttons that "drop" the held component. Left/middle/right only, so a scroll
# wheel (which arrives as BUTTON4/BUTTON5) can still zoom while positioning
# rather than accidentally dropping.
_DROP_BUTTONS = (
    coin.SoMouseButtonEvent.BUTTON1,
    coin.SoMouseButtonEvent.BUTTON2,
    coin.SoMouseButtonEvent.BUTTON3,
)

_BUTTON_NAMES = {
    coin.SoMouseButtonEvent.BUTTON1: "BUTTON1",
    coin.SoMouseButtonEvent.BUTTON2: "BUTTON2",
    coin.SoMouseButtonEvent.BUTTON3: "BUTTON3",
    coin.SoMouseButtonEvent.BUTTON4: "BUTTON4",
    coin.SoMouseButtonEvent.BUTTON5: "BUTTON5",
}


class DragTranslateHandler:
    def __init__(self):
        self.enabled = False
        self._view = None
        self._button_cb = None
        self._motion_cb = None
        self._key_cb = None
        self._held_obj = None
        self._doc = None
        self._last_point = None
        self._motion_log_count = 0
        self._motion_seen = False
        # When we consume a mouse-button press (grab or drop), we must also
        # consume its matching release, or that release falls through to
        # FreeCAD and clears the current selection - which then makes the *next*
        # Shift+middle grab find nothing selected and silently do nothing (the
        # navigation centres the view instead). This tracks that pending release.
        self._swallow_next_up = False

    # --- lifecycle -----------------------------------------------------

    def enable(self):
        self.enabled = True
        self.attach_to_current_view()

    def disable(self):
        self.enabled = False
        self._detach_view()

    def attach_to_current_view(self):
        """(Re-)attach to whichever view is currently active, if enabled and it's
        not already the one we're attached to. Safe to call anytime (e.g. from a
        document-activated/created observer) - a no-op if nothing changed.
        """
        if not self.enabled:
            return
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None or view is self._view:
            return
        self._detach_view()
        try:
            self._view = view
            self._button_cb = view.addEventCallbackPivy(
                coin.SoMouseButtonEvent.getClassTypeId(), self._on_button
            )
            self._motion_cb = view.addEventCallbackPivy(
                coin.SoLocation2Event.getClassTypeId(), self._on_motion
            )
            self._key_cb = view.addEventCallbackPivy(
                coin.SoKeyboardEvent.getClassTypeId(), self._on_key
            )
        except Exception as exc:
            App.Console.PrintWarning(
                "Pipe Harness: could not attach 3D view interactions to this "
                "view (%s)\n" % exc
            )
            self._view = None

    def _detach_view(self):
        # If a move was mid-flight when the view goes away, don't leave a dangling
        # open transaction behind.
        if self._held_obj is not None:
            self._cancel(quiet=True)
        if self._view is not None:
            try:
                if self._button_cb is not None:
                    self._view.removeEventCallbackSWIG(
                        coin.SoMouseButtonEvent.getClassTypeId(), self._button_cb
                    )
                if self._motion_cb is not None:
                    self._view.removeEventCallbackSWIG(
                        coin.SoLocation2Event.getClassTypeId(), self._motion_cb
                    )
                if self._key_cb is not None:
                    self._view.removeEventCallbackSWIG(
                        coin.SoKeyboardEvent.getClassTypeId(), self._key_cb
                    )
            except Exception:
                pass
        self._view = None
        self._button_cb = None
        self._motion_cb = None
        self._key_cb = None
        self._held_obj = None
        self._doc = None
        self._last_point = None
        self._swallow_next_up = False

    # --- grab / drop / cancel --------------------------------------------

    def _pick_target(self, event):
        """The App::Part component directly under the cursor (ray-pick), or None.
        This is what makes "move only the part I clicked on" work when several
        components are in the scene - it doesn't rely on the current selection.
        """
        try:
            pos = event.getPosition().getValue()
            info = self._view.getObjectInfo((int(pos[0]), int(pos[1])))
        except Exception:
            return None
        if not info:
            App.Console.PrintMessage(
                "Pipe Harness move: nothing under the cursor to grab (getObjectInfo "
                "returned nothing)\n"
            )
            return None
        doc_name = info.get("Document")
        obj_name = info.get("Object")
        if not doc_name or not obj_name:
            return None
        try:
            picked = App.getDocument(doc_name).getObject(obj_name)
        except Exception:
            return None
        target = _resolve_movable(picked)
        App.Console.PrintMessage(
            "Pipe Harness move: picked '%s' (%s) -> movable target '%s'\n"
            % (obj_name, getattr(picked, "TypeId", "?"),
               target.Name if target is not None else "<none>")
        )
        return target

    def _start_grab(self, target, event):
        # Make the grabbed component the sole selection, so it's visually clear
        # which part is being moved and a later selection-based action targets it.
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(target)
        except Exception:
            pass
        self._held_obj = target
        self._motion_log_count = 0
        pos = event.getPosition().getValue()
        self._last_point = self._view.getPoint(pos[0], pos[1])
        # One transaction for the whole move, so a single Ctrl+Z afterwards undoes
        # it (and everything the joint-propagation observer dragged along with it).
        self._doc = target.Document
        if self._doc is not None:
            self._doc.openTransaction("Move component")
        App.Console.PrintMessage(
            "Pipe Harness move: grabbed '%s' - move the mouse to reposition it, then "
            "*left-click* to drop it (or press Esc to cancel). Avoid a plain "
            "middle-click to drop - that's FreeCAD's own 'centre view' gesture.\n"
            % target.Name
        )

    def _drop(self):
        obj, doc = self._held_obj, self._doc
        self._held_obj = None
        self._last_point = None
        self._doc = None
        if obj is not None:
            App.Console.PrintMessage(
                "Pipe Harness move: dropped '%s' at %s\n" % (obj.Name, obj.Placement.Base)
            )
        if doc is not None:
            doc.commitTransaction()
            doc.recompute()

    def _cancel(self, quiet=False):
        obj, doc = self._held_obj, self._doc
        self._held_obj = None
        self._last_point = None
        self._doc = None
        # abortTransaction rolls the Placement (and any propagated neighbours)
        # back to exactly where they were when the grab started.
        if doc is not None:
            doc.abortTransaction()
            doc.recompute()
        if obj is not None and not quiet:
            App.Console.PrintMessage(
                "Pipe Harness move: cancelled moving '%s' (restored)\n" % obj.Name
            )

    # --- event handlers --------------------------------------------------

    def _on_button(self, event_callback):
        try:
            self._handle_button(event_callback)
        except Exception:
            # A Python exception raised from a callback invoked by Coin3D's C++
            # event dispatch can otherwise vanish silently (no traceback visible
            # anywhere) - print it explicitly so a real bug here isn't mistaken
            # for "the handler never fired at all".
            App.Console.PrintError(
                "Pipe Harness move: exception in button handler:\n"
                + traceback.format_exc()
            )

    def _handle_button(self, event_callback):
        event = event_callback.getEvent()
        state = event.getState()

        if state == coin.SoMouseButtonEvent.UP:
            # Swallow the release that pairs with a press we consumed, so it
            # can't reach FreeCAD's selection/navigation (which would otherwise
            # clear the selection our next grab depends on).
            if self._swallow_next_up:
                self._swallow_next_up = False
                event_callback.setHandled()
            return
        if state != coin.SoMouseButtonEvent.DOWN:
            return

        # A button press.
        if self._held_obj is not None:
            # Already holding a component - any left/middle/right click drops it.
            if event.getButton() in _DROP_BUTTONS:
                self._drop()
                self._swallow_next_up = True
                event_callback.setHandled()
            return

        # Not holding: Shift + middle mouse grabs the selected component.
        if event.getButton() in _GRAB_BUTTON_CANDIDATES and event.wasShiftDown():
            App.Console.PrintMessage(
                "Pipe Harness move: Shift+%s pressed\n"
                % _BUTTON_NAMES.get(event.getButton(), event.getButton())
            )
            # Consume this press (and its release) no matter what, so a
            # Shift+middle-click never falls through to the navigation style's
            # "centre the view on cursor" gesture while this workbench is active.
            self._swallow_next_up = True
            event_callback.setHandled()
            # Grab the component *under the cursor* first (so with several parts
            # you move exactly the one you clicked on); only if the click missed
            # every component fall back to the current selection.
            target = self._pick_target(event) or _resolve_drag_target(Gui.Selection.getSelection())
            if target is None:
                App.Console.PrintMessage(
                    "Pipe Harness move: that Shift+middle-click didn't resolve to anything "
                    "movable. Aim directly at the part/pipe, or left-click it once to "
                    "select it first and then Shift+middle-click to move the selection.\n"
                )
                return
            self._start_grab(target, event)

    def _on_motion(self, event_callback):
        if not self._motion_seen:
            self._motion_seen = True
            App.Console.PrintMessage(
                "Pipe Harness move: motion callback is receiving events (this prints "
                "once, the first time the mouse moves over the 3D view after load)\n"
            )
        if self._held_obj is None:
            return
        try:
            self._handle_motion(event_callback)
        except Exception:
            App.Console.PrintError(
                "Pipe Harness move: exception in motion handler:\n"
                + traceback.format_exc()
            )

    def _handle_motion(self, event_callback):
        event = event_callback.getEvent()
        pos = event.getPosition().getValue()
        new_point = self._view.getPoint(pos[0], pos[1])
        delta = new_point - self._last_point
        self._last_point = new_point

        placement = self._held_obj.Placement
        self._held_obj.Placement = App.Placement(placement.Base + delta, placement.Rotation)

        if self._motion_log_count < 3:
            self._motion_log_count += 1
            App.Console.PrintMessage(
                "Pipe Harness move: moved '%s' by %s to %s\n"
                % (self._held_obj.Name, delta, self._held_obj.Placement.Base)
            )
        # Swallow the motion while holding so pre-selection highlighting doesn't
        # flicker over the part as it slides.
        event_callback.setHandled()

    def _on_key(self, event_callback):
        try:
            event = event_callback.getEvent()
            if (event.getState() == coin.SoKeyboardEvent.DOWN
                    and event.getKey() == coin.SoKeyboardEvent.ESCAPE):
                if self._held_obj is not None:
                    self._cancel()
                else:
                    Gui.Selection.clearSelection()
                event_callback.setHandled()
        except Exception:
            App.Console.PrintError(
                "Pipe Harness: exception in Escape handler:\n"
                + traceback.format_exc()
            )


def _resolve_movable(obj):
    """The object the mover should actually translate, given whatever was picked
    or selected. Handles all the movable things in a harness, not just imported
    components:

    - an App::Part component -> itself;
    - a face/solid/connection-point inside a component -> that component
      (App::Part), which is what STEP imports *and* parts-library inserts are;
    - a Hose (pipe) itself -> the Hose (its own Placement is live); a hose is a
      Part::FeaturePython that lives at the document root, not inside an
      App::Part, which is exactly why the old App::Part-only resolver could
      never move a pipe;
    - a picked hose *shape* segment or one of a hose's StartAnchor/EndAnchor
      markers -> the owning Hose.

    Returns None if nothing movable applies.
    """
    if obj is None:
        return None
    if obj.TypeId == "App::Part":
        return obj
    parent = objects.get_parent_part(obj)
    if parent is not None:
        return parent
    proxy = getattr(obj, "Proxy", None)
    if isinstance(proxy, objects.Hose):
        return obj
    if isinstance(proxy, objects.ConnectionPoint):
        hose = _hose_owning(obj, "anchor")
        if hose is not None:
            return hose
    if isinstance(proxy, (objects.PipeStraight, objects.PipeBend)):
        hose = _hose_owning(obj, "segment")
        if hose is not None:
            return hose
    return None


def _hose_owning(obj, kind):
    """The Hose that owns `obj` as a StartAnchor/EndAnchor (kind="anchor") or as
    one of its Segments (kind="segment"), or None.
    """
    for other in obj.Document.Objects:
        if not isinstance(getattr(other, "Proxy", None), objects.Hose):
            continue
        if kind == "anchor" and (other.StartAnchor is obj or other.EndAnchor is obj):
            return other
        if kind == "segment" and obj in other.Segments:
            return other
    return None


def _resolve_drag_target(selection):
    """The movable object for the current selection (first one that resolves)."""
    for obj in selection:
        target = _resolve_movable(obj)
        if target is not None:
            return target
    return None


class _ViewActivationObserver:
    """Re-attaches the drag handler whenever the active document/view changes,
    so the feature keeps working across document switches/creation while the
    workbench stays active. Registered once via App.addDocumentObserver.
    """

    def __init__(self, handler):
        self.handler = handler

    def slotActivateDocument(self, doc):
        self.handler.attach_to_current_view()

    def slotCreatedDocument(self, doc):
        self.handler.attach_to_current_view()
