"""Dockable "Pipe Harness Parts Library" panel: a folder tree of saved
components (see library.py), with Add/Remove Folder buttons and an Insert
action to copy a library part into the currently active document.

The tree widget has Qt's drag-enabled flag turned on, but there is no reliable
way to have verified (without live GUI testing) that dropping onto the 3D view
actually inserts anything - the 3D view isn't a registered drop target for
this. Double-click, or the "Insert Into Current File" button, are the
guaranteed-to-work ways to bring a part in; treat drag-and-drop as a bonus
that may not do anything yet.
"""
import os

import FreeCAD as App
import FreeCADGui as Gui

from .qtcompat import QtGui, QtCore
from . import library

_PATH_ROLE = QtCore.Qt.UserRole
_IS_FOLDER_ROLE = QtCore.Qt.UserRole + 1

_ROOT_LABEL = "(library root)"


def _folder_choices():
    """[(display, relative_path)] for the library root plus every existing
    folder, for a "pick a folder" dropdown. The root is relative-path "".
    """
    choices = [(_ROOT_LABEL, "")]
    for rel in library.list_folders():
        choices.append((rel, rel))
    return choices


def _resolve_folder_choice(text, choices):
    """Map a combo/getItem selection back to a relative folder path: a known
    display maps to its stored path, the root label maps to "", and anything
    else is treated as a typed-in new relative folder path.
    """
    text = text.strip()
    for display, rel in choices:
        if display == text:
            return rel
    return "" if text == _ROOT_LABEL else text


class ExportTargetDialog(QtGui.QDialog):
    """Asks for the part name and destination folder when exporting to the
    library. The folder combo is editable, so an existing folder can be picked
    or a new relative folder path typed in (export_part creates it).
    """

    def __init__(self, default_name, default_folder="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export to Parts Library")
        self._choices = _folder_choices()

        self.name_edit = QtGui.QLineEdit(default_name)
        self.folder_combo = QtGui.QComboBox()
        self.folder_combo.setEditable(True)
        for display, _rel in self._choices:
            self.folder_combo.addItem(display)
        # Preselect the folder that's currently active in the library tree (the
        # root maps to index 0), so exporting defaults to "where I'm looking"
        # rather than always the root.
        for i, (_display, rel) in enumerate(self._choices):
            if rel == default_folder:
                self.folder_combo.setCurrentIndex(i)
                break

        form = QtGui.QFormLayout()
        form.addRow("Part name", self.name_edit)
        form.addRow("Folder", self.folder_combo)

        buttons = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtGui.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self):
        """(name, relative_folder) from the dialog fields."""
        return (
            self.name_edit.text().strip(),
            _resolve_folder_choice(self.folder_combo.currentText(), self._choices),
        )


