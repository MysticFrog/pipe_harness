"""Small compatibility shim so the rest of the package can just
``from .qtcompat import QtGui`` regardless of FreeCAD version: 1.0+ uses
PySide6 (QFileDialog, QDialog, etc. live in QtWidgets), 0.2x uses FreeCAD's
own PySide (Qt5) shim, which exposes them under QtGui instead.
"""
try:
    from PySide6 import QtWidgets as QtGui
    from PySide6 import QtCore
except ImportError:
    from PySide import QtGui
    from PySide import QtCore
