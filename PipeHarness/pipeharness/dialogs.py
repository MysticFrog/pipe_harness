# SPDX-License-Identifier: MIT
"""Modal dialogs for the "Add Straight Segment" and "Add Bend Segment" commands.

Both create the new segment immediately (with default values) when the dialog
opens, so it's visible in the 3D view right away, then live-update it as the
user changes a field - before OK is even pressed. Cancelling (or closing the
dialog) removes the tentative segment again, restoring the hose to how it was.

Kept as two separate, minimal dialogs (rather than one combined form) since a
straight run and a bend are two different kinds of thing to add, each with its
own distinct fields.
"""
import FreeCAD as App

from .qtcompat import QtGui
from . import objects


def _tr(text):
    """Translate a user-facing string in the 'PipeHarness' context (returns the
    source text unchanged when no translation is loaded)."""
    return App.Qt.translate("PipeHarness", text)


def _spin(value, minimum, maximum, suffix):
    box = QtGui.QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(2)
    box.setSuffix(suffix)
    box.setValue(value)
    return box


class _SegmentDialog(QtGui.QDialog):
    """Shared undo handling for the segment dialogs.

    The tentative segment is created inside a document transaction opened when
    the dialog opens, so pressing OK leaves exactly one undoable step ("add a
    segment") and Cancel rolls the whole tentative edit back. FreeCAD does not
    wrap Python command execution in a transaction for us, so without this the
    added segment wouldn't be on the undo stack at all.
    """

    def _begin(self, hose, title):
        self.setWindowTitle(title)
        self.hose = hose
        self.doc = hose.Document
        self.segment = None
        self._settled = False
        self.doc.openTransaction(title)

    def accept(self):
        self._settle(commit=True)
        super().accept()

    def reject(self):
        self._settle(commit=False)
        super().reject()

    def _settle(self, commit):
        if self._settled:
            return
        self._settled = True
        if commit:
            self.doc.commitTransaction()
        else:
            self.doc.abortTransaction()
            # If undo happens to be disabled the abort is a no-op, so make sure
            # the tentative segment is gone either way.
            try:
                stale = self.segment is not None and self.segment.Name in [
                    o.Name for o in self.doc.Objects
                ]
            except Exception:
                stale = False
            if stale:
                _remove_preview_segment(self.hose, self.segment)
        self.doc.recompute()


class StraightSegmentDialog(_SegmentDialog):
    def __init__(self, hose, parent=None):
        super().__init__(parent)
        self._begin(hose, _tr("Add Straight Segment"))

        self.length = _spin(objects._DEFAULT_SEGMENT_LENGTH, 0.01, 100000.0, " mm")
        self.segment = objects.add_straight_to_hose(self.hose, self.length.value())
        self.doc.recompute()
        self.length.valueChanged.connect(self._update_preview)

        form = QtGui.QFormLayout()
        form.addRow(_tr("Straight Length"), self.length)

        buttons = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtGui.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _update_preview(self):
        self.segment.Length = self.length.value()
        self.doc.recompute()


class BendSegmentDialog(_SegmentDialog):
    def __init__(self, hose, parent=None):
        super().__init__(parent)
        self._begin(hose, _tr("Add Bend Segment"))

        self.radius = _spin(objects._DEFAULT_BEND_RADIUS, 0.0, 100000.0, " mm")
        self.swept_angle = _spin(90.0, 0.0, 180.0, " deg")
        self.yaw = _spin(0.0, -360.0, 360.0, " deg")
        # Pitch (the other axis-choosing angle) is left at 0 here for the
        # common case - still editable afterward on the PipeBend object's own
        # Data tab if a specific 3D bend plane is needed.
        self.segment = objects.add_bend_to_hose(
            self.hose, self.radius.value(), self.swept_angle.value(), self.yaw.value(), 0.0, 0.0
        )
        self.doc.recompute()
        self.radius.valueChanged.connect(self._update_preview)
        self.swept_angle.valueChanged.connect(self._update_preview)
        self.yaw.valueChanged.connect(self._update_preview)

        form = QtGui.QFormLayout()
        form.addRow(_tr("Bend Radius"), self.radius)
        form.addRow(_tr("Swept Angle (0 = straight)"), self.swept_angle)
        form.addRow(_tr("Yaw (bend axis)"), self.yaw)

        buttons = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtGui.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _update_preview(self):
        self.segment.Radius = self.radius.value()
        self.segment.SweptAngle = self.swept_angle.value()
        self.segment.Yaw = self.yaw.value()
        self.doc.recompute()


def _remove_preview_segment(hose, segment):
    """Undo the tentative add: drop the segment from the hose's Segments list
    (BendSegmentDialog's segment may already have been dropped if the user
    somehow re-ran this - guarded defensively) and delete the object itself.
    """
    doc = hose.Document
    segments = list(hose.Segments)
    if segment in segments:
        segments.remove(segment)
        hose.Segments = segments
    if segment.Name in [o.Name for o in doc.Objects]:
        doc.removeObject(segment.Name)
    doc.recompute()
