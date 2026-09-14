"""Console country-flag textures (jurisdiction_config Languages).

OneHand's language button is filled from ``LanguageButtonStateSetting``
rows. Filenames are language tokens (``flag_spanish.dds``) and often do
not match the country in the bitmap — Puerto Rico packs commonly wire
Spanish to a PR flag. Live Push shows the pixels, not just the name.
"""

from __future__ import annotations

import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

COUNTRY_FLAG_LABEL = "Country flag"

_JURISDICTION_REL = Path("slot") / "themes" / "jurisdiction_config.xml"
_DEFAULT_FLAG_DIR = Path("data") / "GameStarColors" / "1080p" / "Red" / "console" / "languageBtn"
_IMAGE_SUFFIXES = frozenset({".png", ".dds"})
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _qname(parent: ET.Element, name: str) -> str:
    if "}" in parent.tag:
        return parent.tag.split("}", 1)[0] + "}" + name
    return name


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    for el in parent:
        if _local(el.tag) == name:
            return el
    return None


def _text(parent: ET.Element, name: str) -> str:
    el = _child(parent, name)
    if el is None:
        return ""
    return (el.text or "").strip()


@dataclass(frozen=True)
class LanguageFlagSetting:
    """One console language-button row in jurisdiction_config."""

    state_name: str
    texture_path: str
    pressed_texture_path: str = ""

    def texture_name(self) -> str:
        return Path(self.texture_path.replace("\\", "/")).name


@dataclass(frozen=True)
class FlagAsset:
    """A non-pressed flag image next to the wired languageBtn folder."""

    name: str
    relative_path: str
    absolute_path: Path
    pressed_relative_path: str = ""
    pressed_absolute_path: Path | None = None


@dataclass(frozen=True)
class FlagPreview:
    width: int
    height: int
    rgba: bytes


def flags_snapshot(flags: Sequence[LanguageFlagSetting] | None) -> str:
    """Operator-facing Live Push value (basename only — names can lie)."""
    rows = [f for f in (flags or ()) if f.state_name and f.texture_path]
    if not rows:
        return "—"
    return "; ".join(f"{f.state_name}={f.texture_name()}" for f in rows)


def language_flags_from_raw(raw: object) -> list[LanguageFlagSetting]:
    out: list[LanguageFlagSetting] = []
    if not raw:
        return out
    for item in raw:
        if isinstance(item, LanguageFlagSetting):
            if item.state_name and item.texture_path:
                out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("state_name") or "").strip()
        tex = str(item.get("texture_path") or "").strip()
        if not name or not tex:
            continue
        out.append(
            LanguageFlagSetting(
                state_name=name,
                texture_path=tex,
                pressed_texture_path=str(item.get("pressed_texture_path") or "").strip(),
            )
        )
    return out


def language_flags_from_root(root: ET.Element) -> list[LanguageFlagSetting]:
    langs = None
    for el in root.iter():
        if _local(el.tag) == "Languages":
            langs = el
            break
    if langs is None:
        return []
    out: list[LanguageFlagSetting] = []
    for child in langs:
        if _local(child.tag) != "LanguageButtonStateSetting":
            continue
        name = _text(child, "StateName")
        tex = _text(child, "TexturePath")
        if not name or not tex:
            continue
        out.append(
            LanguageFlagSetting(
                state_name=name,
                texture_path=tex,
                pressed_texture_path=_text(child, "PressedTexturePath"),
            )
        )
    return out


def jurisdiction_config_path(goldclub: Path) -> Path:
    return Path(goldclub) / _JURISDICTION_REL


def read_language_flags(goldclub: Path) -> list[LanguageFlagSetting]:
    path = jurisdiction_config_path(goldclub)
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    return language_flags_from_root(root)


def probe_language_flags(root: ET.Element) -> tuple[bool, list[str] | None, str]:
    flags = language_flags_from_root(root)
    if not flags:
        return False, None, "no Languages"
    return True, [f"{f.state_name}={f.texture_name()}" for f in flags], ""


