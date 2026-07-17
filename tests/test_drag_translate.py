"""Headless logic check of the grab-move-drop component mover, run via
FreeCADCmd.exe:

    FreeCADCmd.exe test_drag_translate.py

The literal mouse gesture can only be exercised in a live GUI, but the state
machine behind it (grab -> follow motion -> drop, wrapped in one undoable
transaction; and grab -> Esc cancels/restores) is plain Python and is driven
here with synthetic Coin events and a fake view, against a real document. This
guards the part everything else depends on: that a grab starts a transaction, a
motion translates the component by the cursor delta, a drop commits (undoable in
one step), and Esc aborts back to the start.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "PipeHarness"))

import FreeCAD as App
from pivy import coin

from pipeharness import drag_translate


class FakePos:
    def __init__(self, xy):
        self._xy = xy

    def getValue(self):
        return self._xy


class FakeButtonEvent:
    def __init__(self, state, button, shift, xy=(0, 0)):
        self._state, self._button, self._shift, self._pos = state, button, shift, FakePos(xy)

    def getState(self):
        return self._state

    def getButton(self):
        return self._button

    def wasShiftDown(self):
        return self._shift

    def getPosition(self):
        return self._pos


class FakeKeyEvent:
    def __init__(self, state, key):
        self._state, self._key = state, key

    def getState(self):
        return self._state

    def getKey(self):
        return self._key


class FakeMotionEvent:
    def __init__(self, xy):
        self._pos = FakePos(xy)

    def getPosition(self):
        return self._pos


class FakeCallback:
    """Stand-in for the SoEventCallback FreeCAD passes in; carries one event and
    records whether the handler consumed it.
    """
    def __init__(self, event):
        self._event = event
        self.handled = False

    def getEvent(self):
        return self._event

    def setHandled(self):
        self.handled = True


class FakeView:
    """getPoint just maps screen (x, y) straight to a world point, so a cursor
    delta becomes an equal translation delta - enough to exercise the math.
    getObjectInfo returns whatever `pick_result` is set to (None = the click
    landed on nothing, so the grab falls back to the selection).
    """
    def __init__(self):
        self.pick_result = None

    def getPoint(self, x, y):
        return App.Vector(x, y, 0)

    def getObjectInfo(self, xy):
        return self.pick_result


DOWN = coin.SoMouseButtonEvent.DOWN
UP = coin.SoMouseButtonEvent.UP
B3 = coin.SoMouseButtonEvent.BUTTON3
B1 = coin.SoMouseButtonEvent.BUTTON1
KDOWN = coin.SoKeyboardEvent.DOWN
ESC = coin.SoKeyboardEvent.ESCAPE


def make_component(doc, name, pos):
    b = doc.addObject("Part::Box", name + "Block")
    b.Length = b.Width = b.Height = 10
    p = doc.addObject("App::Part", name)
    p.addObject(b)
    p.Placement = App.Placement(App.Vector(*pos), App.Rotation())
    return p


def main():
    doc = App.newDocument("DragTest")
    doc.UndoMode = 1
    part = make_component(doc, "Comp", (0, 0, 0))
    doc.recompute()

    handler = drag_translate.DragTranslateHandler()
    handler.enabled = True
    handler._view = FakeView()

    # Headless FreeCADGui has no Selection; swap in a fake so a grab resolves to
    # `part` and Esc's clearSelection() is a harmless no-op.
    class _FakeSelection:
        @staticmethod
        def getSelection():
            return [part]

        @staticmethod
        def clearSelection():
            pass

        @staticmethod
        def addSelection(obj):
            pass

    class _FakeGui:
        Selection = _FakeSelection

    drag_translate.Gui = _FakeGui  # type: ignore

    # Ray-pick: grabbing targets the App::Part under the cursor. A pick that
    # lands on the component's inner solid resolves up to the component itself.
    handler._view.pick_result = {"Document": doc.Name, "Object": part.Group[0].Name}
    assert handler._pick_target(FakeCallback(FakeButtonEvent(DOWN, B3, True)).getEvent()) is part, (
        "a pick on a component's solid should resolve to the App::Part"
    )
    handler._view.pick_result = None  # back to "clicked nothing" -> selection fallback

    # --- grab -> move -> drop ------------------------------------------------
    grab = FakeCallback(FakeButtonEvent(DOWN, B3, True, xy=(0, 0)))
    handler._handle_button(grab)
    assert handler._held_obj is part, "Shift+middle press should grab the selected component"
    assert grab.handled, "grab press should be consumed"

    # The paired button release must NOT drop, and must be *swallowed* (handled)
    # so it can't reach FreeCAD's selection handling and clear the selection.
    rel = FakeCallback(FakeButtonEvent(UP, B3, True))
    handler._handle_button(rel)
    assert handler._held_obj is part, "the release right after grabbing must not drop"
    assert rel.handled, "the grab's release must be swallowed to protect the selection"

    # Move the cursor: the component follows by the same delta.
    handler._on_motion(FakeCallback(FakeMotionEvent((10, 0))))
    handler._on_motion(FakeCallback(FakeMotionEvent((10, 25))))
    assert (part.Placement.Base - App.Vector(10, 25, 0)).Length < 1e-6, (
        "component should follow the cursor while held: got %s" % part.Placement.Base
    )

    # Click to drop -> commits.
    drop = FakeCallback(FakeButtonEvent(DOWN, B1, False))
    handler._handle_button(drop)
    assert handler._held_obj is None, "a click should drop the held component"
    assert drop.handled
    assert (part.Placement.Base - App.Vector(10, 25, 0)).Length < 1e-6

    # The drop click's release must also be swallowed - otherwise it falls
    # through to FreeCAD and deselects the part, so the *next* grab finds
    # nothing selected and the middle-click just centres the view instead
    # (exactly the "worked once, now only centres the view" regression).
    drop_up = FakeCallback(FakeButtonEvent(UP, B1, False))
    handler._handle_button(drop_up)
    assert drop_up.handled, "the drop's release must be swallowed to protect the selection"

    # The whole move is one undo step.
    doc.undo()
    doc.recompute()
    assert (part.Placement.Base - App.Vector(0, 0, 0)).Length < 1e-6, (
        "one undo should revert the entire move: got %s" % part.Placement.Base
    )
    doc.redo()
    doc.recompute()
    assert (part.Placement.Base - App.Vector(10, 25, 0)).Length < 1e-6

    # --- grab -> Esc cancels/restores ---------------------------------------
    start = App.Vector(part.Placement.Base)
    handler._handle_button(FakeCallback(FakeButtonEvent(DOWN, B3, True, xy=(0, 0))))
    handler._handle_button(FakeCallback(FakeButtonEvent(UP, B3, True)))
    handler._on_motion(FakeCallback(FakeMotionEvent((100, 100))))
    assert (part.Placement.Base - (start + App.Vector(100, 100, 0))).Length < 1e-6

    esc = FakeCallback(FakeKeyEvent(KDOWN, ESC))
    handler._on_key(esc)
    doc.recompute()
    assert handler._held_obj is None, "Esc should end the move"
    assert esc.handled
    assert (part.Placement.Base - start).Length < 1e-6, (
        "Esc should abort the move and restore the original position: got %s"
        % part.Placement.Base
    )

    # Esc with nothing held should not error (clears selection instead).
    handler._on_key(FakeCallback(FakeKeyEvent(KDOWN, ESC)))

    # A Shift+middle press with *nothing* selected must still be consumed (so it
    # can't fall through to the navigation's centre-the-view gesture), and must
    # not grab anything.
    drag_translate.Gui.Selection.getSelection = staticmethod(lambda: [])  # type: ignore
    empty_grab = FakeCallback(FakeButtonEvent(DOWN, B3, True, xy=(0, 0)))
    handler._handle_button(empty_grab)
    assert handler._held_obj is None, "nothing selected -> nothing grabbed"
    assert empty_grab.handled, "Shift+middle must be consumed even when it grabs nothing"

    # _resolve_movable handles more than App::Parts: a pipe (Hose) and anything
    # picked that belongs to one must resolve to a movable object, or pipes can
    # never be grabbed (a Hose lives at the document root, not inside a Part).
    from pipeharness import objects as _objects
    hose = _objects.create_hose(doc, None, name="FreeHose")
    doc.recompute()
    assert drag_translate._resolve_movable(hose) is hose, "a free hose resolves to itself"
    assert drag_translate._resolve_movable(hose.Segments[0]) is hose, "a hose segment -> its hose"
    assert drag_translate._resolve_movable(hose.StartAnchor) is hose, "a StartAnchor -> its hose"
    assert drag_translate._resolve_movable(hose.EndAnchor) is hose, "an EndAnchor -> its hose"
    assert drag_translate._resolve_movable(part) is part, "an App::Part still resolves to itself"
    assert drag_translate._resolve_movable(part.Group[0]) is part, "a solid inside a Part -> the Part"

    # A hose is movable by setting its own Placement (what _handle_motion does).
    hose_before = App.Vector(hose.Placement.Base)
    hose.Placement = App.Placement(hose_before + App.Vector(5, 0, 0), hose.Placement.Rotation)
    doc.recompute()
    assert (App.Vector(hose.Placement.Base) - hose_before - App.Vector(5, 0, 0)).Length < 1e-6

    print("ALL CHECKS PASSED")


main()
