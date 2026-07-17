# Pipe Harness Assembly — Phase 1 (3D Assembly + Snap + Hose/Pipe Routing)

A FreeCAD workbench for building pipe/hose harness assemblies — hydraulic or
otherwise: import STEP components, mark connection points on them, snap
components together by matching up ports, and route a hose/pipe from a port
(or from the world origin) as a chain of straight and bend segments, each its
own object in the tree, with a connection point at *both* ends ready for
another part to attach to - and if a fitting is already attached to a hose's
end, it follows along automatically as the hose grows. Nothing is "grounded":
moving any jointed component (by editing its `Placement`, or with the
Shift+middle-click grab-move-drop mover) drags every component and free-floating
hose that's directly or transitively jointed to it along by the same rigid
motion, and their connection points travel with them. Save/reuse components via a local
parts library. A full pipe/fitting size library and a 2D CAD-style layout
view are planned for later phases.

## Layout

- `PipeHarness/` — the workbench source (this is what gets deployed into
  FreeCAD's `Mod/` folder).
  - `InitGui.py` — registers the workbench, toolbar, and menu; creates the
    drag-translate handler + its document observer, and the parts library
    panel, once; also wires up the right-click "Export to Parts Library"
    context menu entry.
  - `pipeharness/` — the Python package:
    - `objects.py` — `ConnectionPoint`, `Joint`, `Hose`, `PipeStraight`,
      `PipeBend`, and the routing/fillet math.
    - `snapping.py` — the mate/snap placement math.
    - `commands.py` — the toolbar commands.
    - `dialogs.py` — the "Add Straight/Bend Segment" entry dialogs (with live
      preview - see below).
    - `qtcompat.py` — PySide2/PySide6 (`QtGui`+`QtCore`) import shim shared by
      commands.py, dialogs.py, and library_panel.py.
    - `drag_translate.py` — the Coin3D event handler for grab-move-drop
      component moving (Shift+middle-click to grab, move the mouse, click to
      drop; Esc cancels) and Escape-to-deselect (same "extra 3D view
      interactions" handler). Uses free mouse-move events, since FreeCAD's
      navigation swallows motion while a button is held.
    - `joint_propagation.py` — the document observer that, whenever a
      component or free-floating hose's `Placement` changes, walks every
      `Joint` reachable from it and applies the same rigid delta to the other
      side - so a whole jointed assembly moves together instead of only the
      one piece you directly moved. Registered unconditionally (not gated by
      workbench activation) since it's data consistency, not a UI convenience.
    - `fitting_library.py` — loads the data-driven fitting/dash-size library.
    - `library.py` — export/insert/list/move/delete functions for the local
      parts library (all guarded to stay inside the library root).
    - `library_panel.py` — the dockable "Parts Library" tree panel, its
      right-click context menu (Insert / Move to Folder / Delete for parts,
      Add Subfolder / Remove Folder for folders), and the folder-selecting
      Export dialog.
  - `data/fitting_standards.json` — the JIC/BSP/ORFS fitting standards and
    sizes. Add new standards/sizes here, no code changes needed.
  - `data/dash_sizes.json` — approximate hydraulic hose OD by SAE dash size
    (illustrative, not a manufacturing spec - edit freely).
  - `Resources/icons/` — toolbar and object icons.
- `tools/sync_to_freecad.ps1` — copies `PipeHarness/` into one or more FreeCAD
  `Mod/` folders. It defaults to FreeCAD's per-user addon folder
  (`%APPDATA%\FreeCAD\<version>\Mod`, the same place the Addon Manager installs
  3rd-party workbenches); pass `-FreeCADModPaths` to deploy into a portable
  install's own `Mod/` or any other target. Re-run after every source change.
- `tests/test_snapping.py` — headless check of the core object model and
  snapping math, run via `FreeCADCmd.exe`.
- `tests/test_hose.py` — headless check of the Hose object: default and bent
  multi-segment routing built from separate PipeStraight/PipeBend children,
  `claimChildren()` tree-nesting, independent per-bend radii, segment length
  measured as the exact tangent run, the SweptAngle convention, starting with
  no connection point at all (world origin), the auto-managed `StartAnchor`/
  `EndAnchor` at both ends (including using one as the fixed side of a
  Connect Points mate), the HydraulicHose/DashSize-driven diameter, and - the
  key behavior - that a fitting connected to `EndAnchor` automatically follows
  when the hose grows a new segment; also covers a free-floating hose's own
  `Placement` correctly carrying its `StartAnchor`/`EndAnchor` along with it,
  the anchors' outward-facing normals, and Flip Normal
  (`objects.flip_connection_point`) reversing a point's normal - instantly on
  an ordinary point, and persistently (via the `Reversed` flag) on an anchor
  across later recomputes.
- `tests/test_joint_propagation.py` — headless check of
  `joint_propagation.py`: moving one component in a jointed chain (A↔B↔C)
  drags every transitively-jointed component by the same rigid delta, their
  connection points travel with them, an unrelated un-jointed component is
  left alone, a free-floating hose jointed to a component via its
  `EndAnchor` gets dragged along too, the "moved the wrong object" case
  (moving a component's underlying shape object directly, instead of its
  wrapping `App::Part`) still correctly shifts its connection points and any
  jointed neighbor to compensate, and - with undo enabled (`UndoMode=1`, as
  the GUI always has) - a single undo of a jointed move reverts the whole
  propagation, not just the directly-moved part.
- `tests/test_library.py` — headless check of the parts-library backend
  (`library.py`): exporting a component into a chosen/new/nested folder,
  `list_folders`, moving a part between folders (plus the no-op and
  name-collision cases), deleting a part, and the guards that refuse to
  delete/move anything outside the library root or that isn't a `.FCStd`
  part. Runs against a scratch library root, so the real one is untouched.
- `tests/test_drag_translate.py` — headless check of the grab-move-drop
  component mover's state machine (`drag_translate.py`), driven with synthetic
  Coin events and a fake view: a grab starts an undoable transaction, motion
  translates the component by the cursor delta, a click drops/commits (one undo
  reverts the whole move), and Esc aborts back to the start.
- `tests/test_grounding.py` — headless check of component grounding and native-
  body wrapping: `ensure_component()` wraps a plain root body in a component in
  place (grounded by default), `snapping.connect()` refuses to move a grounded
  component, joint propagation never drags a grounded neighbour (but a grounded
  part moved directly still drags its non-grounded neighbours), and
  `joint_propagation.suppress()` stops propagation for its scope.
- `tests/make_sample_steps.py` — generates two placeholder STEP files (a box
  and a cylinder standing in for real fittings) into `samples/`, for manually
  exercising the workbench in the FreeCAD GUI.

## Development loop

After changing anything under `PipeHarness/`:

```powershell
powershell -ExecutionPolicy Bypass -File tools\sync_to_freecad.ps1
```

Then re-run the headless checks with FreeCAD's console executable
(`FreeCADCmd.exe`, found in the `bin/` folder of your install — replace
`<FreeCAD>` below with the path to yours):

```
"<FreeCAD>\bin\FreeCADCmd.exe" tests\test_snapping.py
"<FreeCAD>\bin\FreeCADCmd.exe" tests\test_hose.py
"<FreeCAD>\bin\FreeCADCmd.exe" tests\test_joint_propagation.py
"<FreeCAD>\bin\FreeCADCmd.exe" tests\test_library.py
"<FreeCAD>\bin\FreeCADCmd.exe" tests\test_drag_translate.py
"<FreeCAD>\bin\FreeCADCmd.exe" tests\test_grounding.py
```

All six should print `ALL CHECKS PASSED` with no warnings above it. They have
been verified on FreeCAD 0.21.2 (PySide2/Qt5) and 1.1.1 (PySide6/Qt6). Both have also been verified (via `--log-file`) to load the
workbench itself cleanly at GUI startup — see "Cross-version notes" below.

**What headless testing can't cover**: only the literal OS mouse/keyboard
gesture. The event-handler *logic* behind the grab-move-drop mover is a plain
state machine and is tested headlessly (`tests/test_drag_translate.py`, driving
it with synthetic Coin events and a fake view), and it was also driven against
a real GUI viewer's `getPoint` (grab → motion moves the part → drop → undo
restores, no errors). The one thing no automated test can produce is the OS
delivering `SoLocation2` mouse-move events with no button held — but that's the
same event stream FreeCAD's own hover pre-selection relies on, so it's reliable.
The segment dialogs' live preview and the parts library panel's
buttons/double-click likewise have their underlying logic tested headlessly and
their wiring confirmed in a live GUI session; only the physical
click/drag/type needs a manual pass — see the walkthrough below.

**Component-move history** (why it's grab-move-drop, not press-hold-drag): a
literal Shift+middle-drag was tried across several rounds and kept failing — the
button-down and button-up fired but *no motion in between* ever reached the
callback. Root cause (confirmed from live logs): FreeCAD's navigation grabs the
mouse while a button is held and consumes the `SoLocation2` move events for its
own pan/rotate before the scene-graph callback sees them. `setHandled()` on the
button-down doesn't prevent it. So the interaction was switched to grab (one
Shift+middle click) → move with no button held (these move events *do* arrive) →
click to drop. Earlier fixes still stand: re-attaching via a persistent document
observer (so it survives document switches) and resolving a clicked solid up to
its containing `App::Part` via `get_parent_part()`.

## Manual GUI walkthrough

Do this by hand, launching `FreeCAD.exe` from your install (tested on FreeCAD
0.21.2 and 1.1.1):

1. Launch FreeCAD. **If it was already running from before you last synced,
   fully quit and relaunch it** — the workbench list is only (re)scanned at
   startup.
2. Create a new document (Ctrl+N).
3. Switch the workbench dropdown (top toolbar) to **Pipe Harness**. Its 9
   commands should appear as toolbar buttons: Import STEP as Component, Add
   Connection Point, Connect Points, Break Joint, Hide/Show Connection
   Points, Add Hose, Add Straight Segment, Add Bend Segment, Show/Hide Parts
   Library. A **Pipe Harness Parts Library** dock panel should also appear
   (probably docked on the right) with Add Folder / Remove Folder / Refresh
   buttons, an empty tree, and an Insert button.
4. Click **Import STEP as Component** and pick
   `samples\fitting_block.step`. You should get a new `Component` (an
   `App::Part`, labeled `fitting_block`) in the tree containing the box.
5. Repeat for `samples\fitting_cylinder.step` — a second `Component`
   (`fitting_cylinder`) appears.
6. In the 3D view, click a face on the box, then click **Add Connection
   Point**. A small cone/arrow marker should appear on that face, pointing
   along its normal, as a new `ConnectionPoint` object nested under the box's
   Component. For an exact bore/hole center instead of the face's own center,
   Ctrl+click a circular edge or a vertex on the face *before* clicking Add
   Connection Point. You can also add a connection point to a **native FreeCAD
   body** that was created directly (a Part/PartDesign box, a `Std_Part` you
   modelled yourself, etc.) and never imported through Pipe Harness — it gets
   wrapped in a new `Component` (App::Part) in place, **grounded** by default,
   so new parts snap onto it without shoving it around (see step 10). No need
   to import via STEP first.
7. Select that new `ConnectionPoint` and check its Data tab — `FittingStandard`,
   `Size`, `Gender`. Set them to confirm the data-driven library works. If the
   cone/arrow points the wrong way (into the body instead of out of the port),
   **right-click the point** (in the model tree or the 3D view) and choose
   **Flip Normal** — the marker reverses, and so does the direction another
   port will mate against. (This also works on a `Hose`'s `Hose_Start`/
   `Hose_End` anchors, where it sets a `Reversed` flag so the flip sticks even
   though those anchors are otherwise re-derived from the hose geometry every
   recompute.)
8. Do the same on a face of the cylinder to get a second `ConnectionPoint`.
9. Click **Hide/Show Connection Points** once — both markers disappear; click
   it again — both reappear.
10. Select the box's connection point first, then Ctrl-click the cylinder's
    connection point second, then click **Connect Points**. The cylinder
    should jump to mate with the box, and a `Joint` ball-and-link marker
    appears at the mated point. The Report View prints which point was treated
    as fixed/free and the moved component's Placement before/after.
    **Grounding**: a *grounded* component is a fixed reference — Connect Points
    snaps other parts onto it without moving it (even if you selected it
    second), and it isn't dragged along when a jointed neighbour moves. Bodies
    you add connection points to via step 6's native-body path are grounded
    automatically; toggle grounding on any component by right-clicking it and
    choosing **Toggle Grounded** (Pipe Harness section). This is what lets you
    build new pipes/parts onto a pre-existing (non-Pipe-Harness) assembly
    without the assembly shifting: the assembly stays put and the new parts
    conform to its connection points. Connect Points also suppresses
    joint-propagation for the duration of the snap, so snapping a second point
    between two already-jointed parts never yanks the assembly.
11. Click that marker (or select `Joint` in the tree) and click **Break
    Joint** — it disappears; the cylinder stays put.
12. Select the connection point on the box and click **Add Hose**. A short
    tube appears as a new `Hose` object with one `PipeStraight` child and two
    connection-point children, `StartAnchor` and `EndAnchor` (expand `Hose`
    in the tree to see all three). Try **Add Hose** again with nothing
    selected — it should start a second hose at the world origin instead of
    erroring.
13. Select the box's `Hose` and click **Add Bend Segment**. A dialog pops up
    with **Bend Radius**, **Swept Angle**, and **Yaw (bend axis)** fields
    (Pitch stays hidden, defaulting to 0 and still editable afterward on the
    property editor if you need a specific 3D bend plane). As soon as the
    dialog opens, a default bend should already be visible in the 3D view (a
    live preview, not waiting for OK) - and **the 3D view should still be
    fully interactive** (pan/zoom/rotate/select) while this dialog is open,
    since it's no longer modal. Drag the Swept Angle and Yaw spinners and the
    hose should visibly re-bend/re-orient in real time. Click Cancel once just
    to confirm the tentative bend disappears again; reopen and click OK to
    keep one. Then **Add Straight Segment** (Length only, same live-preview +
    non-modal behavior) to extend it further.
14. Expand the `Hose` in the tree: `PipeStraight`/`PipeBend` children, each
    with only its own relevant properties, plus `StartAnchor`/`EndAnchor` at
    the ends of the list. Select the `Hose` itself (not a child) to see
    `Diameter`, `HydraulicHose` (bool), and `DashSize` (enum, only editable
    while `HydraulicHose` is on).
    - `SweptAngle` (degrees, on a `PipeBend`): 0 = dead straight, 180 = a
      full U-turn - this is how far the bend actually turns.
    - Turn **HydraulicHose** on: `DashSize` becomes editable (no crimp collar
      geometry is added anymore - just the diameter sizing). Pick a different
      `DashSize` (e.g. `-16`) and `Diameter` should update automatically.
15. Select the box's `Hose`'s `EndAnchor` (the connection point at its open
    end) first, then Ctrl-click a connection point on some other, unconnected
    component second, then click **Connect Points** — that component should
    snap onto the hose's open end, exactly like connecting two ordinary
    component ports. Now click **Add Straight Segment** on the `Hose` again
    (extending it further) — the component you just attached should
    automatically slide along to stay connected at the new, farther-out open
    end, rather than being left behind at the old position.
16. Select an `App::Part` component and, in the tree, right-click it — an
    **Export to Parts Library** entry should appear in the context menu.
    Click it: a dialog asks for a **Part name** and a **Folder**. The folder
    dropdown lists `(library root)` plus every existing library folder, and is
    editable — pick one, or type a new (even nested, e.g. `Fittings/Metric`)
    folder path to create it on export. It **preselects whichever folder is
    currently highlighted in the Parts Library panel's tree**, so exporting
    defaults to where you're working rather than the root. Confirm the part is saved (a message
    prints to the Report View, and it appears in the Parts Library panel's
    tree — use Refresh if not). You can also pre-make folders with **Add
    Folder** in the panel (or right-click a folder → **Add Subfolder**).