def apply_language_flags(root: ET.Element, flags: Sequence[LanguageFlagSetting]) -> None:
    """Set TexturePath on existing language buttons. Empty *flags* is a no-op.

    Does not reorder ``<Languages>`` — Live Push Language already moves the
    initial entry first. Wiping the list would undo that and also drop
    extra pack states the picker did not show.
    """
    rows = [f for f in flags if f.state_name and f.texture_path]
    if not rows:
        return
    langs = _child(root, "Languages")
    if langs is None:
        for el in root.iter():
            if _local(el.tag) == "Languages":
                langs = el
                break
    if langs is None:
        langs = ET.SubElement(root, _qname(root, "Languages"))
    by_name: dict[str, ET.Element] = {}
    for child in langs:
        if _local(child.tag) != "LanguageButtonStateSetting":
            continue
        name = _text(child, "StateName").casefold()
        if name:
            by_name[name] = child
    for flag in rows:
        el = by_name.get(flag.state_name.casefold())
        if el is None:
            el = ET.SubElement(langs, _qname(langs, "LanguageButtonStateSetting"))
            ET.SubElement(el, _qname(el, "StateName")).text = flag.state_name
            by_name[flag.state_name.casefold()] = el
        tex = _child(el, "TexturePath")
        if tex is None:
            tex = ET.SubElement(el, _qname(el, "TexturePath"))
        tex.text = flag.texture_path
        if flag.pressed_texture_path:
            pressed = _child(el, "PressedTexturePath")
            if pressed is None:
                pressed = ET.SubElement(el, _qname(el, "PressedTexturePath"))
            pressed.text = flag.pressed_texture_path


def themes_root(goldclub: Path) -> Path:
    slot_themes = Path(goldclub) / "slot" / "themes"
    if slot_themes.is_dir():
        return slot_themes
    return Path(goldclub) / "themes"


def resolve_theme_texture(goldclub: Path, relative: str) -> Path | None:
    rel = (relative or "").replace("/", "\\").strip()
    if not rel:
        return None
    parts = Path(rel.replace("\\", "/"))
    for base in (themes_root(goldclub), Path(goldclub) / "slot" / "themes"):
        candidate = base / parts
        if candidate.is_file():
            return candidate
    return None


def pressed_name_for(name: str) -> str:
    path = Path(name)
    stem = path.stem
    if stem.casefold().endswith("_pressed"):
        return path.name
    return f"{stem}_pressed{path.suffix}"


def is_primary_flag_file(name: str) -> bool:
    path = Path(name)
    if path.suffix.casefold() not in _IMAGE_SUFFIXES:
        return False
    return not path.stem.casefold().endswith("_pressed")


def _relative_to_themes(goldclub: Path, path: Path) -> str:
    root = themes_root(goldclub)
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("/", "\\")
    except ValueError:
        return path.name


def _assets_in_folder(goldclub: Path, folder: Path) -> list[FlagAsset]:
    if not folder.is_dir():
        return []
    out: list[FlagAsset] = []
    try:
        names = [p.name for p in folder.iterdir() if p.is_file()]
    except OSError:
        return []
    by_fold = {n.casefold(): n for n in names}
    for name in sorted(names, key=str.casefold):
        if not is_primary_flag_file(name):
            continue
        pressed = by_fold.get(pressed_name_for(name).casefold())
        abs_path = folder / name
        pressed_abs = (folder / pressed) if pressed else None
        out.append(
            FlagAsset(
                name=name,
                relative_path=_relative_to_themes(goldclub, abs_path),
                absolute_path=abs_path,
                pressed_relative_path=(
                    _relative_to_themes(goldclub, pressed_abs) if pressed_abs else ""
                ),
                pressed_absolute_path=pressed_abs,
            )
        )
    return out


