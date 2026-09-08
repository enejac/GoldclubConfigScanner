"""Simple home: Create client update · Apply update · Tune live cabinet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config_scanner.app_brand import program_title
from config_scanner.pack_detect import PackKind, auto_detect_beside_exe, detect_update_path
from gui.companion_pack_panel import CompanionApplyPanel
from gui.country_pack_panel import CountryWizardPanel
from gui.embedded_updates_panel import OfficialUpdateCombo, materialize_entry
from gui.jurisdiction_wizard import JurisdictionWizard
from gui.live_push_panel import LivePushPanel
from gui.slot_setup_panel import SlotApplyPanel


_SHARE_B2U = r"\\10.0.0.249\WinSystems_SLOT\_B2U"
_SHARE_GS201 = r"\\10.0.0.249\WinSystems_SLOT\GameStar 2.0.1\Country Selectors"


class _PreflightEmitter(QObject):
    finished = Signal(object)


class _MathPreflightRunnable(QRunnable):
    def __init__(self, target: str, emitter: _PreflightEmitter) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._target = target
        self._emitter = emitter

    def run(self) -> None:
        try:
            from config_scanner.denom_compat import cabinet_link2win_preflight

            self._emitter.finished.emit(cabinet_link2win_preflight(self._target))
        except Exception as exc:  # noqa: BLE001
            self._emitter.finished.emit(exc)


class RoleHome(QWidget):
    """First screen: Create / Apply / Tune live / Advanced."""

    create_requested = Signal()
    restore_requested = Signal()
    push_requested = Signal()
    advanced_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(14)

        title = QLabel(program_title())
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        root.addWidget(title)

        blurb = QLabel(
            "• Create — pick a market, review the official Country Selector, export a "
            "client update or a full CS .b2u from a tuned live cabinet.\n"
            "• Apply — open that update on the EGM (country / leaf / machine number).\n"
            "• Tune — change SAS, bills, tickets, limits, and denoms on a live cabinet, "
            "then export a full Country Selector if needed."
        )
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        create_btn = QPushButton("1. Create client update")
        create_btn.setObjectName("primary")
        create_btn.setMinimumHeight(48)
        create_btn.setToolTip(
            "Pick a market and Country Selector pack, compare settings, then export a "
            "client update or a full official-style CS .b2u from a tuned live cabinet."
        )
        create_btn.clicked.connect(self.create_requested.emit)
        root.addWidget(create_btn)

        restore_btn = QPushButton("2. Apply update on cabinet")
        restore_btn.setObjectName("primary")
        restore_btn.setMinimumHeight(48)
        restore_btn.setToolTip(
            "Open a GameStar Country Selector .b2u or unpacked folder.\n"
            "GameStar+22/+30 zips, JinLong, and .mrimg disk images are not CS overlays."
        )
        restore_btn.clicked.connect(self.restore_requested.emit)
        root.addWidget(restore_btn)

        push_btn = QPushButton("3. Tune live cabinet")
        push_btn.setObjectName("primary")
        push_btn.setMinimumHeight(48)
        push_btn.setToolTip(
            "Load the cabinet, edit SAS / currency / denoms, Apply. "
            "Stops the game, writes files, starts the stack again."
        )
        push_btn.clicked.connect(self.push_requested.emit)
        root.addWidget(push_btn)

        adv = QPushButton("Advanced tools…")
        adv.setFlat(True)
        adv.setCursor(Qt.CursorShape.PointingHandCursor)
        adv.setStyleSheet("color: #8ab4f8; text-align: left; padding: 4px 0;")
        adv.setToolTip("Snapshots, pack authoring, companions, ship")
        adv.clicked.connect(self.advanced_requested.emit)
        root.addWidget(adv)

        self._preflight = QLabel("")
        self._preflight.setWordWrap(True)
        self._preflight.setObjectName("mathPreflight")
        self._preflight.setStyleSheet("color: #999;")
        root.addWidget(self._preflight)

        root.addStretch(1)

    def set_math_preflight(self, report) -> None:
        """Show the startup Link2Win math check (read-only)."""
        from config_scanner.denom_compat import MathPreflightReport

        if isinstance(report, Exception):
            self._preflight.setStyleSheet("color: #999;")
            self._preflight.setText(f"Math preflight skipped: {report}")
            return
        if not isinstance(report, MathPreflightReport):
            self._preflight.clear()
            return
        if not report.reachable:
            self._preflight.setStyleSheet("color: #999;")
            self._preflight.setText(
                report.messages[0] if report.messages else ""
            )
            return
        if report.ok:
            extra = ""
            if not report.decryptor:
                extra = (
                    " Encryptor.exe (tools) is for JSON math; "
                    "preflight uses pack fingerprints so live math stays untouched."
                )
            elif report.cabinet_denoms:
                shown = ", ".join(f"{d}c" for d in report.cabinet_denoms)
                extra = f" Link2Win math covers {shown}."
            self._preflight.setStyleSheet("color: #6a9;")
            self._preflight.setText(("Math preflight OK." + extra).strip())
            return
        self._preflight.setStyleSheet("color: #c66;")
        detail = " ".join(report.messages[:2])
        self._preflight.setText(
            "Link2Win math does not match the live denom. "
            + detail
            + " Math files are not written on startup — use Tune live to copy a matching pack."
        )


class RestoreHubPanel(QWidget):
    """Client: open an update (built-in, .b2u, or folder), auto-detect type, apply."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stack = QStackedWidget(self)
        self._picker = QWidget()
        self._build_picker()
        self._stack.addWidget(self._picker)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        auto = auto_detect_beside_exe()
        if auto is not None and auto.kind != PackKind.UNKNOWN:
            self._open_detected(auto.root, auto)

    def _build_picker(self) -> None:
        root = QVBoxLayout(self._picker)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        back = QPushButton("← Home")
        back.setToolTip("Return to the Config Scanner home screen.")
        back.clicked.connect(self.back_requested.emit)
        head.addWidget(back)
        title = QLabel("Apply update on cabinet")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        title.setToolTip(
            "Open a Country Selector or ConfigScanner update and apply it on this EGM."
        )
        head.addWidget(title)
        head.addStretch(1)
        root.addLayout(head)

        help_lbl = QLabel(
            "Pick a built-in Country Selector, or open a .b2u / unpacked folder. "
            "Then choose country / screens / mode, enter the machine number, and Apply."
        )
        help_lbl.setWordWrap(True)
        root.addWidget(help_lbl)

        official_lbl = QLabel("Official update (offline)")
        official_lbl.setStyleSheet("font-weight: 600;")
        official_lbl.setToolTip(
            "Built-in GameStar packs shipped inside Config Scanner (work without the lab share)."
        )
        root.addWidget(official_lbl)

        self._official = OfficialUpdateCombo(apply_label="Apply")
        self._official.setToolTip(
            "Select a built-in Country Selector, then Apply to open the field wizard."
        )
        self._official.apply_requested.connect(self._restore_embedded)
        root.addWidget(self._official)

        path_lbl = QLabel("Or open a file / folder")
        path_lbl.setStyleSheet("font-weight: 600;")
        root.addWidget(path_lbl)

        row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setPlaceholderText(
            r"\\10.0.0.249\...\CS-Gamestar-TT-00.b2u  or  unpacked ConfigScanner_Country_*"
        )
        self._path.setToolTip(
            "Path to a .b2u, GameStar CountrySelectorTool folder, or ConfigScanner "
            "client/EGM package."
        )
        row.addWidget(self._path, stretch=1)
        browse = QPushButton("Browse…")
        browse.setToolTip("Pick a .b2u file or an unpacked update folder.")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        share = QPushButton("Browse lab share…")
        share.setToolTip(f"Open {_SHARE_B2U}")
        share.clicked.connect(self._browse_share)
        row.addWidget(share)
        open_btn = QPushButton("Open")
        open_btn.setObjectName("primary")
        open_btn.setToolTip("Detect the update type and open the matching apply screen.")
        open_btn.clicked.connect(self._open_path)
        row.addWidget(open_btn)
        root.addLayout(row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        root.addStretch(1)

    def open_update_path(self, path: str | Path) -> None:
        """Jump to Apply and open a folder or ``.b2u`` path."""
        self._path.setText(str(path))
        self._open_update(Path(path))

    def _restore_embedded(self, entry) -> None:
        try:
            tool = materialize_entry(entry)
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Built-in restore", str(exc))
            return
        from config_scanner.pack_detect import DetectedPack

        detected = DetectedPack(PackKind.COUNTRY, tool, "embedded")
        self._open_detected(tool, detected)

    def _browse(self) -> None:
        start = self._path.text().strip() or _SHARE_GS201
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select update (.b2u) or Cancel and pick folder",
            start,
            "BiOS updates (*.b2u);;All files (*.*)",
        )
        if path:
            self._path.setText(path)
            return
        folder = QFileDialog.getExistingDirectory(self, "Select unpacked update folder", start)
        if folder:
            self._path.setText(folder)

    def _browse_share(self) -> None:
        start = _SHARE_B2U
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Lab share update (.b2u)",
            start,
            "BiOS updates (*.b2u);;All files (*.*)",
        )
        if path:
            self._path.setText(path)
            return
        folder = QFileDialog.getExistingDirectory(self, "Lab share folder", start)
        if folder:
            self._path.setText(folder)

    def _open_path(self) -> None:
        raw = self._path.text().strip()
        if not raw:
            QMessageBox.warning(self, "Open", "Choose an update path (.b2u or folder).")
            return
        self._open_update(Path(raw))

    def _open_update(self, path: Path) -> None:
        try:
            if path.suffix.casefold() == ".b2u":
                self._status.setText(f"Decrypting {path.name}…")
                QApplication.processEvents()
            detected = detect_update_path(path)
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            self._status.setText(str(exc))
            QMessageBox.warning(
                self,
                "Open",
                f"Could not open update:\n{exc}\n\n"
                "Raw .b2u files need BiOS2_PackageGenerator.exe in tools\\ "
                "(place it beside ConfigScanner or under D:\\tools).",
            )
            return
        self._open_detected(detected.root, detected)

    def _open_detected(self, path: Path, detected=None) -> None:
        if detected is None:
            detected = detect_update_path(path)
        if detected.kind == PackKind.UNKNOWN:
            self._status.setText(f"Could not recognize: {path}")
            QMessageBox.warning(
                self,
                "Open",
                "Not a Country / EGM / Companion pack.\n"
                "Need CountrySelectorTool\\data, recipe.json, or companion.json.",
            )
            return
        while self._stack.count() > 1:
            w = self._stack.widget(1)
            self._stack.removeWidget(w)
            w.deleteLater()

        if detected.kind == PackKind.COUNTRY:
            panel = CountryWizardPanel(detected.root, self)
        elif detected.kind == PackKind.EGM_RECIPE:
            panel = SlotApplyPanel(detected.root, self)
        else:
            panel = CompanionApplyPanel(detected.root, self)

        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        back = QPushButton("← Choose another update")
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        top.addWidget(back)
        kind_lbl = QLabel(f"Type: {detected.kind.value} — {detected.detail}")
        top.addWidget(kind_lbl)
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(panel, stretch=1)
        self._stack.addWidget(wrap)
        self._stack.setCurrentWidget(wrap)
        self._status.setText(f"Opened {detected.kind.value}: {detected.root}")


