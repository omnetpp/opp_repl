"""
PyQt6 GUI for browsing chart diff triples (<stem>.png, <stem>-new.png,
<stem>-old.png, <stem>-diff.png) under a folder.

Usage from a shell::

    opp_diff_charts /path/to/folder

Usage from Python::

    from opp_repl.diffcharts import main
    main("/path/to/folder")

PyQt6 is an optional dependency: install with ``pip install opp_repl[diffcharts]``.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    from PyQt6 import QtCore, QtGui, QtWidgets
except ImportError as _pyqt6_import_error:
    raise ImportError(
        "PyQt6 is required to use opp_repl.diffcharts. "
        "Install with: pip install 'opp_repl[diffcharts]'"
    ) from _pyqt6_import_error


@dataclass(frozen=True)
class DiffEntry:
    base: str          # absolute path without suffixes (directory + basename without "-new"/"-old"/"-diff")
    dirpath: str       # directory containing the images
    name: str          # relative display name (directory basename + base file)
    diff_path: str     # {stem}-diff.png (may be None if missing)
    current_path: str  # {stem}.png (may be None if missing)
    old_path: str      # {stem}-old.png (may be None if missing)
    new_path: str      # {stem}-new.png (may be None if missing)
    metric: Optional[float] = None  # RMSE between -old and -new; None when both files don't exist or matplotlib is unavailable


def _compute_metric(old_path: Optional[str], new_path: Optional[str]) -> Optional[float]:
    """Return the RMSE between two PNGs, or ``None`` if it cannot be computed.

    Uses the same metric as the chart-test pipeline (so the value here
    matches what ``run_chart_tests`` / module-image tests report).  Lazy-
    imports matplotlib so the GUI itself stays usable without the
    ``chart`` extras installed — in that case the column shows ``None``.
    """
    if not old_path or not new_path:
        return None
    try:
        from opp_repl.test.chart import compute_chart_image_diff
    except ImportError:
        return None
    try:
        # diff_file_name=None: compute the metric without writing a diff image.
        return compute_chart_image_diff(old_path, new_path, diff_file_name=None)
    except Exception:
        return None


@dataclass(frozen=True)
class _DiffCandidate:
    """Discovered PNG group before the (slow) RMSE metric is computed.

    Mirrors :class:`DiffEntry` minus the ``metric`` field — produced by the
    cheap directory-walk phase so the expensive per-candidate RMSE can be
    deferred / parallelised / streamed.
    """
    base: str
    dirpath: str
    name: str
    diff_path: Optional[str]
    current_path: Optional[str]
    old_path: Optional[str]
    new_path: Optional[str]


def _collect_diff_candidates(root: str) -> List[_DiffCandidate]:
    """Walk *root* and return the sorted list of PNG groups that need a diff,
    without computing per-group metrics.
    """
    candidates: List[_DiffCandidate] = []
    stems_seen = set()  # Track (dirpath, stem) to avoid duplicates

    for dirpath, _dirs, files in os.walk(root):
        pngs = {f for f in files if f.lower().endswith(".png")}

        # Find all potential stems by checking for any of the three suffixes
        for f in pngs:
            stem = None
            if f.lower().endswith("-new.png"):
                stem = f[:-len("-new.png")]
            elif f.lower().endswith("-old.png"):
                stem = f[:-len("-old.png")]
            elif not f.lower().endswith("-new.png") and not f.lower().endswith("-old.png"):
                # This is a base .png file (not ending in -new or -old)
                stem = f[:-len(".png")]

            if not stem or (dirpath, stem) in stems_seen:
                continue
            stems_seen.add((dirpath, stem))

            # Check which files exist
            diff_name = f"{stem}-diff.png"
            current_name = f"{stem}.png"
            old_name = f"{stem}-old.png"
            new_name = f"{stem}-new.png"

            diff_path = os.path.join(dirpath, diff_name) if diff_name in pngs else None
            current_path = os.path.join(dirpath, current_name) if current_name in pngs else None
            old_path = os.path.join(dirpath, old_name) if old_name in pngs else None
            new_path = os.path.join(dirpath, new_name) if new_name in pngs else None

            # Skip if old and new exist and are byte-identical - nothing to diff
            if new_path and old_path and filecmp.cmp(new_path, old_path, shallow=False):
                continue

            # Only add if at least one of NEW or OLD exists
            if not (new_path or old_path):
                continue

            # Display name: relative to root or folder+stem
            rel_dir = os.path.relpath(dirpath, root)
            display = os.path.join(rel_dir, stem) if rel_dir != "." else stem
            candidates.append(_DiffCandidate(
                base=os.path.join(dirpath, stem),
                dirpath=dirpath,
                name=display,
                diff_path=diff_path,
                current_path=current_path,
                old_path=old_path,
                new_path=new_path,
            ))

    # Sort consistently (by relative display name, then by dir)
    candidates.sort(key=lambda c: (c.name.lower(), c.dirpath.lower()))
    return candidates


def _finalize_candidate(c: _DiffCandidate) -> DiffEntry:
    """Compute the RMSE for one candidate and return the full :class:`DiffEntry`."""
    return DiffEntry(
        base=c.base,
        dirpath=c.dirpath,
        name=c.name,
        diff_path=c.diff_path,
        current_path=c.current_path,
        old_path=c.old_path,
        new_path=c.new_path,
        metric=_compute_metric(c.old_path, c.new_path),
    )


def find_diff_entries(root: str) -> List[DiffEntry]:
    """
    Scan 'root' recursively and find entries with any of: <foo>.png, <foo>-new.png, <foo>-old.png
    (at least one must exist in the same directory).
    """
    return [_finalize_candidate(c) for c in _collect_diff_candidates(root)]


class ImageCache:
    """Tiny pixmap cache to avoid reloading on every resize."""
    def __init__(self) -> None:
        self._cache: dict[str, QtGui.QPixmap] = {}

    def get(self, path: str) -> QtGui.QPixmap:
        pm = self._cache.get(path)
        if pm is None or pm.isNull():
            pm = QtGui.QPixmap(path)
            self._cache[path] = pm
        return pm

    def clear(self) -> None:
        self._cache.clear()


class ThumbLabel(QtWidgets.QLabel):
    """QLabel that keeps aspect ratio on resize."""
    def __init__(self, path: str, cache: ImageCache, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(4, 4)
        self._path = path
        self._cache = cache
        self._last_scaled_for: Tuple[int, int] | None = None
        self._orig = None  # QPixmap
        self.updatePixmap()

    def setPath(self, path: str) -> None:
        self._path = path
        self._orig = None
        self._last_scaled_for = None
        self.updatePixmap()

    def updatePixmap(self) -> None:
        if not self._orig:
            self._orig = self._cache.get(self._path)
        self._applyScale()

    def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
        super().resizeEvent(ev)
        self._applyScale()

    def _applyScale(self) -> None:
        if not self._orig:
            return
        size = self.size()
        key = (size.width(), size.height())
        if self._last_scaled_for == key:
            return
        scaled = self._orig.scaled(
            size,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self._last_scaled_for = key


class DiffTable(QtWidgets.QTableWidget):
    """Table showing {stem}.png | {stem}-new.png | {stem}-old.png thumbnails, supports Ctrl+Wheel scaling."""
    scaleChanged = QtCore.pyqtSignal(float)  # emits new scale

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels(["Index", "DIFF", "CURRENT", "OLD", "NEW", "Metric", "Path"])
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setIconSize(QtCore.QSize(64, 64))
        # Smooth scrolling looks nicer for images
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        # Avoid stretching columns unevenly; we'll set fixed widths per row-height
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)

        # Add minimal spacing between rows using stylesheet
        self.setStyleSheet("""
            QTableWidget::item {
                border-bottom: 2px solid transparent;
                margin-bottom: 2px;
            }
        """)

        # Thumbnail scaling state
        self._scale = 1.0  # multiplicative factor (10% steps)
        self._base_side = 200  # will be computed by window based on screen height

    def setBaseThumbSide(self, side_px: int) -> None:
        self._base_side = max(40, side_px)
        self._applySizes()

    def currentScale(self) -> float:
        return self._scale

    def setScale(self, scale: float) -> None:
        scale = max(0.1, min(5.0, scale))
        if abs(scale - self._scale) > 1e-6:
            self._scale = scale
            self._applySizes()
            self.scaleChanged.emit(self._scale)

    def wheelEvent(self, e: QtGui.QWheelEvent) -> None:
        if e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            angle = e.angleDelta().y()
            if angle != 0:
                step = 0.10  # 10% per notch
                new_scale = self._scale * (1.0 + step) if angle > 0 else self._scale * (1.0 - step)
                self.setScale(new_scale)
            e.accept()
            return
        super().wheelEvent(e)

    def _applySizes(self) -> None:
        side = int(self._base_side * self._scale)
        # Row height: image size + minimum padding + vertical spacing between rows
        row_h = max(40, int(side * 0.6) + 12)  # Images typically use ~60% due to aspect ratio + 12px for padding and spacing
        for r in range(self.rowCount()):
            self.setRowHeight(r, row_h)

        # Calculate maximum path width needed based on relative paths
        max_path_width = 200  # minimum width
        if hasattr(self, '_entries') and self._entries:
            # Create a font metrics object to measure text width
            font = QtGui.QFont()
            font.setPointSize(12)  # Match the path label font size
            fm = QtGui.QFontMetrics(font)

            anchor = getattr(self, '_root_dir', None) or os.getcwd()
            # Find the longest relative path text
            for entry in self._entries:
                base_path = entry.diff_path or entry.current_path or entry.old_path or entry.new_path
                relative_path = os.path.relpath(base_path, anchor)
                text_width = fm.horizontalAdvance(relative_path) + 16  # Reduced padding since paths are shorter
                max_path_width = max(max_path_width, text_width)

        # Metric column width: enough for "0.123456" + a bit
        font = QtGui.QFont()
        font.setPointSize(12)
        fm = QtGui.QFontMetrics(font)
        metric_width = fm.horizontalAdvance("0.123456") + 16

        # Column width: add minimum padding between columns
        for c in range(self.columnCount()):
            if c == 0:  # Index column
                self.setColumnWidth(c, max(60, int(side * 0.3) + 8))  # Add padding
            elif c == 5:  # Metric column
                self.setColumnWidth(c, metric_width)
            elif c == 6:  # Path column
                self.setColumnWidth(c, max_path_width + 8)  # Add padding
            else:  # Image columns (DIFF, CURRENT, OLD, NEW)
                self.setColumnWidth(c, side + 8)  # Add padding between columns

    def setRowWidgets(self, row: int, widgets: Tuple[QtWidgets.QWidget, ...]) -> None:
        for col, w in enumerate(widgets):
            if w is not None:
                self.setCellWidget(row, col, w)

    def setEntries(self, entries: List[DiffEntry], root_dir: str | None = None) -> None:
        """Set the entries data for path width calculations."""
        self._entries = entries
        self._root_dir = root_dir


class ImageView(QtWidgets.QLabel):
    """Single-image view that scales to fit the window."""
    # Signal emitted when mouse wheel is used for navigation
    wheelNavigation = QtCore.pyqtSignal(int)  # emits +1 for down/forward, -1 for up/backward

    def __init__(self, cache: ImageCache, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._cache = cache
        self._path = ""
        self._orig = None

    def setImagePath(self, path: str) -> None:
        self._path = path
        self._orig = self._cache.get(path)
        self._rescale()

    def clearImage(self) -> None:
        self._path = ""
        self._orig = None
        self.clear()

    def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
        super().resizeEvent(ev)
        self._rescale()

    def _rescale(self) -> None:
        if not self._orig:
            return
        target = self.size()
        pm = self._orig.scaled(
            target,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pm)

    def wheelEvent(self, e: QtGui.QWheelEvent) -> None:
        """Handle mouse wheel events for diff navigation."""
        angle = e.angleDelta().y()
        if angle != 0:
            if e.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                # Shift + wheel: cycle between diff/old/new (like left/right arrows)
                # Use different signal values to distinguish from regular navigation
                direction = +100 if angle < 0 else -100  # +/-100 indicates image type cycling
            else:
                # Regular wheel: navigate between entries (like up/down arrows)
                direction = +1 if angle < 0 else -1  # +/-1 indicates entry navigation

            self.wheelNavigation.emit(direction)
            e.accept()
            return
        super().wheelEvent(e)


class _ScanWorker(QtCore.QObject):
    """Background scan: collect candidates, compute RMSE per candidate, stream
    the resulting :class:`DiffEntry` objects to the GUI in small batches.

    The generation tag lets the GUI ignore stragglers from an older scan after
    the user hits F5.
    """
    discovery_started = QtCore.pyqtSignal(int)              # generation
    candidates_collected = QtCore.pyqtSignal(int, int)       # generation, total
    batch_ready = QtCore.pyqtSignal(int, object)             # generation, List[DiffEntry]
    failed = QtCore.pyqtSignal(int, str)                     # generation, message
    finished = QtCore.pyqtSignal(int)                        # generation

    BATCH_SIZE = 8

    def __init__(self, root: str, generation: int) -> None:
        super().__init__()
        self._root = root
        self.generation = generation
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            self.discovery_started.emit(self.generation)
            candidates = _collect_diff_candidates(self._root)
            if self._cancel:
                self.finished.emit(self.generation)
                return
            self.candidates_collected.emit(self.generation, len(candidates))
            batch: List[DiffEntry] = []
            for c in candidates:
                if self._cancel:
                    break
                batch.append(_finalize_candidate(c))
                if len(batch) >= self.BATCH_SIZE:
                    self.batch_ready.emit(self.generation, batch)
                    batch = []
            if batch and not self._cancel:
                self.batch_ready.emit(self.generation, batch)
        except Exception as ex:
            self.failed.emit(self.generation, str(ex))
        self.finished.emit(self.generation)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, root_dir: str) -> None:
        super().__init__()
        self.setWindowTitle("Image Diff Browser")
        self._root_dir = os.path.abspath(root_dir)
        self._cache = ImageCache()
        self._entries: List[DiffEntry] = []
        self._current_index = -1   # index in self._entries for viewer
        self._current_kind = 0     # 0=diff,1=current,2=old,3=new
        self._kinds = ("diff", "current", "old", "new")

        # Async scan state. `_live_scans` keeps Python refs to all (thread,
        # worker) pairs that haven't yet emitted thread.finished — even
        # cancelled ones — so QThread C++ objects don't get destroyed while
        # the underlying OS thread is still running.
        self._scan_thread: Optional[QtCore.QThread] = None
        self._scan_worker: Optional[_ScanWorker] = None
        self._live_scans: dict[int, tuple[QtCore.QThread, _ScanWorker]] = {}
        self._scan_generation = 0
        self._scan_total = 0
        self._refresh_initial = True
        self._size_apply_pending = False

        # Pre-warm the matplotlib-based metric computation on the main thread.
        # _compute_metric lazy-imports opp_repl.test.chart which pulls in
        # matplotlib; doing that first-time import from a non-main QThread
        # has been observed to clash with Qt and abort the process.
        try:
            import opp_repl.test.chart  # noqa: F401
        except ImportError:
            pass

        # Central stacked layout: [0]=table page, [1]=viewer page
        self._stack = QtWidgets.QStackedWidget(self)
        self.setCentralWidget(self._stack)

        # Table page
        self._table = DiffTable(self)
        self._table.doubleClicked.connect(self._on_table_double_clicked)
        self._stack.addWidget(self._table)

        # Viewer page
        self._viewer = ImageView(self._cache, self)
        self._viewer.wheelNavigation.connect(self._on_viewer_wheel_navigation)
        self._stack.addWidget(self._viewer)

        # Status bar with progress feedback for the async scan
        self._progress = QtWidgets.QProgressBar(self)
        self._progress.setMaximumWidth(240)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._progress)

        # Actions
        refresh = QtGui.QAction(self)
        refresh.setShortcut(QtGui.QKeySequence.StandardKey.Refresh)  # F5
        refresh.triggered.connect(self.refresh)
        self.addAction(refresh)

        # After show, set initial thumbs to fit ~3 rows on the current screen
        QtCore.QTimer.singleShot(0, self._init_base_thumb_side)

        # Initial data: starts a background worker; rows stream in.
        self.refresh(initial=True)

    # ----- Data scanning & table population -----

    def refresh(self, *, initial: bool = False) -> None:
        """(Re)scan directory and rebuild table asynchronously.

        Discovery and per-image RMSE run on a background QThread; rows stream
        into the table as they're produced. F5 cancels any in-flight scan and
        starts a fresh one — late signals from the previous worker are
        discarded via the generation tag.
        """
        # Cancel any in-flight scans; their remaining signals get ignored
        # via the generation check in the slots, and their (thread, worker)
        # tuples stay in _live_scans until thread.finished fires.
        for _t, _w in self._live_scans.values():
            _w.cancel()

        self._scan_generation += 1
        generation = self._scan_generation
        self._refresh_initial = initial

        # Reset state
        self._entries = []
        self._cache.clear()
        self._table.setRowCount(0)
        self._table.setEntries(self._entries, self._root_dir)
        self._scan_total = 0

        # Status feedback: indeterminate bar during discovery.
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self.statusBar().showMessage(f"Scanning {self._root_dir}…")

        # Spawn worker on its own QThread.
        thread = QtCore.QThread()
        worker = _ScanWorker(self._root_dir, generation)
        worker.moveToThread(thread)
        worker.discovery_started.connect(self._on_discovery_started)
        worker.candidates_collected.connect(self._on_candidates_collected)
        worker.batch_ready.connect(self._on_batch_ready)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_scan_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        self._live_scans[generation] = (thread, worker)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _append_entry_row(self, ent: DiffEntry) -> None:
        """Append one DiffEntry as a new row in the table."""
        row = len(self._entries)
        self._entries.append(ent)
        self._table.setRowCount(row + 1)

        # Row header text: show a short label so user knows which diff this is.
        item = QtWidgets.QTableWidgetItem(ent.name)
        item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
        self._table.setVerticalHeaderItem(row, item)

        # Create index label (starting from 1)
        index_w = QtWidgets.QLabel(str(row + 1), self._table)
        index_w.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        index_w.setStyleSheet("font-weight: bold; font-size: 14px;")

        # Create widgets only for existing files
        diff_w = ThumbLabel(ent.diff_path, self._cache, self._table) if ent.diff_path else None
        current_w = ThumbLabel(ent.current_path, self._cache, self._table) if ent.current_path else None
        old_w = ThumbLabel(ent.old_path, self._cache, self._table) if ent.old_path else None
        new_w = ThumbLabel(ent.new_path, self._cache, self._table) if ent.new_path else None

        # Metric label (RMSE between old and new)
        if ent.metric is None:
            metric_text = "—"
        elif ent.metric == 0:
            metric_text = "0"
        else:
            metric_text = f"{ent.metric:.6f}"
        metric_w = QtWidgets.QLabel(metric_text, self._table)
        metric_w.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        metric_w.setStyleSheet("font-family: monospace; font-size: 12px; padding: 2px;")
        if ent.metric is not None and ent.metric > 0:
            metric_w.setToolTip(f"RMSE = {ent.metric}")

        # Create path label - show path relative to the scanned root (the
        # staging_dir when invoked from compare_charts), falling back to cwd
        # if no root is set. Fall back across image kinds since -old.png and
        # -new.png may be the only files present.
        display_path = ent.current_path or ent.diff_path or ent.new_path or ent.old_path
        if display_path:
            relative_path = os.path.relpath(display_path, self._root_dir or os.getcwd())
            path_w = QtWidgets.QLabel(relative_path, self._table)
            path_w.setToolTip(display_path)
        else:
            path_w = QtWidgets.QLabel("", self._table)
        path_w.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        path_w.setStyleSheet("font-size: 14px; padding: 2px;")

        self._table.setRowWidgets(row, (index_w, diff_w, current_w, old_w, new_w, metric_w, path_w))

    # ----- Async scan signal handlers -----

    def _on_discovery_started(self, generation: int) -> None:
        if generation != self._scan_generation:
            return
        self.statusBar().showMessage(f"Scanning {self._root_dir}…")

    def _on_candidates_collected(self, generation: int, total: int) -> None:
        if generation != self._scan_generation:
            return
        self._scan_total = total
        if total == 0:
            self._progress.setRange(0, 1)
            self._progress.setValue(1)
            self.statusBar().showMessage("No diff entries found.")
        else:
            self._progress.setRange(0, total)
            self._progress.setValue(0)
            self.statusBar().showMessage(f"Comparing 0 / {total} images…")

    def _on_batch_ready(self, generation: int, batch: object) -> None:
        if generation != self._scan_generation:
            return
        for ent in batch:  # type: ignore[union-attr]
            self._append_entry_row(ent)
        self._table.setEntries(self._entries, self._root_dir)
        self._progress.setValue(len(self._entries))
        self.statusBar().showMessage(
            f"Comparing {len(self._entries)} / {self._scan_total} images…"
        )
        # Coalesced thumb/column resize — kept off the per-batch hot path.
        self._schedule_size_apply()

    def _on_scan_failed(self, generation: int, message: str) -> None:
        if generation != self._scan_generation:
            return
        self.statusBar().showMessage(f"Scan failed: {message}")

    def _on_scan_finished(self, generation: int) -> None:
        # Stragglers from a cancelled scan: ignore — _on_thread_finished
        # below clears the refs once the OS thread actually exits.
        if generation != self._scan_generation:
            return
        self._progress.setVisible(False)
        total = len(self._entries)
        if total == 0:
            self.statusBar().showMessage("No diff entries found.")
        else:
            self.statusBar().showMessage(f"{total} entries loaded.", 5000)

        # If we were in viewer mode, try to keep position (clamped)
        initial = self._refresh_initial
        if not initial and self._stack.currentIndex() == 1 and self._entries:
            self._current_index = max(0, min(self._current_index, total - 1))
            self._current_kind = 0  # switch to diff on refresh
            self._show_current_in_viewer()
        elif self._stack.currentIndex() == 1 and not self._entries:
            self._viewer.clearImage()

        # Final pass to settle column widths against the full entries list.
        self._apply_sizes_from_window()
        # NB: self._scan_thread / self._scan_worker are cleared in
        # _on_thread_finished — clearing them here would drop the Python
        # ref before QThread's event loop has actually exited, causing a
        # "QThread destroyed while still running" abort.

    def _on_thread_finished(self) -> None:
        """Connected to ``QThread.finished``; safe to drop our Python refs now."""
        sender = self.sender()
        # Drop the live-scan entry whose thread emitted this signal.
        for gen, (thread, _worker) in list(self._live_scans.items()):
            if thread is sender:
                del self._live_scans[gen]
                break
        if sender is self._scan_thread:
            self._scan_thread = None
            self._scan_worker = None

    def _schedule_size_apply(self) -> None:
        """Coalesce repeated `_apply_sizes_from_window` calls during streaming.

        `_applySizes` iterates `self._entries` to recompute the path column
        width, so calling it per row would be O(N²). A short single-shot timer
        merges back-to-back batches into one repaint.
        """
        if self._size_apply_pending:
            return
        self._size_apply_pending = True
        QtCore.QTimer.singleShot(50, self._do_size_apply)

    def _do_size_apply(self) -> None:
        self._size_apply_pending = False
        self._apply_sizes_from_window()

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:
        # Stop any background scans before destruction so their threads
        # don't outlive the widgets they talk to.
        for thread, worker in self._live_scans.values():
            worker.cancel()
        for thread, _worker in list(self._live_scans.values()):
            thread.quit()
            thread.wait(2000)
        super().closeEvent(ev)

    # ----- Sizing logic -----

    def _init_base_thumb_side(self) -> None:
        # Choose base thumbnail side so ~3 rows fit on the current (maximized) window
        # Account for horizontal header + some padding.
        h = self.height()
        header_h = self._table.horizontalHeader().height()
        effective = max(100, h - header_h - 60)
        per_row = int(effective / 3)
        base_side = max(60, per_row - 2)  # leave minimal margin inside the row
        self._table.setBaseThumbSide(base_side)

    def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
        super().resizeEvent(ev)
        # Recompute base so that ~3 rows fit whenever the window size changes (table mode)
        if self._stack.currentIndex() == 0:  # table page
            self._apply_sizes_from_window()

    def _apply_sizes_from_window(self) -> None:
        header_h = self._table.horizontalHeader().height()
        h = self.height()
        effective = max(100, h - header_h - 60)
        per_row = int(effective / 3)
        base_side = max(60, per_row - 2)  # minimal margin inside the row
        self._table.setBaseThumbSide(base_side)

    # ----- Table interactions -----

    def _on_table_double_clicked(self, idx: QtCore.QModelIndex) -> None:
        row = idx.row()
        if 0 <= row < len(self._entries):
            self._current_index = row
            # Find first available image type for this entry
            ent = self._entries[row]
            if ent.diff_path:
                self._current_kind = 0
            elif ent.current_path:
                self._current_kind = 1
            elif ent.old_path:
                self._current_kind = 2
            elif ent.new_path:
                self._current_kind = 3
            self._show_viewer()

    # ----- Viewer mode -----

    def _show_viewer(self) -> None:
        self._show_current_in_viewer()
        self._stack.setCurrentIndex(1)

    def _back_to_table(self) -> None:
        self._stack.setCurrentIndex(0)
        # Ensure selected row is visible
        if 0 <= self._current_index < self._table.rowCount():
            self._table.selectRow(self._current_index)
            self._table.scrollToItem(self._table.verticalHeaderItem(self._current_index),
                                     QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)

    def _show_current_in_viewer(self) -> None:
        if not (0 <= self._current_index < len(self._entries)):
            self._viewer.clearImage()
            return
        ent = self._entries[self._current_index]

        # Get the path for the current kind
        if self._current_kind == 0:
            path = ent.diff_path
        elif self._current_kind == 1:
            path = ent.current_path
        elif self._current_kind == 2:
            path = ent.old_path
        else:
            path = ent.new_path

        if path:
            self._viewer.setImagePath(path)
            # Also update window title for context
            self.setWindowTitle(f"Image Diff Browser — [{ent.name}]  ({self._kinds[self._current_kind].upper()})")
        else:
            self._viewer.clearImage()
            self.setWindowTitle(f"Image Diff Browser — [{ent.name}]  (NO IMAGE)")

    def _on_viewer_wheel_navigation(self, direction: int) -> None:
        """Handle mouse wheel navigation in viewer mode."""
        if not self._entries:
            return

        if abs(direction) >= 100:
            # Shift + wheel: cycle between stem/new/old image types (like left/right arrows)
            ent = self._entries[self._current_index]
            delta = +1 if direction > 0 else -1

            # Skip missing files when navigating
            attempts = 0
            while attempts < 4:  # Maximum 4 attempts to avoid infinite loop
                self._current_kind = (self._current_kind + delta) % 4

                # Check if current kind has a file
                if self._current_kind == 0 and ent.diff_path:
                    break
                elif self._current_kind == 1 and ent.current_path:
                    break
                elif self._current_kind == 2 and ent.old_path:
                    break
                elif self._current_kind == 3 and ent.new_path:
                    break

                attempts += 1

            self._show_current_in_viewer()
        else:
            # Regular wheel: navigate between entries (like up/down arrows)
            self._current_index = (self._current_index + direction) % len(self._entries)

            # Find the first available image type for the new entry
            ent = self._entries[self._current_index]
            if ent.diff_path:
                self._current_kind = 0
            elif ent.current_path:
                self._current_kind = 1
            elif ent.old_path:
                self._current_kind = 2
            elif ent.new_path:
                self._current_kind = 3

            self._show_current_in_viewer()

    # ----- Key handling -----

    def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
        # Global shortcuts that depend on the page
        if self._stack.currentIndex() == 1:
            # Viewer page
            if e.key() == QtCore.Qt.Key.Key_Escape:
                self._back_to_table()
                return
            if e.key() in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right):
                if not self._entries:
                    return
                ent = self._entries[self._current_index]
                delta = -1 if e.key() == QtCore.Qt.Key.Key_Left else +1

                # Skip missing files when navigating
                attempts = 0
                while attempts < 4:  # Maximum 4 attempts to avoid infinite loop
                    self._current_kind = (self._current_kind + delta) % 4

                    # Check if current kind has a file
                    if self._current_kind == 0 and ent.diff_path:
                        break
                    elif self._current_kind == 1 and ent.current_path:
                        break
                    elif self._current_kind == 2 and ent.old_path:
                        break
                    elif self._current_kind == 3 and ent.new_path:
                        break

                    attempts += 1

                self._show_current_in_viewer()
                return
            if e.key() in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up):
                if not self._entries:
                    return
                delta = +1 if e.key() == QtCore.Qt.Key.Key_Down else -1
                self._current_index = (self._current_index + delta) % len(self._entries)

                # Find the first available image type for the new entry
                ent = self._entries[self._current_index]
                if ent.diff_path:
                    self._current_kind = 0
                elif ent.current_path:
                    self._current_kind = 1
                elif ent.old_path:
                    self._current_kind = 2
                elif ent.new_path:
                    self._current_kind = 3

                self._show_current_in_viewer()
                return
        else:
            # Table page
            if e.key() == QtCore.Qt.Key.Key_Escape:
                self.close()
                return
            if e.key() == QtCore.Qt.Key.Key_F5:
                self.refresh()
                return
            if e.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                # Enter key should act like double-click on selected row
                current_row = self._table.currentRow()
                if 0 <= current_row < len(self._entries):
                    self._current_index = current_row
                    # Find first available image type for this entry
                    ent = self._entries[current_row]
                    if ent.diff_path:
                        self._current_kind = 0
                    elif ent.current_path:
                        self._current_kind = 1
                    elif ent.old_path:
                        self._current_kind = 2
                    elif ent.new_path:
                        self._current_kind = 3
                    self._show_viewer()
                return
            if e.key() == QtCore.Qt.Key.Key_Delete:
                # Delete key should remove OLD/NEW/DIFF files and remove the line
                current_row = self._table.currentRow()
                if 0 <= current_row < len(self._entries):
                    ent = self._entries[current_row]

                    # Delete the files (OLD, NEW, DIFF - not CURRENT)
                    files_deleted = []
                    if ent.old_path and os.path.exists(ent.old_path):
                        try:
                            os.remove(ent.old_path)
                            files_deleted.append("OLD")
                        except Exception as ex:
                            print(f"Error deleting {ent.old_path}: {ex}", file=sys.stderr)

                    if ent.new_path and os.path.exists(ent.new_path):
                        try:
                            os.remove(ent.new_path)
                            files_deleted.append("NEW")
                        except Exception as ex:
                            print(f"Error deleting {ent.new_path}: {ex}", file=sys.stderr)

                    if ent.diff_path and os.path.exists(ent.diff_path):
                        try:
                            os.remove(ent.diff_path)
                            files_deleted.append("DIFF")
                        except Exception as ex:
                            print(f"Error deleting {ent.diff_path}: {ex}", file=sys.stderr)

                    # Remove entry from list and table
                    if files_deleted:
                        self._entries.pop(current_row)
                        self._table.removeRow(current_row)

                        # Select next row if available, or previous if at end
                        if self._entries:
                            new_row = min(current_row, len(self._entries) - 1)
                            self._table.selectRow(new_row)

                return
        super().keyPressEvent(e)


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Browse image differences for (<foo>.png, <foo>-new.png, <foo>-diff.png) triplets.")
    p.add_argument("folder", help="Root folder to scan recursively")
    return p.parse_args(argv)


def main(folder: str | None = None) -> int:
    """Launch the diffcharts GUI.

    Parameters:
        folder: Root folder to scan recursively. If ``None``, the folder is
            taken from ``sys.argv``.

    Returns:
        Process exit code from the Qt event loop.
    """
    if folder is None:
        args = _parse_args(sys.argv[1:])
        folder = args.folder

    root = os.path.abspath(folder)
    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        return 2

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Image Diff Browser")

    win = MainWindow(root)
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
