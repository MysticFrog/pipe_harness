import FreeCAD as App
import FreeCADGui as Gui


class PipeHarnessWorkbench(Gui.Workbench):
    MenuText = "Pipe Harness"
    ToolTip = "Build pipe/hose harness assemblies from imported STEP components"

    command_list = [
        "PipeHarness_ImportSTEP",
        "PipeHarness_AddConnectionPoint",
        "PipeHarness_ConnectPoints",
        "PipeHarness_BreakJoint",
        "PipeHarness_ToggleConnectionPoints",
        "PipeHarness_AddHose",
        "PipeHarness_AddStraightSegment",
        "PipeHarness_AddBendSegment",
        "PipeHarness_ToggleLibraryPanel",
    ]

    def __init__(self):
        # FreeCAD execs InitGui.py directly rather than importing it, so a plain
        # module-level variable here is not visible from inside this class body/methods
        # (only names FreeCAD itself pre-seeds, like `os`, resolve that way). A local
        # import inside a function is always a normal local binding, so it works here.
        import os
        import pipeharness
        wb_dir = os.path.dirname(os.path.dirname(pipeharness.__file__))
        self.Icon = os.path.join(wb_dir, "Resources", "icons", "PipeHarness.svg")
        self.drag_handler = None
        self._view_observer = None
        self._joint_observer = None

    def Initialize(self):
        # Runs once, the first time this workbench is activated: register the
        # commands and build the toolbar/menu/library panel. The document
        # observers and 3D-view handlers are deliberately NOT registered here -
        # they are added in Activated() and removed in Deactivated(), so this
        # addon does nothing to other documents/workbenches while it isn't the
        # active one (no global, always-on side effects).
        from pipeharness import commands  # noqa: F401 - registers Gui.addCommand calls
        from pipeharness.library_panel import get_or_create_panel
        self.appendToolbar("Pipe Harness", self.command_list)
        self.appendMenu("Pipe Harness", self.command_list)
        get_or_create_panel()

    def _ensure_handlers(self):
        if self.drag_handler is None:
            from pipeharness.drag_translate import DragTranslateHandler, _ViewActivationObserver
            from pipeharness.joint_propagation import JointPropagationObserver
            self.drag_handler = DragTranslateHandler()
            self._view_observer = _ViewActivationObserver(self.drag_handler)
            self._joint_observer = JointPropagationObserver()

    def Activated(self):
        # Register the observers/handlers only while this workbench is active.
        self._ensure_handlers()
        App.addDocumentObserver(self._view_observer)
        App.addDocumentObserver(self._joint_observer)
        # We didn't track Placement changes while inactive, so re-seed the
        # propagation baselines from the current documents before enabling it.
        self._joint_observer.resync()
        self.drag_handler.enable()

    def Deactivated(self):
        if self.drag_handler is not None:
            self.drag_handler.disable()
        if self._view_observer is not None:
            App.removeDocumentObserver(self._view_observer)
        if self._joint_observer is not None:
            App.removeDocumentObserver(self._joint_observer)

    def ContextMenu(self, recipient):
        # Lets "Export to Parts Library" / "Toggle Grounded" show up on
        # right-click in the Model tree/3D view regardless of what's selected;
        # each command's own IsActive()/Activated() validate the selection.
        self.appendContextMenu(
            "Pipe Harness",
            ["PipeHarness_ExportToLibrary", "PipeHarness_ToggleGrounded"],
        )

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(PipeHarnessWorkbench())