class SimpleShell(QWidget):
    """Home ↔ Create wizard ↔ Apply ↔ Live push; optional Advanced."""

    advanced_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stack = QStackedWidget(self)
        self._home = RoleHome()
        self._wizard = JurisdictionWizard()
        self._restore = RestoreHubPanel()
        # Create Live Push lazily — constructing it at startup auto-probes G:/SMB
        # and freezes the home screen on rapid Tune clicks.
        self._push: LivePushPanel | None = None
        self._nav_guard = False
        self._stack.addWidget(self._home)
        self._stack.addWidget(self._wizard)
        self._stack.addWidget(self._restore)

        self._home.create_requested.connect(self._show_create)
        self._home.restore_requested.connect(self._show_restore)
        self._home.push_requested.connect(self._show_push)
        self._home.advanced_requested.connect(self.advanced_requested.emit)
        self._wizard.back_requested.connect(self._show_home)
        self._restore.back_requested.connect(self._show_home)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

        self._preflight_emitter = _PreflightEmitter()
        self._preflight_emitter.finished.connect(self._home.set_math_preflight)
        QTimer.singleShot(200, self._start_math_preflight)

    def _start_math_preflight(self) -> None:
        from config_scanner.live_push import default_live_cabinet_target

        worker = _MathPreflightRunnable(
            default_live_cabinet_target(), self._preflight_emitter
        )
        QThreadPool.globalInstance().start(worker)

    def _show_home(self) -> None:
        self._stack.setCurrentWidget(self._home)

    def _show_create(self) -> None:
        if self._nav_guard:
            return
        self._stack.setCurrentWidget(self._wizard)

    def _show_restore(self) -> None:
        if self._nav_guard:
            return
        self._stack.setCurrentWidget(self._restore)

    def _show_push(self) -> None:
        """Open Tune live cabinet once; ignore rapid repeat clicks while opening."""
        if self._nav_guard:
            return
        self._nav_guard = True
        try:
            if self._push is None:
                self._push = LivePushPanel(autoload=False)
                self._push.back_requested.connect(self._show_home)
                self._stack.addWidget(self._push)
            self._stack.setCurrentWidget(self._push)
            self._push.ensure_started()
        finally:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(400, self._clear_nav_guard)

    def _clear_nav_guard(self) -> None:
        self._nav_guard = False

    def show_restore(self) -> None:
        self._show_restore()

    def open_restore(self, path: str | Path) -> None:
        """Home → Apply, then open a ``.b2u`` or folder."""
        self.show_restore()
        self._restore.open_update_path(path)

    def show_create(self) -> None:
        self._show_create()
