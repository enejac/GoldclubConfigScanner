"""Standalone window for the Config Scanner."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.single_instance import (
    show_already_running_warning,
    try_acquire_config_scanner_lock,
)

from gui.app_branding import apply_window_branding, status_bar_brand_pixmap
from gui.app_logging import get_logger
from gui.companion_pack_panel import CompanionApplyPanel, CompanionPackAuthorPanel
from gui.config_scanner_tab import ConfigScannerTabWidget
from gui.country_pack_panel import CountryWizardPanel
from gui.ship_panel import ShipPanel
from gui.simple_home import SimpleShell
from gui.slot_setup_panel import SlotApplyPanel, SlotSetupPanel
from gui.theme_utils import apply_theme
from config_manager import SettingsManager
from config_scanner.app_brand import program_title
from config_scanner.ui_screenshot import save_widget_screenshot

logger = get_logger(__name__)


class ConfigScannerWindow(QMainWindow):
    """Simple Create/Restore home; typed packs open apply-only; Advanced has full tabs."""

    def __init__(
        self,
        parent=None,
        *,
        apply_pack: Path | None = None,
        country_pack: Path | None = None,
        companion_pack: Path | None = None,
        restore_b2u: Path | None = None,
        snapshots: bool = False,
    ) -> None:
        super().__init__(parent)
        logger.info(
            "ConfigScannerWindow.__init__ apply_pack=%s country_pack=%s companion_pack=%s restore_b2u=%s snapshots=%s",
            apply_pack,
            country_pack,
            companion_pack,
            restore_b2u,
            snapshots,
        )
        self._apply_pack = Path(apply_pack) if apply_pack else None
        self._country_pack = Path(country_pack) if country_pack else None
        self._companion_pack = Path(companion_pack) if companion_pack else None
        self._restore_b2u = Path(restore_b2u) if restore_b2u else None
        self._snapshots_mode = bool(snapshots)
        self._simple: SimpleShell | None = None
        self._advanced: QWidget | None = None
        self._applied_show_mode = False

        if self._companion_pack is not None:
            title = program_title("Restore companion")
        elif self._country_pack is not None:
            title = program_title("Restore Country Selector")
        elif self._restore_b2u is not None:
            title = program_title("Restore update")
        elif self._apply_pack is not None:
            title = program_title("Restore settings")
        elif self._snapshots_mode:
            title = program_title("Snapshots")
        else:
            title = program_title()
        self.setWindowTitle(title)
        self.setMinimumSize(900, 600)
        self.resize(1180, 860)
        apply_window_branding(self)

        if self._companion_pack is not None:
            self._scanner = None
            self.setCentralWidget(CompanionApplyPanel(self._companion_pack, self))
        elif self._country_pack is not None:
            self._scanner = None
            self.setCentralWidget(CountryWizardPanel(self._country_pack, self))
        elif self._apply_pack is not None:
            self._scanner = None
            self.setCentralWidget(SlotApplyPanel(self._apply_pack, self))
        elif self._snapshots_mode:
            self._scanner = ConfigScannerTabWidget(self)
            self.setCentralWidget(self._scanner)
            self._root_stack = None
        else:
            self._root_stack = QStackedWidget(self)
            self._simple = SimpleShell(self)
            self._simple.advanced_requested.connect(self._show_advanced)
            self._root_stack.addWidget(self._simple)
            self._scanner = None
            self.setCentralWidget(self._root_stack)
            if self._restore_b2u is not None:
                QTimer.singleShot(
                    0,
                    lambda: self._simple.open_restore(self._restore_b2u),
                )

        sb = QStatusBar(self)
        self.setStatusBar(sb)

        brand = QLabel()
        brand.setPixmap(status_bar_brand_pixmap(size=18))
        sb.addWidget(brand)
        sb.addWidget(QLabel(program_title()))
        self._status = QLabel("Ready")
        sb.addWidget(self._status, stretch=1)
        self._screenshot_btn = QPushButton("Screenshot")
        self._screenshot_btn.setToolTip(
            "Save a PNG of this window next to ConfigScanner.exe "
            "(Ctrl+Shift+S). Does not capture the desktop."
        )
        self._screenshot_btn.clicked.connect(self._screenshot_ui)
        sb.addPermanentWidget(self._screenshot_btn)
        self._screenshot_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._screenshot_shortcut.activated.connect(self._screenshot_ui)

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, SettingsManager.get_theme())
        self._cs_show_mode = SettingsManager.restore_config_scanner_window_geometry(self)
        logger.info(
            "ConfigScannerWindow.__init__ done show_mode=%s", self._cs_show_mode
        )

    def _show_advanced(self) -> None:
        if self._advanced is None:
            wrap = QWidget()
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            top = QPushButton("← Back to home")
            top.clicked.connect(lambda: self._root_stack.setCurrentWidget(self._simple))
            lay.addWidget(top)
            hint = QLabel(
                "Snapshots, EGM pack authoring, companions, ship "
                "(country CS export is on home → Create client update)"
            )
            hint.setStyleSheet("color: #888; padding-left: 4px;")
            lay.addWidget(hint)
            tabs = QTabWidget(wrap)
            try:
                self._scanner = ConfigScannerTabWidget(self)
            except Exception:
                logger.exception("ConfigScannerTabWidget failed during init")
                raise
            tabs.addTab(self._scanner, "Snapshots")
            tabs.addTab(SlotSetupPanel(self), "EGM setup")
            tabs.addTab(CompanionPackAuthorPanel(self), "Companion packs")
            tabs.addTab(ShipPanel(self), "Ship")
            lay.addWidget(tabs, stretch=1)
            self._advanced = wrap
            self._root_stack.addWidget(self._advanced)
        self._root_stack.setCurrentWidget(self._advanced)

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        logger.info("ConfigScannerWindow showEvent visible=%s", self.isVisible())
        if self._applied_show_mode:
            return
        self._applied_show_mode = True
        if self._cs_show_mode == "fullscreen":
            self.showFullScreen()
        elif self._cs_show_mode == "maximized":
            self.showMaximized()
        if self._should_open_live_push_on_launch():
            QTimer.singleShot(0, self._open_live_push)

    def _should_open_live_push_on_launch(self) -> bool:
        return (
            self._simple is not None
            and self._restore_b2u is None
            and not self._snapshots_mode
            and self._apply_pack is None
            and self._country_pack is None
            and self._companion_pack is None
        )

    def _open_live_push(self) -> None:
        if self._simple is None:
            return
        self._simple.show_push()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        SettingsManager.save_config_scanner_window_geometry(self)
        super().closeEvent(event)

    def show_status(self, message: str) -> None:
        self._status.setText(message)

    def _screenshot_ui(self) -> None:
        try:
            path = save_widget_screenshot(self)
        except OSError as exc:
            QMessageBox.warning(self, "Screenshot", str(exc))
            return
        self.show_status(f"Saved {path.name} next to the exe")


def run_config_scanner_app(
    *,
    apply_pack: str | Path | None = None,
    country_pack: str | Path | None = None,
    companion_pack: str | Path | None = None,
    restore_b2u: str | Path | None = None,
    snapshots: bool = False,
) -> int:
    """Launch only the Config Scanner window (no log triage UI)."""
    from config_scanner.runtime_bootstrap import bootstrap_frozen_app

    log_path = bootstrap_frozen_app()
    logger.info(
        "run_config_scanner_app log_file=%s apply=%s country=%s companion=%s restore_b2u=%s snapshots=%s",
        log_path,
        apply_pack,
        country_pack,
        companion_pack,
        restore_b2u,
        snapshots,
    )
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(program_title())
    app.setApplicationDisplayName(program_title())
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")

    instance_lock = try_acquire_config_scanner_lock()
    if instance_lock is None:
        logger.warning("second Config Scanner instance refused — already running")
        show_already_running_warning()
        return 1
    app._config_scanner_instance_lock = instance_lock  # type: ignore[attr-defined]

    from gui.app_branding import apply_app_icon
    from gui.win_title_bar import install_title_bar_theme_filter, schedule_title_bar_theme

    apply_app_icon(app)
    install_title_bar_theme_filter(app, SettingsManager.get_theme)
    apply_theme(app, SettingsManager.get_theme())

    win = ConfigScannerWindow(
        apply_pack=Path(apply_pack) if apply_pack else None,
        country_pack=Path(country_pack) if country_pack else None,
        companion_pack=Path(companion_pack) if companion_pack else None,
        restore_b2u=Path(restore_b2u) if restore_b2u else None,
        snapshots=snapshots,
    )
    win.show()
    schedule_title_bar_theme(win, SettingsManager.get_theme())
    return app.exec()