17. In the Parts Library panel, double-click the part you just exported (or
    select it and click the **Insert Into Current File** button) — a copy of
    that component (with its connection points intact) should appear in the
    current document, positioned at the world origin. **Note**: the tree
    widget has drag enabled, but dragging it onto the 3D view was not able to
    be verified as an actual working drop target without live testing -
    double-click / Insert is the reliable way to bring a part in for now.
    **Right-click a part** in the panel for its context menu: **Insert Into
    Current File**, **Move to Folder…** (pick or type a destination folder -
    it's created if new; a same-named part already there is refused rather
    than overwritten), and **Delete Part** (with a confirmation; this removes
    the `.FCStd` file and can't be undone). Right-clicking a *folder* offers
    **Add Subfolder** and **Remove Folder** instead.
18. Open the Report View first (View > Panels > Report view). Hold **Shift**
    and **middle-click directly on the cylinder** to *grab* it — the grab
    ray-picks whatever component is under the cursor, so with several parts in
    the scene you move exactly the one you clicked on (it also becomes the sole
    selection). Now **move the mouse with no button held** — the cylinder
    follows the cursor (translating in the screen plane) — and **left-click to
    drop** it. (Press **Esc** to cancel and snap it back.) **Use a left-click,
    not a middle-click, to drop**: a plain middle-click is FreeCAD's own
    "centre view on cursor" navigation gesture, which the navigation processes
    before this workbench can, so it would recentre the view. The grab-move-drop
    model (rather than press-hold-drag) is deliberate — FreeCAD's navigation
    eats mouse-move events while a button is held, so a held-button drag never
    receives motion; moving with no button held does. The Report View shows
    `grabbed '<name>'`, a few `moved '<name>' by ...` lines, then
    `dropped '<name>' at ...`, plus a `picked '<x>' -> movable target '<y>'`
    line naming what the ray-pick resolved to. The same gesture moves a **pipe**
    (grab its tube) and a parts-library-inserted component. If a click doesn't
    grab (the log says it didn't resolve to anything movable), left-click the
    part once to select it, then Shift+middle-click to move the selection.
19. Move the cylinder's `Component` (grab-move-drop per step 18, or edit its
    Placement), *then* click a different face on it and **Add Connection
    Point** again — the marker should appear at the face's *current*
    location, not the pre-move one.
20. Select any component or object in the 3D view (or the tree) so it's
    highlighted, then press **Escape** — the selection should clear
    immediately, with no dialog or tool needing to be active first.
21. With the box, cylinder, and box's `Hose` all still connected from earlier
    steps (box↔cylinder via step 10's Joint, and the hose's `EndAnchor`↔some
    other component via step 15), select just the **box's** `Component` and
    edit its `Placement.Position` directly in the property editor (or
    grab-move-drop it per step 18). Every component and hose transitively jointed to the box —
    the cylinder, the hose, and whatever's attached to the hose's far end —
    should all translate together by the same amount, and their connection
    point markers should move with them. An unrelated, un-jointed component
    elsewhere in the document should **not** move. This confirms nothing is
    "grounded": moving any one jointed part drags the whole connected
    assembly, not just that one piece.
22. Immediately press **Ctrl+Z** (Undo). The whole assembly — the part you
    moved *and* every jointed part/connection point that followed it — should
    snap back to where it was in one step. (Same for undoing a grab-move-drop:
    the entire move is one undo step.)
23. Look at the two anchor markers on a `Hose` (`Hose_Start` and `Hose_End`):
    the little cone/arrow on each should point *away* from the hose body —
    `Hose_End` out the open end, `Hose_Start` out the near end (opposite the
    hose's direction of travel). That outward direction is what another port
    mates against. Change a `PipeStraight` segment's `Length` and confirm the
    `Hose_End` marker (and anything snapped to it) slides to the new open end,
    while `Hose_Start` (and anything snapped to it) stays put.

If any step errors, the message appears in FreeCAD's Report View
(View > Panels > Report view).

## Cross-version notes (0.21.2 vs 1.1.1)

- **PySide2/Qt5 vs PySide6/Qt6**: `QFileDialog`/`QDialog`/`QDockWidget`/etc.
  live in `QtWidgets`, not `QtGui`, under Qt6. `pipeharness/qtcompat.py`
  exposes both `QtGui` (aliased appropriately) and `QtCore` from whichever
  binding is available; `commands.py`, `dialogs.py`, and `library_panel.py`
  all import from this shared shim.
- **`InitGui.py` execution model**: FreeCAD `exec`s `InitGui.py` directly
  rather than importing it, so `__file__` is never defined there, and a plain
  module-level variable in `InitGui.py` is *not visible* from inside the
  workbench class's body/methods. Compute anything like that inside a method
  using local imports instead. Also watch for accidental BOM characters if
  editing these files via PowerShell's `-replace`/`Set-Content -Encoding
  UTF8` (adds a BOM; FreeCAD's direct `exec` chokes on it, plain Python
  `import` doesn't) - use a proper no-BOM UTF-8 encoder.
- **Python proxy `__dict__` is serialized to JSON**: FreeCAD saves a Python
  FeaturePython/ViewProvider proxy by JSON-serializing its instance `__dict__`
  - and (at least in 0.21.2) does so *regardless* of `__getstate__` returning
  `None`. So a proxy must never keep a non-serializable object (a
  `DocumentObject`, a `ViewProviderDocumentObject`, a Qt widget, a Coin node)
  as `self.something`, or every save/copy/insert spams
  `PropertyPythonObject::toString(): failed ... not JSON serializable`. Our
  ViewProviders therefore store only names (`ViewProviderHose` keeps
  `object_name`/`document_name` strings and re-looks-up the object in
  `claimChildren`) and nothing at all where the reference wasn't needed. Keep
  proxy `__dict__` values limited to JSON-native types.
- **Coin3D/pivy mouse button numbering**: Open Inventor's classic convention
  is `BUTTON1`=left, `BUTTON2`=middle, `BUTTON3`=right, but which one actually
  fires for a real middle-click couldn't be confirmed without live mouse
  input, so `drag_translate.py` accepts *either* as "middle click" (gated on
  Shift, so it can't hijack anything even if the guess is wrong).
- No dedicated "export a subset of objects to a file" API exists in this
  FreeCAD version (`Document.exportObjects` doesn't exist here) - the parts
  library instead copies the selected `App::Part` (recursively, via
  `Document.copyObject(obj, True)`) into a throwaway document and saves *that*,
  and reverses the process to insert. This was verified directly to correctly
  round-trip a custom `ConnectionPoint` FeaturePython object (including its
  Proxy class) before relying on it.
- If your FreeCAD install lives on a cloud-synced drive (OneDrive, Google
  Drive, etc.), the very first launch or headless run after a sync can be
  noticeably slow (potentially minutes) while the sync client materializes
  files on first access. Subsequent runs are normal speed.

## A note on editing Placement/Axis directly

`Hose`'s own `Placement` property *is* live - if a hose has no `StartPoint`
(built at the world origin), moving or reorienting the `Hose` object's own
`Placement` correctly moves/reorients the whole thing, *including* its
`StartAnchor`/`EndAnchor` connection points (they're independent document
objects, not children whose display auto-composites with the Hose's own
Placement, so `Hose.execute()` explicitly folds `obj.Placement` into their
computed world position/direction on every recompute). `PipeStraight`/
`PipeBend` segment children don't have a `Placement` at all (they're plain
`App::FeaturePython`, not a geometric type) - only their own listed
properties show up, by design.

Editing any `App::Part` component's (or free-floating `Hose`'s) `Placement`
- by hand in the property editor, or via Shift+middle-mouse-drag - also drags
every other component/hose transitively jointed to it by the same rigid
delta, via the always-on `joint_propagation.py` document observer. Nothing is
treated as a fixed "ground" just because it happened to be the *first*-selected
(fixed) side of an earlier Connect Points mate - the propagation is symmetric
and follows the `Joint` graph outward from whichever object you actually
moved. All of this is fully **undoable** as a single step: the Shift+MMB drag
wraps the whole gesture in one transaction, and the observer's edits to the
jointed neighbours land inside whatever transaction the triggering edit opened
(the property editor opens one automatically), so a single Ctrl+Z reverts the
move *and* everything it dragged along.

An **anchor's `+Z` axis is its outward-facing direction** - the way another
port mates against it (Connect Points opposes the two `+Z` axes). A hose's
`EndAnchor` faces along the direction of travel (out the open end); its
`StartAnchor` faces the *opposite* way (out the near end, i.e. against travel),
so a fitting snapped onto the start points correctly into the hose. If any
point faces the wrong way, **right-click it → Flip Normal** reverses it (one
undoable step). On an ordinary point this just flips its `Placement`; on an
auto-managed hose anchor it toggles a `Reversed` flag that `_update_anchor`
re-applies each recompute, so the flip isn't lost when the anchor is
re-derived from the hose geometry. (Flipping a point that's already mated
doesn't re-drive the fitting on the other side of the joint - re-run Connect
Points if you want the existing mate to follow the new facing; an anchor,
though, does re-snap whatever's attached to it on its next recompute.)

**Moving the underlying shape instead of the component**: clicking a visible
solid in the 3D view (or selecting the imported body's own row in the tree,
distinct from the `Component`/`App::Part` row wrapping it) selects the shape
object itself - editing *its* `Placement` moves the geometry but, on its own,
would leave that component's connection points (calibrated against the
`App::Part`, not the shape) behind. `joint_propagation.py` detects this case
too (see `_classify()`'s `"shape"` case) and shifts the sibling connection
points - and anything jointed through them - to compensate by the same
delta. This relies on a baseline Placement having been recorded for that
shape object at least once already, which happens automatically right after
the *next* recompute following its creation (`slotRecomputedDocument`, since
by the time any of this workbench's own commands finish - Import STEP, Add
Connection Point - they've already called `doc.recompute()`) - so in normal
use this is transparent. The only gap is moving a shape's `Placement` before
any recompute has happened at all since the document was (re)opened; if a
connection point doesn't follow its shape, moving that shape again (which
will now have a baseline) - or moving the `Component`/`App::Part` itself,
which has no such caveat - confirms/fixes it.

If editing a `Placement` via its expanded **Angle/Axis/Position** sub-fields
and changing only **Axis** doesn't do anything: that's expected, not a bug -
a rotation is `Angle` degrees *around* `Axis`, so at `Angle=0` the axis is
mathematically irrelevant. Set a nonzero `Angle` too, or - for a hose - use
**Add Bend Segment**'s `Swept Angle` field instead.

## Known limitations (by design, for this phase)

- Connect/Break is point-and-click (select then click a button), not a live
  drag-with-snap-preview.
- No 2D CAD-style layout view yet.
- A port's rotation about its own axis isn't fixed by a snap (only position +
  facing direction).
- A Hose only routes *from* a start point via manually added segments - it
  does not automatically solve a path to reach a second, target connection
  point (a real routing/IK problem, out of scope for now). Its `StartAnchor`/
  `EndAnchor` can be used as the *fixed* side of a mate (something else can
  snap onto it, and will keep following if the hose later grows), but a hose
  can't itself be dragged/mated by one of its anchors the way a rigid
  component can.
- The "fitting follows when the hose grows" behavior (re-snapping via
  `_update_anchor`/`snapping.connect()` when the hose's own geometry changes)
  only propagates one level - whatever is directly mated to `StartAnchor`/
  `EndAnchor`. General movement of an already-placed component *does* now
  cascade through the whole jointed assembly (see `joint_propagation.py`
  above); it's specifically hose-growth-triggered re-snapping that stays
  one level deep, to avoid fighting with that propagation.
- Add Straight/Bend Segment always append to the *tail* (open/growing) end of
  the selected hose's segment chain - no way yet to insert mid-chain.
- The corner fillet used for hose bends is a manual tangent-arc construction,
  not FreeCAD's solid-fillet operation. If a bend's radius is too large for
  the segments on either side of it, the sweep can fail or self-intersect.
- The grab-move-drop mover (Shift+middle-click *on* a part/pipe to grab, move,
  **left-click** to drop) moves whole components (`App::Part`) **and pipes**
  (free-floating `Hose` objects move by their own placement; picking a pipe's
  tube, a bend/straight segment, or one of its end anchors resolves to the
  hose). It translates in the screen plane only (no rotation, no depth control)
  and doesn't snap mid-move. It's grab-move-drop rather than press-hold-drag
  because FreeCAD's navigation eats mouse-move events while a button is held
  (see the Component-move history above). Drop with a **left**-click: a plain
  middle-click is FreeCAD's built-in "centre view" gesture, handled by the
  navigation before this workbench can intercept it, so it would recentre the
  view instead of dropping cleanly. The grab ray-picks whatever is under the
  cursor and resolves it to its movable owner; if that pick misses, it falls
  back to the current selection — so if something won't grab under the cursor,
  left-click it once to select it, then Shift+middle-click to move it. Each grab
  logs `picked '<x>' -> movable target '<y>'` to the Report View to make it
  obvious what got grabbed.
- The parts library panel's drag-and-drop into the 3D view is unverified and
  may not actually do anything yet - double-click or the Insert button are
  the reliable way to bring a library part into the current document.
- The parts library supports export-into-a-folder, move-part-between-folders,
  and delete-a-part (right-click a part), plus add/remove folder - but there's
  still no in-place **rename** of a part or folder (re-export under a new name,
  or move then delete, for now), and delete/remove are immediate filesystem
  operations with no undo.
