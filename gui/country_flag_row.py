"""Live Push country-flag picker — thumbnails, because filenames lie."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config_scanner.language_flags import (
    FlagAsset,
    LanguageFlagSetting,
    assignment_for_asset,
    decode_flag_preview,
    discover_flag_assets,
    resolve_theme_texture,
)

_ICON = QSize(40, 36)


def flag_pixmap(path: Path | None, size: QSize = _ICON) -> QPixmap:
    """PNG via Qt; DDS (BC7) via the scanner decoder."""
    if path is None or not path.is_file():
        return QPixmap()
    if path.suffix.casefold() == ".png":
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    preview = decode_flag_preview(path)
    if preview is None:
        return QPixmap()
    image = QImage(
        preview.rgba,
        preview.width,
        preview.height,
        preview.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    # Copy so the preview buffer can be freed.
    pix = QPixmap.fromImage(image.copy())
    if pix.isNull():
        return pix
    return pix.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class CountryFlagsEditor(QWidget):
    """One icon combo per wired language button (Spanish / English / …)."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("csCountryFlag")
        self._goldclub: Path | None = None
        self._wired: list[LanguageFlagSetting] = []
        self._assets: list[FlagAsset] = []
        self._combos: list[QComboBox] = []
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(4)
        self._empty = QLabel("No console flag on this cabinet")
        self._empty.setObjectName("csCountryFlagEmpty")
        self._empty.setStyleSheet("color: #888;")
        self._root.addWidget(self._empty)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

    def current_flags(self) -> list[LanguageFlagSetting]:
        if not self._combos:
            return list(self._wired)
        out: list[LanguageFlagSetting] = []
        for wired, combo in zip(self._wired, self._combos, strict=False):
            asset = combo.currentData()
            if isinstance(asset, FlagAsset):
                out.append(assignment_for_asset(wired, asset))
            else:
                out.append(wired)
        return out

    def load(
        self,
        goldclub: Path | None,
        flags: list[LanguageFlagSetting] | None,
    ) -> None:
        self._goldclub = goldclub
        self._wired = list(flags or [])
        self._assets = (
            discover_flag_assets(goldclub, wired=self._wired)
            if goldclub is not None
            else []
        )
        self._rebuild()

    def setStyleSheet(self, sheet: str) -> None:  # noqa: N802
        super().setStyleSheet(sheet)
        for combo in self._combos:
            combo.setStyleSheet(sheet)

    def _rebuild(self) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._empty:
                widget.deleteLater()
        self._combos = []
        if not self._wired:
            self._empty.setVisible(True)
            self._root.addWidget(self._empty)
            return
        self._empty.setVisible(False)
        for flag in self._wired:
            row = QWidget(self)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            caption = QLabel(flag.state_name)
            caption.setMinimumWidth(64)
            combo = QComboBox()
            combo.setIconSize(_ICON)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            combo.setToolTip(
                "Filename is a language token. Trust the picture — "
                "flag_spanish is often Puerto Rico, not Spain."
            )
            self._fill_combo(combo, flag)
            combo.currentIndexChanged.connect(self.changed)
            layout.addWidget(caption)
            layout.addWidget(combo, 1)
            self._root.addWidget(row)
            self._combos.append(combo)

    def _fill_combo(self, combo: QComboBox, flag: LanguageFlagSetting) -> None:
        current_name = flag.texture_name().casefold()
        assets = list(self._assets)
        if current_name and not any(
            a.name.casefold() == current_name for a in assets
        ):
            resolved = (
                resolve_theme_texture(self._goldclub, flag.texture_path)
                if self._goldclub is not None
                else None
            )
            assets.insert(
                0,
                FlagAsset(
                    name=flag.texture_name(),
                    relative_path=flag.texture_path,
                    absolute_path=resolved or Path(flag.texture_path),
                    pressed_relative_path=flag.pressed_texture_path,
                ),
            )
        chosen = 0
        for i, asset in enumerate(assets):
            pix = flag_pixmap(asset.absolute_path)
            icon = QIcon(pix) if not pix.isNull() else QIcon()
            combo.addItem(icon, asset.name, asset)
            if asset.name.casefold() == current_name:
                chosen = i
        if combo.count():
            combo.setCurrentIndex(chosen)