def discover_flag_assets(
    goldclub: Path,
    *,
    wired: Sequence[LanguageFlagSetting] | None = None,
) -> list[FlagAsset]:
    """Images sitting in the live languageBtn folder (plus any wired path)."""
    folders: list[Path] = []
    seen: set[str] = set()

    def _add(folder: Path) -> None:
        try:
            key = str(folder.resolve()).casefold()
        except OSError:
            key = str(folder).casefold()
        if key in seen:
            return
        seen.add(key)
        folders.append(folder)

    for flag in wired or ():
        resolved = resolve_theme_texture(goldclub, flag.texture_path)
        if resolved is not None:
            _add(resolved.parent)
    _add(themes_root(goldclub) / _DEFAULT_FLAG_DIR)

    found: list[FlagAsset] = []
    names: set[str] = set()
    for folder in folders:
        for asset in _assets_in_folder(goldclub, folder):
            key = asset.name.casefold()
            if key in names:
                continue
            names.add(key)
            found.append(asset)
    return found


def assignment_for_asset(
    current: LanguageFlagSetting, asset: FlagAsset
) -> LanguageFlagSetting:
    """Keep the language name; retarget both idle and pressed textures."""
    pressed = asset.pressed_relative_path or current.pressed_texture_path
    return LanguageFlagSetting(
        state_name=current.state_name,
        texture_path=asset.relative_path,
        pressed_texture_path=pressed,
    )


