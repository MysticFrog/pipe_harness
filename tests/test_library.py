"""Headless verification of the parts-library backend, run via FreeCADCmd.exe:

    FreeCADCmd.exe test_library.py

Covers the export/organize operations behind the Parts Library panel: exporting
a component into a chosen (possibly new, nested) folder, listing folders,
moving a part between folders (including the no-op and name-collision cases),
deleting a part, and the safety guards that keep delete/move from touching
anything outside the library root. The library root is redirected to a scratch
directory so the real user library is never touched.
"""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "PipeHarness"))

import FreeCAD as App

from pipeharness import library
from pipeharness import objects


def make_part(doc, name):
    block = doc.addObject("Part::Box", name + "Block")
    block.Length = block.Width = block.Height = 10
    part = doc.addObject("App::Part", name)
    part.addObject(block)
    doc.recompute()
    objects.create_connection_point(doc, part, App.Vector(10, 5, 5), App.Vector(1, 0, 0), name=name + "CP")
    doc.recompute()
    return part


def main():
    tmp = tempfile.mkdtemp(prefix="phlib_test_")
    library.LIBRARY_ROOT = tmp
    try:
        doc = App.newDocument("LibraryTest")
        part = make_part(doc, "Elbow")

        # Export into an existing folder, a brand-new nested folder (created on
        # demand), and the root.
        p_fit = library.export_part(part, "elbow90", folder="Fittings")
        assert os.path.isfile(p_fit)
        assert os.path.dirname(p_fit) == os.path.join(tmp, "Fittings")

        nested_rel = os.path.join("Fittings", "Metric")
        p_nested = library.export_part(part, "elbow45", folder=nested_rel)
        assert os.path.isfile(p_nested), "export should create a new nested folder on demand"

        p_root = library.export_part(part, "loose")
        assert os.path.dirname(p_root) == tmp, "no folder should export to the root"

        folders = library.list_folders()
        assert "Fittings" in folders and nested_rel in folders, (
            "list_folders should report the created folders: %s" % folders
        )

        # Move a part between folders.
        moved = library.move_part(p_fit, nested_rel)
        assert os.path.isfile(moved) and not os.path.exists(p_fit), "move should relocate the file"
        assert os.path.normpath(os.path.dirname(moved)) == os.path.normpath(os.path.join(tmp, nested_rel))

        # Move to the root.
        moved_root = library.move_part(moved, "")
        assert os.path.dirname(moved_root) == tmp

        # Moving to the folder it's already in is a harmless no-op.
        again = library.move_part(moved_root, "")
        assert again == moved_root

        # A name collision on move must be refused, not silently overwrite.
        p_dup = library.export_part(part, "elbow90", folder="Fittings")
        collided = False
        try:
            library.move_part(p_dup, "")  # 'elbow90' already exists at root
        except FileExistsError:
            collided = True
        assert collided, "moving onto an existing same-name part should raise"
        assert os.path.isfile(p_dup), "the source part should survive a refused move"

        # Delete.
        library.delete_part(moved_root)
        assert not os.path.exists(moved_root), "delete_part should remove the file"

        # Guards: never touch anything outside the library root, never a non-part.
        outside = os.path.join(tempfile.gettempdir(), "definitely_outside.FCStd")
        blocked = False
        try:
            library.delete_part(outside)
        except ValueError:
            blocked = True
        assert blocked, "delete outside the library root must be refused"

        not_a_part = os.path.join(tmp, "notes.txt")
        with open(not_a_part, "w") as fh:
            fh.write("x")
        blocked = False
        try:
            library.delete_part(not_a_part)
        except ValueError:
            blocked = True
        assert blocked, "delete of a non-.FCStd file must be refused"

        print("ALL CHECKS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


main()