class LibraryPanel(QtGui.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Pipe Harness Parts Library", parent)
        self.setObjectName("PipeHarnessLibraryPanel")

        container = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(container)

        button_row = QtGui.QHBoxLayout()
        add_folder_btn = QtGui.QPushButton("Add Folder")
        remove_folder_btn = QtGui.QPushButton("Remove Folder")
        refresh_btn = QtGui.QPushButton("Refresh")
        add_folder_btn.clicked.connect(self._add_folder)
        remove_folder_btn.clicked.connect(self._remove_folder)
        refresh_btn.clicked.connect(self.refresh)
        button_row.addWidget(add_folder_btn)
        button_row.addWidget(remove_folder_btn)
        button_row.addWidget(refresh_btn)
        layout.addLayout(button_row)

        self.tree = QtGui.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setDragEnabled(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree)

        insert_btn = QtGui.QPushButton("Insert Into Current File")
        insert_btn.clicked.connect(self._insert_selected)
        layout.addWidget(insert_btn)

        self.setWidget(container)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        library.ensure_library_root()
        self._populate(self.tree.invisibleRootItem(), library.LIBRARY_ROOT)
        self.tree.expandAll()

    def _populate(self, parent_item, dir_path):
        for entry in sorted(os.listdir(dir_path)):
            full = os.path.join(dir_path, entry)
            if os.path.isdir(full):
                item = QtGui.QTreeWidgetItem([entry])
                item.setData(0, _PATH_ROLE, full)
                item.setData(0, _IS_FOLDER_ROLE, True)
                parent_item.addChild(item)
                self._populate(item, full)
            elif entry.lower().endswith(".fcstd"):
                item = QtGui.QTreeWidgetItem([os.path.splitext(entry)[0]])
                item.setData(0, _PATH_ROLE, full)
                item.setData(0, _IS_FOLDER_ROLE, False)
                parent_item.addChild(item)

    def _selected_folder_path(self):
        """The folder a new subfolder/export should go under: the selected
        folder, the selected part's own containing folder, or the library
        root if nothing is selected.
        """
        item = self.tree.currentItem()
        if item is None:
            return library.LIBRARY_ROOT
        path = item.data(0, _PATH_ROLE)
        is_folder = item.data(0, _IS_FOLDER_ROLE)
        return path if is_folder else os.path.dirname(path)

    def current_relative_folder(self):
        """The active tree folder as a path relative to the library root ("" for
        the root) - used to preselect the Export dialog's folder.
        """
        abs_path = self._selected_folder_path()
        if os.path.normpath(abs_path) == os.path.normpath(library.LIBRARY_ROOT):
            return ""
        return os.path.relpath(abs_path, library.LIBRARY_ROOT)

    def _add_folder(self):
        name, ok = QtGui.QInputDialog.getText(self, "Add Folder", "Folder name:")
        if not ok or not name.strip():
            return
        target = os.path.join(self._selected_folder_path(), name.strip())
        try:
            os.makedirs(target, exist_ok=False)
        except FileExistsError:
            App.Console.PrintError("Pipe Harness Library: '%s' already exists.\n" % name.strip())
            return
        self.refresh()

    def _remove_folder(self):
        item = self.tree.currentItem()
        if item is None or not item.data(0, _IS_FOLDER_ROLE):
            App.Console.PrintError("Pipe Harness Library: select a folder to remove.\n")
            return
        path = item.data(0, _PATH_ROLE)
        confirm = QtGui.QMessageBox.question(
            self, "Remove Folder",
            "Remove '%s' and everything in it? This cannot be undone." % item.text(0),
        )
        if confirm != QtGui.QMessageBox.Yes:
            return
        import shutil
        shutil.rmtree(path)
        self.refresh()

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QtGui.QMenu(self.tree)
        if item.data(0, _IS_FOLDER_ROLE):
            menu.addAction("Add Subfolder", self._add_folder)
            menu.addAction("Remove Folder", self._remove_folder)
        else:
            menu.addAction("Insert Into Current File",
                           lambda: self._insert_path(item.data(0, _PATH_ROLE)))
            menu.addAction("Move to Folder…", lambda: self._move_part(item))
            menu.addAction("Delete Part", lambda: self._delete_part(item))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _delete_part(self, item):
        path = item.data(0, _PATH_ROLE)
        confirm = QtGui.QMessageBox.question(
            self, "Delete Part",
            "Delete '%s'? This cannot be undone." % item.text(0),
        )
        if confirm != QtGui.QMessageBox.Yes:
            return
        try:
            library.delete_part(path)
        except Exception as exc:
            App.Console.PrintError("Pipe Harness Library: could not delete (%s)\n" % exc)
            return
        self.refresh()

    def _move_part(self, item):
        path = item.data(0, _PATH_ROLE)
        choices = _folder_choices()
        displays = [display for display, _rel in choices]
        current_rel = os.path.relpath(os.path.dirname(path), library.LIBRARY_ROOT)
        if current_rel == ".":
            current_rel = ""
        try:
            current_index = [rel for _display, rel in choices].index(current_rel)
        except ValueError:
            current_index = 0
        choice, ok = QtGui.QInputDialog.getItem(
            self, "Move Part", "Destination folder:", displays, current_index, True
        )
        if not ok:
            return
        folder = _resolve_folder_choice(choice, choices)
        try:
            library.move_part(path, folder)
        except Exception as exc:
            App.Console.PrintError("Pipe Harness Library: could not move (%s)\n" % exc)
            return
        self.refresh()

    def _on_double_click(self, item, _column):
        if not item.data(0, _IS_FOLDER_ROLE):
            self._insert_path(item.data(0, _PATH_ROLE))

    def _insert_selected(self):
        item = self.tree.currentItem()
        if item is None or item.data(0, _IS_FOLDER_ROLE):
            App.Console.PrintError("Pipe Harness Library: select a part to insert.\n")
            return
        self._insert_path(item.data(0, _PATH_ROLE))

    def _insert_path(self, filepath):
        doc = App.ActiveDocument or App.newDocument()
        try:
            library.insert_part(filepath, doc)
            doc.recompute()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as exc:
            App.Console.PrintError("Pipe Harness Library: could not insert '%s' (%s)\n" % (filepath, exc))


_panel_instance = None


def get_or_create_panel():
    """The single shared LibraryPanel instance, creating and docking it into
    FreeCAD's main window the first time this is called.
    """
    global _panel_instance
    if _panel_instance is None:
        _panel_instance = LibraryPanel(Gui.getMainWindow())
        Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, _panel_instance)
    return _panel_instance
