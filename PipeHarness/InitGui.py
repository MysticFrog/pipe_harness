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

    def Initialize(self):
        # Runs once, the first time this workbench is activated. The drag-translate
        # handler and its document observer are created here (once) rather than in
        # Activated() (which runs every time the workbench is switched to) - the
        # observer re-attaches the handler to whichever view becomes active, so
        # switching/creating documents while the workbench stays active still works
        # (Activated() alone would only attach to the view current at that instant).
        from pipeharness import commands  # noqa: F401 - registers Gui.addCommand calls
        from pipeharness.drag_translate import DragTranslateHandler, _ViewActivationObserver
        from pipeharness.joint_propagation import JointPropagationObserver
        from pipeharness.library_panel import get_or_create_panel
        self.drag_handler = DragTranslateHandler()
        App.addDocumentObserver(_ViewActivationObserver(self.drag_handler))
        # Joint propagation is data consistency, not a 3D-view convenience like
        # drag-translate/Escape, so it's registered unconditionally here rather
        # than gated by Activated()/Deactivated() - a jointed assembly should stay
        # consistent even if the user switches away from this workbench.
        App.addDocumentObserver(JointPropagationObserver())
        self.appendToolbar("Pipe Harness", self.command_list)
        self.appendMenu("Pipe Harness", self.command_list)
        get_or_create_panel()

    def Activated(self):
        if self.drag_handler is not None:
            self.drag_handler.enable()

    def Deactivated(self):
        if self.drag_handler is not None:
            self.drag_handler.disable()

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
