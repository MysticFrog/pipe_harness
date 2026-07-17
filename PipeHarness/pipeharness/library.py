"""Local parts library: export a component (with its connection points) to a
reusable .FCStd file under a local library folder, and insert one back into
the active document.

The actual save/load mechanism was verified directly (headless) before relying
on it: `target_doc.copyObject(obj, True)` recursively copies an object and its
dependents into another document (including reconstructing custom FeaturePython
proxies like ConnectionPoint correctly), and a document containing just that
copy can be saved/reopened as a standalone .FCStd - there is no dedicated
"export a subset of objects" call in this FreeCAD version, so a throwaway
document is used as the vehicle for both directions.
"""
import os

import FreeCAD as App

LIBRARY_ROOT = os.path.join(App.getUserAppDataDir(), "PipeHarnessLibrary")


def ensure_library_root():
    os.makedirs(LIBRARY_ROOT, exist_ok=True)
    return LIBRARY_ROOT


def create_folder(relative_path):
    """Create a folder (and any parents) under the library root."""
    ensure_library_root()
    full = os.path.join(LIBRARY_ROOT, relative_path)
    os.makedirs(full, exist_ok=True)
    return full


def export_part(part, filename, folder=""):
    """Save `part` (an App::Part) as a standalone library file, with its
    Placement reset to the origin (a library part should drop in ready to be
    positioned, not wherever it happened to sit in the file it came from).
    `filename` should not include an extension; `folder` is a path relative to
    the library root ("" = the root itself). Returns the saved file path.
    """
    ensure_library_root()
    target_dir = os.path.join(LIBRARY_ROOT, folder) if folder else LIBRARY_ROOT
    os.makedirs(target_dir, exist_ok=True)
    out_path = os.path.join(target_dir, filename + ".FCStd")

    temp_doc = App.newDocument("PipeHarnessLibraryExport")
    try:
        copied = temp_doc.copyObject(part, True)
        copied.Placement = App.Placement()
        temp_doc.recompute()
        temp_doc.saveAs(out_path)
    finally:
        App.closeDocument(temp_doc.Name)
    return out_path


def insert_part(filepath, target_doc):
    """Insert a library part (a .FCStd file previously saved by export_part)
    into target_doc. Returns the newly-inserted App::Part.
    """
    temp_doc = App.openDocument(filepath)
    try:
        parts = [o for o in temp_doc.Objects if o.TypeId == "App::Part"]
        if not parts:
            raise ValueError("No component (App::Part) found in library file %s" % filepath)
        copied = target_doc.copyObject(parts[0], True)
        target_doc.recompute()
        return copied
    finally:
        App.closeDocument(temp_doc.Name)


def list_tree(root=None):
    """A nested {"folders": {name: subtree}, "parts": [(label, filepath), ...]}
    structure describing the library, for populating the library panel.
    """
    root = root or ensure_library_root()
    tree = {"folders": {}, "parts": []}
    for entry in sorted(os.listdir(root)):
        full = os.path.join(root, entry)
        if os.path.isdir(full):
            tree["folders"][entry] = list_tree(full)
        elif entry.lower().endswith(".fcstd"):
            tree["parts"].append((os.path.splitext(entry)[0], full))
    return tree


def list_folders():
    """Every folder in the library, as paths relative to the library root
    (the root itself is not included; each entry uses the OS separator).
    Sorted, for populating a "pick a folder" dropdown.
    """
    root = ensure_library_root()
    folders = []
    for dirpath, dirnames, _files in os.walk(root):
        for name in dirnames:
            folders.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(folders)


def _inside_library(path):
    """Guard: True only if `path` resolves to somewhere inside the library
    root - so delete/move can never touch a file elsewhere on disk even if
    handed a bad path.
    """
    root = os.path.abspath(ensure_library_root())
    ap = os.path.abspath(path)
    return ap == root or ap.startswith(root + os.sep)


def _validate_part_path(filepath, verb):
    if not _inside_library(filepath):
        raise ValueError("Refusing to %s a path outside the parts library: %s" % (verb, filepath))
    if not filepath.lower().endswith(".fcstd") or not os.path.isfile(filepath):
        raise ValueError("Not a library part file: %s" % filepath)


def delete_part(filepath):
    """Delete a single library part file (a .FCStd previously saved by
    export_part). Guarded to only ever remove a real part file inside the
    library.
    """
    _validate_part_path(filepath, "delete")
    os.remove(filepath)


def move_part(filepath, dest_rel_folder):
    """Move a library part into dest_rel_folder (relative to the library root;
    "" means the root itself), creating that folder if needed. Returns the new
    path. Raises FileExistsError if a part of the same name is already there.
    """
    _validate_part_path(filepath, "move")
    ensure_library_root()
    dest_dir = os.path.join(LIBRARY_ROOT, dest_rel_folder) if dest_rel_folder else LIBRARY_ROOT
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(filepath))
    if os.path.abspath(dest) == os.path.abspath(filepath):
        return filepath  # already there - no-op
    if os.path.exists(dest):
        raise FileExistsError(
            "A part named '%s' already exists in that folder." % os.path.basename(filepath)
        )
    import shutil
    shutil.move(filepath, dest)
    return dest