def decode_flag_preview(path: Path) -> FlagPreview | None:
    """RGBA preview for PNG or DDS (WIC on Windows, then a small fallback)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if data.startswith(_PNG_SIG):
        preview = _decode_png_rgba(data)
        if preview is not None:
            return preview
    if data[:4] == b"DDS ":
        preview = _decode_dds_simple(data)
        if preview is not None:
            return preview
        return _decode_dds_wic(path)
    if sys.platform == "win32":
        return _decode_dds_wic(path)
    return None


def _decode_png_rgba(data: bytes) -> FlagPreview | None:
    """8-bit RGB/RGBA, non-interlaced PNG (the languageBtn icons)."""
    if not data.startswith(_PNG_SIG):
        return None
    pos = 8
    width = height = 0
    bit_depth = 8
    color_type = 6
    idat = bytearray()
    end = len(data)
    while pos + 8 <= end:
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4 : pos + 8]
        start = pos + 8
        stop = start + length
        if stop + 4 > end:
            return None
        chunk = data[start:stop]
        pos = stop + 4
        if tag == b"IHDR" and length >= 13:
            width, height, bit_depth, color_type = struct.unpack_from(">IIBB", chunk, 0)
        elif tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
    if width <= 0 or height <= 0 or bit_depth != 8 or color_type not in (2, 6):
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    bpp = 3 if color_type == 2 else 4
    stride = 1 + width * bpp
    if len(raw) < stride * height:
        return None
    out = bytearray(width * height * 4)
    dest = 0
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        if row[0] != 0:
            return None
        pixels = row[1:]
        for x in range(width):
            src = x * bpp
            out[dest] = pixels[src]
            out[dest + 1] = pixels[src + 1]
            out[dest + 2] = pixels[src + 2]
            out[dest + 3] = 255 if bpp == 3 else pixels[src + 3]
            dest += 4
    return FlagPreview(width, height, bytes(out))


def _decode_dds_simple(data: bytes) -> FlagPreview | None:
    """Uncompressed BGRA / RGBA DDS (tests). Live GameStar flags are BC7 via WIC."""
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", data, 12)
    fourcc = data[84:88]
    bitcount = struct.unpack_from("<I", data, 88)[0]
    offset = 128
    if fourcc == b"DX10":
        if len(data) < 148:
            return None
        dxgi = struct.unpack_from("<I", data, 128)[0]
        offset = 148
        # 87 B8G8R8A8_UNORM, 91 *_SRGB, 28 R8G8B8A8_UNORM
        if dxgi in (87, 91, 88, 93):
            return _rgba_from_bgra(data[offset:], width, height)
        if dxgi in (28, 26):
            return _rgba_from_rgba(data[offset:], width, height)
        if dxgi in (98, 99):  # BC7_UNORM / BC7_UNORM_SRGB
            from config_scanner.bc7 import decode_bc7_image

            try:
                rgba = decode_bc7_image(data[offset:], width, height)
            except ValueError:
                return None
            return FlagPreview(width, height, rgba)
        return None
    if fourcc in (b"\x00\x00\x00\x00", b"") or bitcount in (24, 32):
        if bitcount == 24:
            return _rgba_from_bgr(data[offset:], width, height)
        return _rgba_from_bgra(data[offset:], width, height)
    return None


def _rgba_from_bgra(blob: bytes, width: int, height: int) -> FlagPreview | None:
    need = width * height * 4
    if width <= 0 or height <= 0 or len(blob) < need:
        return None
    out = bytearray(need)
    src = blob[:need]
    for i in range(0, need, 4):
        out[i] = src[i + 2]
        out[i + 1] = src[i + 1]
        out[i + 2] = src[i]
        out[i + 3] = src[i + 3]
    return FlagPreview(width, height, bytes(out))


def _rgba_from_rgba(blob: bytes, width: int, height: int) -> FlagPreview | None:
    need = width * height * 4
    if width <= 0 or height <= 0 or len(blob) < need:
        return None
    return FlagPreview(width, height, bytes(blob[:need]))


def _rgba_from_bgr(blob: bytes, width: int, height: int) -> FlagPreview | None:
    need = width * height * 3
    if width <= 0 or height <= 0 or len(blob) < need:
        return None
    out = bytearray(width * height * 4)
    di = 0
    for i in range(0, need, 3):
        out[di] = blob[i + 2]
        out[di + 1] = blob[i + 1]
        out[di + 2] = blob[i]
        out[di + 3] = 255
        di += 4
    return FlagPreview(width, height, bytes(out))


def _decode_dds_wic(path: Path) -> FlagPreview | None:
    """Windows Imaging Component — required for live BC7 ``flag_*.dds``."""
    if sys.platform != "win32":
        return None
    try:
        return _wic_decode_path(path)
    except (OSError, ValueError, ArithmeticError):
        return None


def _wic_decode_path(path: Path) -> FlagPreview | None:
    import ctypes
    from ctypes import HRESULT, POINTER, byref, c_void_p, c_uint32, c_wchar_p

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = (c_void_p, c_uint32)
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = ()
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = (
        c_void_p,
        c_void_p,
        c_uint32,
        c_void_p,
        POINTER(c_void_p),
    )
    ole32.CoCreateInstance.restype = HRESULT

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", c_uint32),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def guid(text: str) -> GUID:
        # {xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
        body = text.strip("{}").replace("-", "")
        data4 = (ctypes.c_ubyte * 8)(*bytes.fromhex(body[16:]))
        return GUID(
            int(body[0:8], 16),
            int(body[8:12], 16),
            int(body[12:16], 16),
            data4,
        )

    CLSID_WICImagingFactory = guid("{CACAF262-9370-4615-A13B-9F5539DA4C0A}")
    IID_IWICImagingFactory = guid("{EC5EC8A9-C395-4314-9C77-54D7A935FF70}")
    GUID_WICPixelFormat32bppRGBA = guid("{F5C7AD2D-6A8D-43DD-A7A8-A29935261AE9}")
    CLSCTX_INPROC_SERVER = 1
    GENERIC_READ = 0x80000000
    COINIT_MULTITHREADED = 0x0
    WICDecodeMetadataCacheOnDemand = 0
    WICBitmapDitherTypeNone = 0
    WICBitmapPaletteTypeCustom = 0

    class _COM:
        def __init__(self, punk: int) -> None:
            self.punk = punk
            vtbl = ctypes.cast(c_void_p(punk), POINTER(c_void_p)).contents
            self.fn = ctypes.cast(vtbl, POINTER(c_void_p))

        def _fn(self, index: int, restype, *argtypes):
            proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
            return proto(self.fn[index])

        def release(self) -> None:
            self._fn(2, c_uint32)(self.punk)

    initialized = False
    factory = decoder = frame = converter = None
    try:
        hr = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        # S_OK, S_FALSE, RPC_E_CHANGED_MODE
        if hr not in (0, 1, 0x80010106):
            return None
        initialized = hr in (0, 1)
        punk = c_void_p()
        ole32.CoCreateInstance(
            ctypes.byref(CLSID_WICImagingFactory),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_IWICImagingFactory),
            byref(punk),
        )
        if not punk.value:
            return None
        factory = _COM(punk.value)
        decoder_ptr = c_void_p()
        create_dec = factory._fn(
            3,
            HRESULT,
            c_wchar_p,
            c_void_p,
            c_uint32,
            c_uint32,
            POINTER(c_void_p),
        )
        create_dec(
            factory.punk,
            str(path),
            None,
            GENERIC_READ,
            WICDecodeMetadataCacheOnDemand,
            byref(decoder_ptr),
        )
        if not decoder_ptr.value:
            return None
        decoder = _COM(decoder_ptr.value)
        frame_ptr = c_void_p()
        get_frame = decoder._fn(13, HRESULT, c_uint32, POINTER(c_void_p))
        get_frame(decoder.punk, 0, byref(frame_ptr))
        if not frame_ptr.value:
            return None
        frame = _COM(frame_ptr.value)
        conv_ptr = c_void_p()
        create_conv = factory._fn(10, HRESULT, POINTER(c_void_p))
        create_conv(factory.punk, byref(conv_ptr))
        if not conv_ptr.value:
            return None
        converter = _COM(conv_ptr.value)
        init_conv = converter._fn(
            8,
            HRESULT,
            c_void_p,
            POINTER(GUID),
            c_uint32,
            c_void_p,
            ctypes.c_double,
            c_uint32,
        )
        init_conv(
            converter.punk,
            frame.punk,
            ctypes.byref(GUID_WICPixelFormat32bppRGBA),
            WICBitmapDitherTypeNone,
            None,
            0.0,
            WICBitmapPaletteTypeCustom,
        )
        width = c_uint32()
        height = c_uint32()
        get_size = converter._fn(3, HRESULT, POINTER(c_uint32), POINTER(c_uint32))
        get_size(converter.punk, byref(width), byref(height))
        w, h = int(width.value), int(height.value)
        if w <= 0 or h <= 0 or w > 2048 or h > 2048:
            return None
        stride = w * 4
        buf = (ctypes.c_ubyte * (stride * h))()
        copy = converter._fn(
            7,
            HRESULT,
            c_void_p,
            c_uint32,
            c_uint32,
            c_void_p,
        )

        class WICRect(ctypes.Structure):
            _fields_ = [
                ("X", ctypes.c_int),
                ("Y", ctypes.c_int),
                ("Width", ctypes.c_int),
                ("Height", ctypes.c_int),
            ]

        rect = WICRect(0, 0, w, h)
        copy(converter.punk, ctypes.byref(rect), stride, stride * h, buf)
        return FlagPreview(w, h, bytes(buf))
    finally:
        for obj in (converter, frame, decoder, factory):
            if obj is not None:
                try:
                    obj.release()
                except OSError:
                    pass
        if initialized:
            try:
                ole32.CoUninitialize()
            except OSError:
                pass


def write_uncompressed_bgra_dds(path: Path, width: int, height: int, bgra: bytes) -> None:
    """Test helper: uncompressed 32-bit BGRA DDS."""
    need = width * height * 4
    if len(bgra) < need:
        raise ValueError("BGRA buffer too small")
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    # caps | height | width | pixelformat
    struct.pack_into("<I", header, 8, 0x1 | 0x2 | 0x4 | 0x1000)
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    struct.pack_into("<I", header, 20, width * 4)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, 0x41)  # RGB | alpha
    struct.pack_into("<I", header, 88, 32)
    struct.pack_into("<I", header, 92, 0x00FF0000)
    struct.pack_into("<I", header, 96, 0x0000FF00)
    struct.pack_into("<I", header, 100, 0x000000FF)
    struct.pack_into("<I", header, 104, 0xFF000000)
    struct.pack_into("<I", header, 108, 0x1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bgra[:need])
