"""On-screen recording pill — per-pixel alpha, multi-style visualizers,
caret-aware dodging.

Rendering: PIL at 2× supersampling → UpdateLayeredWindow with a real alpha
channel (smooth AA edges, soft shadows, luminous glow).

Visualizer styles (✦ button on the pill cycles them live):
  strings   — Siri-style flowing ribbons
  spectrum  — mirrored filled waveform (SoundCloud-ish, thicker)
  bars      — round-capped equalizer bars
  scope     — single thin oscilloscope line (synthetic, minimal)
  pulse     — breathing orb with expanding ripple rings
  particles — drifting specks that dance with your voice

The ◐ button cycles color themes. Both choices persist.

Caret dodge: while you dictate, the pill tracks the text caret of the focused
app (GetGUIThreadInfo) and — if it would overlap what you're typing — slides
to the nearest clear spot, easing back home when the coast is clear.
"""

import colorsys
import ctypes
import logging
import math
import queue
import threading

import numpy as np

from .themes import get_theme

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

_CHROMA = "#010203"
_EASE = 0.30
_SLIDE_PX = 16
_SS = 2  # supersampling factor (2× + DPI-aware = crisp; 3× starved the
         # keyboard hook of GIL time and lagged system-wide input)

WAVES = ["strings", "spectrum", "bars", "scope", "pulse", "particles",
         "beam", "pixels"]
BGS = ["gradient", "solid", "aurora", "carbon", "nebula",
       "rain", "aura", "petals", "synthwave", "invaders"]

# 8-bit invader sprite (two animation frames: legs in / legs out)
_INVADER = [
    ["..X....X..", "...X..X...", "..XXXXXX..", ".XX.XX.XX.",
     "XXXXXXXXXX", "X.XXXXXX.X", "X.X....X.X", "...XX.XX.."],
    ["..X....X..", "X..X..X..X", "X.XXXXXX.X", "XXX.XX.XXX",
     "XXXXXXXXXX", ".XXXXXXXX.", "..X....X..", ".X......X."],
]


# ── color helpers ────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _mix(a: str, b: str, t: float) -> str:
    (r1, g1, b1), (r2, g2, b2) = _hex_to_rgb(a), _hex_to_rgb(b)
    return (f"#{int(r1 + (r2 - r1) * t):02x}"
            f"{int(g1 + (g2 - g1) * t):02x}{int(b1 + (b2 - b1) * t):02x}")


def _darken(h: str, t: float) -> str:
    return _mix(h, "#000000", t)


def _rgba(h: str, a: int) -> tuple[int, int, int, int]:
    r, g, b = _hex_to_rgb(h)
    return r, g, b, a


# ── Win32 plumbing ───────────────────────────────────────────────────────────

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = (("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte))


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32))


class _BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", ctypes.c_uint32 * 3))


class _POINT(ctypes.Structure):
    _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))


class _SIZE(ctypes.Structure):
    _fields_ = (("cx", ctypes.c_long), ("cy", ctypes.c_long))


class _RECT(ctypes.Structure):
    _fields_ = (("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long))


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = (("cbSize", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", _RECT))


def _caret_screen_rect() -> tuple[int, int, int, int] | None:
    """Screen rect of the text caret in the foreground app (if it has one)."""
    try:
        gti = _GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if not _user32.GetGUIThreadInfo(0, ctypes.byref(gti)) or not gti.hwndCaret:
            return None
        tl = _POINT(gti.rcCaret.left, gti.rcCaret.top)
        br = _POINT(gti.rcCaret.right, gti.rcCaret.bottom)
        _user32.ClientToScreen(gti.hwndCaret, ctypes.byref(tl))
        _user32.ClientToScreen(gti.hwndCaret, ctypes.byref(br))
        if br.y <= tl.y:
            return None
        return tl.x, tl.y, max(br.x, tl.x + 2), br.y
    except Exception:  # noqa: BLE001
        return None


_uia = None
_uia_fails = 0


def _uia_focused_rect() -> tuple[int, int, int, int] | None:
    """Fallback for apps with no Win32 caret (browsers, Electron): the focused
    text element's bounding rect via UI Automation."""
    global _uia, _uia_fails
    if _uia_fails >= 3:
        return None
    try:
        if _uia is None:
            import comtypes
            import comtypes.client

            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen.UIAutomationClient import (CUIAutomation,
                                                         IUIAutomation)

            _uia = comtypes.CoCreateInstance(
                CUIAutomation._reg_clsid_, interface=IUIAutomation,
                clsctx=comtypes.CLSCTX_INPROC_SERVER)
        el = _uia.GetFocusedElement()
        if el is None:
            return None
        if el.CurrentControlType not in (50004, 50030, 50025):  # Edit/Document/Custom-edit
            return None
        r = el.CurrentBoundingRectangle
        if r.right <= r.left or r.bottom <= r.top:
            return None
        # A rect covering most of the screen is a renderer surface, not a field.
        sw = _user32.GetSystemMetrics(0)
        sh = _user32.GetSystemMetrics(1)
        if (r.right - r.left) * (r.bottom - r.top) > 0.55 * sw * sh:
            return None
        return r.left, r.top, r.right, r.bottom
    except Exception:  # noqa: BLE001
        _uia_fails += 1
        return None


def _premultiplied_bgra(img) -> bytes:
    arr = np.asarray(img, dtype=np.uint8)
    a = arr[:, :, 3].astype(np.uint16)
    prem = (arr[:, :, :3].astype(np.uint16) * a[..., None] // 255).astype(np.uint8)
    bgra = np.dstack((prem[:, :, 2], prem[:, :, 1], prem[:, :, 0], arr[:, :, 3]))
    return np.ascontiguousarray(bgra).tobytes()


def _ulw_paint(hwnd: int, img, x: int, y: int, alpha: int) -> bool:
    w, h = img.size
    hdc_screen = _user32.GetDC(0)
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    ok = False
    hbmp = None
    try:
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        hbmp = _gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0,
                                       ctypes.byref(bits), None, 0)
        if not hbmp or not bits:
            return False
        buf = _premultiplied_bgra(img)
        ctypes.memmove(bits, buf, len(buf))
        old = _gdi32.SelectObject(hdc_mem, hbmp)
        bf = _BLENDFUNCTION(0, 0, max(0, min(255, alpha)), 1)
        pt, sz, src = _POINT(x, y), _SIZE(w, h), _POINT(0, 0)
        ok = bool(_user32.UpdateLayeredWindow(
            hwnd, hdc_screen, ctypes.byref(pt), ctypes.byref(sz),
            hdc_mem, ctypes.byref(src), 0, ctypes.byref(bf), 2))
        _gdi32.SelectObject(hdc_mem, old)
    finally:
        if hbmp:
            _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(0, hdc_screen)
    return ok


# ── the overlay ──────────────────────────────────────────────────────────────

class Overlay:
    def __init__(self, ui_cfg: dict, get_level=None, on_click=None,
                 on_cycle=None, on_cycle_wave=None, on_cycle_bg=None,
                 get_stats=None, on_move=None):
        self.enabled = bool(ui_cfg.get("overlay", True))
        self._get_level = get_level or (lambda: 0.0)
        self._on_click = on_click            # ● dot: finish recording
        self._on_cycle = on_cycle            # ◐ theme button
        self._on_cycle_wave = on_cycle_wave  # ✦ style button
        self._on_cycle_bg = on_cycle_bg      # ▦ / right-click: next background
        self._get_stats = get_stats or (lambda: (0.0, 0, ""))
        self._on_move = on_move              # persist dragged position
        self._bg = ui_cfg.get("bg", "gradient")
        self._pill_width = int(ui_cfg.get("pill_width", 180))
        self._expanded = False
        self._egg = None         # {"kind": n, "t0": frame} while an egg plays
        self._egg_n = 0
        pos = ui_cfg.get("pos")
        self._custom_home = tuple(pos) if isinstance(pos, (list, tuple)) else None
        self._theme = get_theme(ui_cfg.get("theme", "minimal-dark"),
                                ui_cfg.get("theme_overrides") or {})
        self._overrides = ui_cfg.get("theme_overrides") or {}
        self._wave = ui_cfg.get("wave", "strings")
        self._weight = float(ui_cfg.get("wave_weight", 1.0))
        self._position = ui_cfg.get("position", "bottom")
        self._offset = int(ui_cfg.get("offset_px", 80))
        self._scale = float(ui_cfg.get("scale", 1.0))
        self._q: queue.Queue = queue.Queue()
        self._display_level = 0.0
        if self.enabled:
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="overlay"
            )
            self._thread.start()

    # -- thread-safe API ------------------------------------------------------

    def show(self, state: str):
        if self.enabled:
            self._q.put(("show", state))

    def set_preview(self, text: str):
        pass  # the compact visual shows no text

    def flash_done(self, text: str):
        if self.enabled:
            self._q.put(("hide", None))

    def hide(self):
        if self.enabled:
            self._q.put(("hide", None))

    def set_theme(self, name: str):
        if self.enabled:
            self._q.put(("theme", name))

    def set_wave(self, name: str):
        if self.enabled:
            self._q.put(("wave", name))

    def set_bg(self, name: str):
        if self.enabled:
            self._q.put(("bg", name))

    def stop(self):
        if self.enabled:
            self._q.put(("quit", None))

    # -- geometry ----------------------------------------------------------------

    _EGG_PAD = 84    # transparent headroom above the pill while an egg plays
    _EGG_DUR = 62    # frames (~2s)

    def _egg_pad(self) -> int:
        return int(self._EGG_PAD * self._scale) if self._egg else 0

    def _dims(self) -> tuple[int, int]:
        w = int(self._pill_width * self._scale)
        return w, int(40 * self._scale) + self._egg_pad()

    # -- static pill body (cached) -------------------------------------------------

    def _masked(self, img_rgba):
        """Clip an RGBA layer to the pill body shape."""
        out = img_rgba.copy()
        out.putalpha(Image.composite(
            img_rgba.getchannel("A"),
            Image.new("L", img_rgba.size, 0), self._body_mask))
        return out

    def _render_base(self, w: int, h: int, pad: int = 0):
        key = (w, h, pad, self._theme["bg"], self._theme["border"], self._bg)
        if getattr(self, "_base_key", None) == key:
            return self._base
        W, H = w * _SS, h * _SS
        P = pad * _SS  # transparent easter-egg headroom above the pill
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(sh)
        d.rounded_rectangle((5 * _SS, P + 6 * _SS, W - 5 * _SS, H - 1 * _SS),
                            radius=(H - P - 7 * _SS) // 2, fill=(0, 0, 0, 110))
        sh = sh.filter(ImageFilter.GaussianBlur(3 * _SS))
        img = Image.alpha_composite(img, sh)
        d = ImageDraw.Draw(img)
        body = (2 * _SS, P + 1 * _SS, W - 2 * _SS, H - 5 * _SS)
        radius = (body[3] - body[1]) // 2
        d.rounded_rectangle(body, radius=radius,
                            fill=_rgba(_darken(self._theme["bg"], 0.30), 242),
                            outline=_rgba(self._theme["border"], 255),
                            width=_SS)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle(body, radius=radius, fill=255)
        self._body_mask = mask
        self._body_box = body

        # subtle accent wash fading left→right — each theme gets its own glow
        accent = _hex_to_rgb(self._theme["accent"])
        tint = np.zeros((H, W, 4), np.uint8)
        tint[..., 0], tint[..., 1], tint[..., 2] = accent
        tint[..., 3] = np.tile(np.linspace(26, 0, W, dtype=np.uint8), (H, 1))
        img = Image.alpha_composite(img, self._masked(Image.fromarray(tint, "RGBA")))

        if self._bg == "gradient":
            # polished black-gray: light crown fading into a deep base
            g = np.zeros((H, W, 4), np.uint8)
            col = np.linspace(30, 0, H, dtype=np.uint8)       # white sheen top…
            dk = np.linspace(0, 60, H, dtype=np.uint8)        # …dark weight below
            g[..., 0:3] = 255
            g[..., 3] = np.tile(col[:, None], (1, W))
            img = Image.alpha_composite(img, self._masked(Image.fromarray(g, "RGBA")))
            g2 = np.zeros((H, W, 4), np.uint8)
            g2[..., 3] = np.tile(dk[:, None], (1, W))
            img = Image.alpha_composite(img, self._masked(Image.fromarray(g2, "RGBA")))
        elif self._bg == "carbon":
            cb = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            dc = ImageDraw.Draw(cb)
            step = 7 * _SS
            for x in range(-H, W + H, step):
                dc.line([(x, 0), (x + H, H)], fill=(255, 255, 255, 10),
                        width=_SS)
                dc.line([(x + step // 2, 0), (x + step // 2 - H, H)],
                        fill=(0, 0, 0, 26), width=_SS)
            img = Image.alpha_composite(img, self._masked(cb))
        elif self._bg == "nebula":
            stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ds = ImageDraw.Draw(stars)
            for i in range(30):
                sx = ((i * 2654435761) % 977) / 977 * W
                sy = ((i * 40503) % 613) / 613 * H
                r = (0.5 + ((i * 7) % 5) / 5) * _SS
                ds.ellipse((sx - r, sy - r, sx + r, sy + r),
                           fill=(255, 255, 255, 70))
            img = Image.alpha_composite(img, self._masked(stars))

        self._base_key, self._base = key, img
        self._aurora_cache = None
        return img

    def _aurora_layer(self, frame):
        """Slowly drifting blurred color blobs — cached strip, panned live."""
        W, H = self._base.size
        if self._aurora_cache is None:
            colors = self._theme.get("strings") or ["#ff5fa2", "#8b5cf6", "#00d4ff"]
            W2 = W * 2
            strip = Image.new("RGBA", (W2, H), (0, 0, 0, 0))
            ds = ImageDraw.Draw(strip)
            blobs = colors * 2
            for i, c in enumerate(blobs):
                cx = (i + 0.5) * W2 / len(blobs)
                cy = H * (0.25 + 0.5 * ((i * 37) % 10) / 10)
                ds.ellipse((cx - W * 0.16, cy - H * 0.55,
                            cx + W * 0.16, cy + H * 0.55), fill=_rgba(c, 64))
            self._aurora_cache = strip.filter(ImageFilter.GaussianBlur(H // 3))
        strip = self._aurora_cache
        off = int(frame * 1.2 * _SS) % (strip.size[0] - W)
        return self._masked(strip.crop((off, 0, off + W, H)))

    # -- visualizer styles (all drawn at _SS scale) ---------------------------------

    def _wave_strings(self, d, mid, x0, x1, lv, frame, colors):
        span = x1 - x0
        amp = (2.2 + 12.5 * lv) * self._scale * _SS
        paths = []
        for si, c in enumerate(colors):
            ph1 = frame * 0.17 + si * 2.1
            ph2 = frame * 0.11 - si * 1.4
            pts = []
            for j in range(35):
                u = j / 34
                env = math.sin(math.pi * u)
                y = mid + env * (amp * 0.72 * math.sin(9.4 * u + ph1)
                                 + amp * 0.5 * math.sin(14.6 * u - ph2))
                pts.append((x0 + u * span, y))
            paths.append((pts, c))
        gw = int(4.5 * _SS * self._scale * self._weight)
        cw = max(2, int(1.8 * _SS * self._scale * self._weight))
        for pts, c in paths:
            d.line(pts, fill=_rgba(c, 88), width=gw, joint="curve")
        for pts, c in paths:
            d.line(pts, fill=_rgba(c, 255), width=cw, joint="curve")

    def _wave_spectrum(self, d, mid, x0, x1, lv, frame, colors):
        span = x1 - x0
        maxa = (2.0 + 12.0 * lv) * self._scale * _SS
        top, bot = [], []
        for j in range(41):
            u = j / 40
            env = math.sin(math.pi * u)
            a = env * maxa * (0.35 + 0.65 * abs(
                math.sin(7.1 * u + frame * 0.13)
                * math.sin(3.3 * u - frame * 0.07)))
            top.append((x0 + u * span, mid - a))
            bot.append((x0 + u * span, mid + a))
        poly = top + bot[::-1]
        d.polygon(poly, fill=_rgba(colors[0], 80))
        lw = max(2, int(1.6 * _SS * self._scale * self._weight))
        d.line(top, fill=_rgba(colors[1 % len(colors)], 230), width=lw,
               joint="curve")
        d.line(bot, fill=_rgba(colors[2 % len(colors)], 230), width=lw,
               joint="curve")

    def _wave_bars(self, d, mid, x0, x1, lv, frame, colors):
        n = 12
        span = x1 - x0
        step = span / n
        bw = max(3, int(3.2 * _SS * self._scale * self._weight))
        for i in range(n):
            ph = math.sin(frame * 0.2 + i * 0.9)
            bh = (2.0 + (0.30 + 0.70 * abs(ph)) * 13.0 * lv + 1.2) \
                * self._scale * _SS
            cx = x0 + i * step + step / 2
            c = colors[i % len(colors)]
            d.rounded_rectangle((cx - bw / 2, mid - bh, cx + bw / 2, mid + bh),
                                radius=bw / 2, fill=_rgba(c, 235))

    def _wave_scope(self, d, mid, x0, x1, lv, frame, colors):
        span = x1 - x0
        amp = (1.5 + 11.0 * lv) * self._scale * _SS
        pts = []
        for j in range(61):
            u = j / 60
            env = math.sin(math.pi * u)
            y = mid + env * amp * (math.sin(18.0 * u + frame * 0.3)
                                   + 0.4 * math.sin(31.0 * u - frame * 0.21))
            pts.append((x0 + u * span, y))
        lw = max(1, int(1.1 * _SS * self._scale * self._weight))
        d.line(pts, fill=_rgba(colors[0], 70), width=lw * 3, joint="curve")
        d.line(pts, fill=_rgba(colors[0], 255), width=lw, joint="curve")

    def _wave_pulse(self, d, mid, x0, x1, lv, frame, colors):
        cx = (x0 + x1) / 2
        r = (5.0 + 9.0 * lv + 1.2 * math.sin(frame * 0.2)) * self._scale * _SS
        # expanding ripple rings while there's voice
        if lv > 0.12:
            for k in range(2):
                prog = (frame * 0.022 + k * 0.5) % 1.0
                rr = r + prog * ((x1 - x0) / 2 - r)
                a = int(120 * (1.0 - prog))
                d.ellipse((cx - rr, mid - rr, cx + rr, mid + rr),
                          outline=_rgba(colors[(k + 1) % len(colors)], a),
                          width=max(1, int(1.4 * _SS * self._scale)))
        d.ellipse((cx - r * 2.0, mid - r * 2.0, cx + r * 2.0, mid + r * 2.0),
                  fill=_rgba(colors[0], 42))
        d.ellipse((cx - r, mid - r, cx + r, mid + r), fill=_rgba(colors[0], 255))

    def _wave_beam(self, d, mid, x0, x1, lv, frame, colors):
        """Kamehameha: a charging orb firing an energy beam — voice = power."""
        orb_r = (3.5 + 5.0 * lv + 0.8 * math.sin(frame * 0.3)) \
            * self._scale * _SS
        bx = x0 + orb_r + 2 * _SS
        thick = (1.2 + 9.0 * lv) * self._scale * _SS
        top, bot = [], []
        for j in range(25):
            u = j / 24
            x = bx + u * (x1 - bx)
            wob = math.sin(11.0 * u - frame * 0.45) * thick * 0.25
            top.append((x, mid - thick / 2 + wob))
            bot.append((x, mid + thick / 2 + wob))
        d.polygon(top + bot[::-1], fill=_rgba(colors[2 % len(colors)], 110))
        d.line([(bx, mid), (x1, mid)], fill=_rgba(colors[0], 235),
               width=max(2, int(thick * 0.35)))
        d.ellipse((bx - orb_r * 1.8, mid - orb_r * 1.8,
                   bx + orb_r * 1.8, mid + orb_r * 1.8),
                  fill=_rgba(colors[1 % len(colors)], 55))
        d.ellipse((bx - orb_r, mid - orb_r, bx + orb_r, mid + orb_r),
                  fill=_rgba(colors[0], 255))

    def _wave_pixels(self, d, mid, x0, x1, lv, frame, colors):
        """8-bit equalizer: chunky quantized blocks, arcade style."""
        n = 11
        span = x1 - x0
        step = span / n
        block = max(2, int(2.6 * _SS * self._scale))
        gap = max(1, _SS)
        for i in range(n):
            ph = abs(math.sin(frame * 0.17 + i * 1.1))
            levels = 1 + int((0.25 + 0.75 * ph) * lv * 4 + 0.4)  # 1..5
            cx = x0 + i * step + step / 2
            c = colors[i % len(colors)]
            for k in range(levels):  # stack outward from center, mirrored
                off = k * (block + gap)
                d.rectangle((cx - block, mid - off - block,
                             cx + block, mid - off), fill=_rgba(c, 235))
                d.rectangle((cx - block, mid + off,
                             cx + block, mid + off + block), fill=_rgba(c, 235))

    def _wave_particles(self, d, mid, x0, x1, lv, frame, colors):
        n = 15
        span = x1 - x0
        for i in range(n):
            u = (i + 0.5) / n
            ph = i * 1.7
            y = mid + math.sin(frame * 0.14 + ph) \
                * (2.0 + 10.0 * lv) * self._scale * _SS * math.sin(math.pi * u)
            r = (1.1 + ((i * 2654435761) % 97) / 97 * 1.6) * self._scale * _SS
            a = 110 + int(120 * abs(math.sin(frame * 0.1 + i * 0.8)))
            c = colors[i % len(colors)]
            d.ellipse((x0 + u * span - r, y - r, x0 + u * span + r, y + r),
                      fill=_rgba(c, min(255, a)))

    # -- animated backgrounds (drawn per frame, clipped to the pill) ----------------

    def _bg_rain(self, W, H, frame, colors):
        """Matrix code rain — falling glyph columns with fading tails."""
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if not hasattr(self, "_rain_font"):
            try:
                from PIL import ImageFont

                self._rain_font = ImageFont.truetype(
                    "consola.ttf", int(6.5 * _SS * self._scale))
            except Exception:  # noqa: BLE001
                self._rain_font = None
        glyphs = "01ｱｲｳｴｸｼﾘﾂtwm*+"
        c = colors[0]
        step = int(11 * self._scale) * _SS
        for i in range(max(1, W // step)):
            x = i * step + step // 3
            speed = 0.9 + ((i * 7) % 5) / 4.0
            head = (frame * speed * 1.6 * _SS + i * 97 * _SS) % (H + 16 * _SS)
            for j in range(4):  # head + fading tail
                gy = head - j * 7 * _SS * self._scale
                a = max(0, 120 - j * 34)
                ch = glyphs[(i * 31 + j * 17 + frame // 8) % len(glyphs)]
                if self._rain_font:
                    d.text((x, gy), ch, fill=_rgba(c, a), font=self._rain_font)
                else:
                    d.rectangle((x, gy, x + 2 * _SS, gy + 4 * _SS),
                                fill=_rgba(c, a))
        return layer

    def _bg_aura(self, W, H, frame, colors):
        """Saiyan aura — flame tongues flickering upward from the base."""
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        n = 9
        for i in range(n):
            x = (i + 0.5) * W / n
            flick = math.sin(frame * 0.31 + i * 1.35)
            fh = (7.0 + 11.0 * flick * flick) * self._scale * _SS
            wdt = 5.5 * self._scale * _SS
            c = colors[i % 2]
            d.polygon([(x - wdt, H), (x + wdt, H),
                       (x + wdt * 0.25, H - fh * 0.6), (x, H - fh)],
                      fill=_rgba(c, 62))
            d.polygon([(x - wdt * 0.5, H), (x + wdt * 0.5, H),
                       (x, H - fh * 0.7)], fill=_rgba(colors[0], 80))
        for i in range(4):  # rising sparks
            sx = ((i * 48271) % 811) / 811 * W
            sy = H - ((frame * (1.5 + i * 0.4) * _SS + i * 200) % H)
            r = 1.2 * _SS
            d.ellipse((sx - r, sy - r, sx + r, sy + r),
                      fill=_rgba(colors[0], 130))
        return layer

    def _bg_petals(self, W, H, frame, colors):
        """Sakura petals drifting down with a gentle sway."""
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        pink = "#ffb7c5"
        for i in range(8):
            base_x = ((i * 2654435761) % 997) / 997 * W
            speed = 0.5 + ((i * 13) % 7) / 9.0
            y = (frame * speed * _SS + i * 300) % (H + 12 * _SS) - 6 * _SS
            x = base_x + math.sin(frame * 0.06 + i * 1.9) * 8 * _SS
            rx = (2.4 + (i % 3)) * self._scale * _SS * 0.8
            ry = rx * 0.55
            if i % 2:
                rx, ry = ry, rx  # alternate orientation ≈ tumbling
            d.ellipse((x - rx, y - ry, x + rx, y + ry),
                      fill=_rgba(pink, 120))
        return layer

    def _bg_synthwave(self, W, H, frame, colors):
        """Outrun sunset — glowing sun, scrolling perspective grid."""
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        magenta, cyan = "#ff2bd6", "#00e5ff"
        horizon = int(H * 0.42)
        # sun with scanline slits
        scx, sr = W * 0.72, H * 0.55
        d.ellipse((scx - sr, horizon - sr, scx + sr, horizon + sr),
                  fill=_rgba("#ff9a3d", 46))
        for k in range(3):
            sy = horizon - sr + (k + 1) * sr / 2.2
            d.rectangle((scx - sr, sy, scx + sr, sy + 2 * _SS), fill=(0, 0, 0, 0))
        d.line([(0, horizon), (W, horizon)], fill=_rgba(cyan, 120),
               width=max(1, _SS))
        # scrolling horizontal grid lines (accelerating toward the viewer)
        for k in range(5):
            p = ((k / 5) + frame * 0.012) % 1.0
            y = horizon + (H - horizon) * p * p
            d.line([(0, y), (W, y)], fill=_rgba(magenta, int(30 + 70 * p)),
                   width=max(1, _SS))
        # converging verticals
        vx = W / 2
        for k in range(-4, 5):
            x_h = vx + k * W * 0.09
            x_b = vx + k * W * 0.26
            d.line([(x_h, horizon), (x_b, H)], fill=_rgba(magenta, 46),
                   width=max(1, _SS))
        return layer

    def _bg_invaders(self, W, H, frame, colors):
        """Space Invaders marching across the pill, legs animating."""
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        sprite = _INVADER[(frame // 14) % 2]
        px = max(1, int(0.9 * _SS * self._scale))
        sw = len(sprite[0]) * px
        march = int(((frame // 5) % 24) - 12) * abs(px)
        c = colors[0]
        for k in range(3):
            ox = int(W * (0.18 + 0.3 * k)) + (march if k % 2 == 0 else -march)
            oy = int(H * 0.22) + (0 if k % 2 == 0 else int(H * 0.3))
            for r, row in enumerate(sprite):
                for cix, ch in enumerate(row):
                    if ch == "X":
                        x = ox + cix * px
                        d.rectangle((x, oy + r * px, x + px - 1,
                                     oy + (r + 1) * px - 1), fill=_rgba(c, 72))
            _ = sw
        return layer

    # -- full frame -----------------------------------------------------------------

    def _font(self, px: int):
        key = px
        cache = getattr(self, "_font_cache", None)
        if cache is None:
            cache = self._font_cache = {}
        if key not in cache:
            try:
                from PIL import ImageFont

                cache[key] = ImageFont.truetype("segoeui.ttf", px)
            except Exception:  # noqa: BLE001
                cache[key] = None
        return cache[key]

    def _egg_colors(self, t, frame):
        if t.get("animate_strings"):  # 🌈 live hue-cycling (rgb-gamer)
            return ["#%02x%02x%02x" % tuple(
                int(c * 255) for c in colorsys.hsv_to_rgb(
                    (frame * 0.006 + i / 3) % 1.0, 0.85, 1.0))
                for i in range(3)]
        return t.get("strings") or ["#ff5fa2", "#8b5cf6", "#00d4ff"]

    def _draw_egg(self, d, W, P, rel, colors):
        """The click surprise, played in the transparent headroom above."""
        p = min(1.0, rel / self._EGG_DUR)
        kind = self._egg["kind"]
        s = self._scale * _SS
        if kind == 0:  # 🎆 firework: rocket up, then burst with gravity
            cx = W / 2
            if p < 0.32:
                ry = P - (P * 0.75) * (p / 0.32)
                d.line([(cx, ry + 8 * s), (cx, ry + 16 * s)],
                       fill=_rgba(colors[0], 160), width=int(1.5 * s))
                d.ellipse((cx - 2 * s, ry - 2 * s, cx + 2 * s, ry + 2 * s),
                          fill=_rgba(colors[0], 255))
            else:
                q = (p - 0.32) / 0.68
                by = P * 0.25
                for i in range(16):
                    ang = i * math.tau / 16
                    rr = q * P * 0.55
                    px = cx + math.cos(ang) * rr
                    py = by + math.sin(ang) * rr * 0.8 + q * q * P * 0.3
                    a = int(255 * (1 - q))
                    r = (1.6 + (i % 3) * 0.6) * s * (1 - q * 0.5)
                    d.ellipse((px - r, py - r, px + r, py + r),
                              fill=_rgba(colors[i % len(colors)], max(0, a)))
        elif kind == 1:  # 🎉 confetti cannon
            for i in range(24):
                h1 = (i * 2654435761) % 997 / 997
                h2 = (i * 40503) % 613 / 613
                vx = (h1 - 0.5) * W * 0.9
                x = W / 2 + vx * p
                y = P - (2.6 * p - 2.2 * p * p) * P * (0.5 + h2 * 0.5)
                a = int(255 * (1 - max(0.0, p - 0.6) / 0.4))
                rw = (2.5 if (i + rel // 6) % 2 else 1.2) * s
                rh = (1.2 if (i + rel // 6) % 2 else 2.5) * s  # flutter
                d.rectangle((x - rw, y - rh, x + rw, y + rh),
                            fill=_rgba(colors[i % len(colors)], max(0, a)))
        else:  # 👻 peeker: rises from behind the pill, blinks, ducks back
            gx = W * 0.72
            gw = 13 * s
            rise = (min(p / 0.28, 1.0) if p < 0.72
                    else max(0.0, 1.0 - (p - 0.72) / 0.28))
            top = P - rise * 26 * s
            body_c = _rgba(colors[0], 235)
            d.rounded_rectangle((gx - gw, top, gx + gw, P + 4 * s),
                                radius=gw, fill=body_c)
            blink = 0.42 < p < 0.5
            ey = top + 10 * s
            for ex in (gx - 4.5 * s, gx + 4.5 * s):
                if blink:
                    d.line([(ex - 2 * s, ey), (ex + 2 * s, ey)],
                           fill=(15, 18, 24, 255), width=int(s))
                else:
                    d.ellipse((ex - 2 * s, ey - 2.6 * s, ex + 2 * s, ey + 2.6 * s),
                              fill=(15, 18, 24, 255))

    def _render_frame(self, frame: int, state: str, w: int, h: int):
        t = self._theme
        W, H = w * _SS, h * _SS
        pad = self._egg_pad()
        P = pad * _SS
        img = self._render_base(w, h, pad).copy()
        bg_colors = self._egg_colors(t, frame)
        if self._bg == "aurora":
            img = Image.alpha_composite(img, self._aurora_layer(frame))
        elif self._bg == "nebula":  # twinkles on top of the static stars
            tw = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            dt = ImageDraw.Draw(tw)
            for i in range(6):
                sx = ((i * 48271) % 811) / 811 * W
                sy = ((i * 16807) % 449) / 449 * H
                a = int(110 * abs(math.sin(frame * 0.06 + i * 1.7)))
                r = 1.1 * _SS
                dt.ellipse((sx - r, sy - r, sx + r, sy + r),
                           fill=(255, 255, 255, a))
            img = Image.alpha_composite(img, self._masked(tw))
        elif self._bg in ("rain", "aura", "petals", "synthwave", "invaders"):
            layer_fn = getattr(self, f"_bg_{self._bg}")
            img = Image.alpha_composite(
                img, self._masked(layer_fn(W, H, frame, bg_colors)))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        expanded = False  # (superseded by the easter egg — body click pops it)
        mid = P + (H - P - 4 * _SS) / 2 + 1 * _SS

        if self._egg and state in ("listening", "locked") and P:
            self._draw_egg(d, W, P, frame - self._egg["t0"], bg_colors)

        if state in ("listening", "locked"):
            color = t["dot"] if state == "listening" else t["accent"]
            pulse = 1.2 * math.sin(frame * 0.28) if state == "listening" else 0.0
            r = (4.2 + pulse) * self._scale * _SS
            cx = 18 * self._scale * _SS
            d.ellipse((cx - r * 1.9, mid - r * 1.9, cx + r * 1.9, mid + r * 1.9),
                      fill=_rgba(color, 45))
            d.ellipse((cx - r, mid - r, cx + r, mid + r), fill=_rgba(color, 255))

            lv = max(0.0, min(1.0, self._display_level))
            colors = bg_colors
            x0 = int(34 * self._scale) * _SS
            x1 = W - int(64 * self._scale) * _SS  # room for the buttons
            waver = getattr(self, f"_wave_{self._wave}", self._wave_strings)
            waver(d, mid, x0, x1, lv, frame, colors)

            mut = _rgba(t["muted"], 210)
            # ▦ background button (3×3 grid)
            gcx = W - 49 * self._scale * _SS
            gs = 1.9 * self._scale * _SS
            for gi in range(3):
                for gj in range(3):
                    gx = gcx + (gi - 1) * gs * 2.2
                    gy = mid + (gj - 1) * gs * 2.2
                    d.rectangle((gx - gs * 0.7, gy - gs * 0.7,
                                 gx + gs * 0.7, gy + gs * 0.7), fill=mut)
            # ✦ style button (diamond)
            scx = W - 31 * self._scale * _SS
            sr = 4.6 * self._scale * _SS
            d.polygon([(scx, mid - sr), (scx + sr, mid),
                       (scx, mid + sr), (scx - sr, mid)],
                      outline=mut, width=max(1, _SS - 1) or 1)
            # ◐ theme button (half-moon)
            bcx = W - 14 * self._scale * _SS
            br = 4.8 * self._scale * _SS
            d.ellipse((bcx - br, mid - br, bcx + br, mid + br),
                      outline=mut, width=_SS)
            d.pieslice((bcx - br, mid - br, bcx + br, mid + br),
                       start=90, end=270, fill=mut)

        elif state == "processing":
            cx0 = W / 2 - 13 * self._scale * _SS
            for i in range(3):
                ph = frame * 0.25 - i * 0.9
                r = (2.2 + 1.2 * max(0.0, math.sin(ph))) * self._scale * _SS
                cx = cx0 + i * 13 * self._scale * _SS
                d.ellipse((cx - r, mid - r, cx + r, mid + r),
                          fill=_rgba(t["accent"], 230))

        img = Image.alpha_composite(img, layer)
        return img.resize((w, h), Image.LANCZOS)

    # -- Tk thread ---------------------------------------------------------------------

    def _run(self):
        try:
            import tkinter as tk
        except ImportError:
            log.warning("tkinter unavailable — overlay disabled")
            self.enabled = False
            return
        try:
            ulw = _HAS_PIL
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            if not ulw:
                root.attributes("-alpha", 0.0)
                try:
                    root.attributes("-transparentcolor", _CHROMA)
                except tk.TclError:
                    pass
            root.configure(bg=_CHROMA)
            canvas = tk.Canvas(root, bg=_CHROMA, highlightthickness=0,
                               cursor="hand2")
            canvas.pack(fill="both", expand=True)

            # -- drag anywhere · click dot to finish · click body to expand --
            self._press = None       # (screen_x, screen_y, win_x, win_y)
            self._dragging = False

            def on_press(e):
                if self._state not in ("listening", "locked"):
                    return
                self._press = (e.x_root, e.y_root, self._x, self._y)
                self._dragging = False

            def on_motion(e):
                if self._press is None:
                    return
                dx = e.x_root - self._press[0]
                dy = e.y_root - self._press[1]
                if not self._dragging and dx * dx + dy * dy > (6 * self._scale) ** 2:
                    self._dragging = True
                if self._dragging:  # follow the cursor directly, no easing lag
                    self._x = self._x_target = self._press[2] + dx
                    self._y = self._y_target = self._press[3] + dy

            def on_release(e):
                press, self._press = self._press, None
                if press is None or self._state not in ("listening", "locked"):
                    return
                try:
                    if self._dragging:  # dropped: this is the new home
                        self._dragging = False
                        self._custom_home = (int(self._x), int(self._y))
                        if self._on_move:
                            self._on_move(int(self._x), int(self._y))
                        return
                    w, _h = self._dims()
                    pad = self._egg_pad()
                    py = e.y - pad  # y within the pill row itself
                    on_row = 0 <= py <= int(40 * self._scale)
                    if on_row and e.x >= w - int(22 * self._scale):
                        if self._on_cycle:
                            self._on_cycle()          # ◐ next theme
                    elif on_row and e.x >= w - int(40 * self._scale):
                        if self._on_cycle_wave:
                            self._on_cycle_wave()     # ✦ next visualizer
                    elif on_row and e.x >= w - int(58 * self._scale):
                        if self._on_cycle_bg:
                            self._on_cycle_bg()       # ▦ next background
                    elif on_row and e.x <= int(30 * self._scale):
                        if self._on_click:
                            self._on_click()          # ● dot: finish & vanish
                    else:
                        # 🥚 easter egg! something fun pops out of the top
                        fresh = self._egg is None
                        self._egg = {"kind": self._egg_n % 3, "t0": self._frame}
                        self._egg_n += 1
                        self._base_key = None
                        if fresh:  # grow the window UPWARD, pill stays put
                            gp = self._egg_pad()
                            self._y -= gp
                            self._y_target -= gp
                            self._hcur = float(self._dims()[1])
                except Exception:  # noqa: BLE001
                    log.exception("pill click handler failed")

            for wdg in (canvas, root):
                wdg.bind("<Button-1>", on_press)
                wdg.bind("<B1-Motion>", on_motion)
                wdg.bind("<ButtonRelease-1>", on_release)

            def right_clicked(_e):
                if self._state in ("listening", "locked") and self._on_cycle_bg:
                    try:
                        self._on_cycle_bg()  # right-click → next background
                    except Exception:  # noqa: BLE001
                        log.exception("bg cycle handler failed")

            canvas.bind("<Button-3>", right_clicked)
            root.bind("<Button-3>", right_clicked)

            # Per-monitor DPI: render at the display's native pixel density
            # (the process is DPI-aware; see __main__) → crisp, not stretched.
            try:
                dpi = _user32.GetDpiForWindow(
                    _user32.GetParent(root.winfo_id()) or root.winfo_id())
                if dpi:
                    self._scale *= dpi / 96.0
            except Exception:  # noqa: BLE001
                pass

            self._state = "hidden"
            self._frame = 0
            self._alpha = 0.0
            self._alpha_target = 0.0
            self._visible = False
            self._x = 0.0
            self._x_target = 0.0
            self._y = 0.0
            self._y_target = 0.0
            self._wcur, self._hcur = (float(v) for v in self._dims())
            self._ulw_ok = ulw
            self._ulw_fails = 0

            def hwnd_of():
                return (_user32.GetParent(root.winfo_id()) or root.winfo_id())

            def style_window():
                try:
                    hwnd = hwnd_of()
                    GWL_EXSTYLE = -20
                    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    new = style | 0x08000000 | 0x00000080  # NOACTIVATE|TOOLWINDOW
                    if self._ulw_ok:
                        new |= 0x00080000                  # LAYERED
                    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)
                except Exception:  # noqa: BLE001
                    pass

            def home_pos():
                w, h = self._dims()
                sw = root.winfo_screenwidth()
                sh = root.winfo_screenheight()
                if self._custom_home:  # user dragged it somewhere — respect that
                    hx = max(4, min(int(self._custom_home[0]), sw - w - 4))
                    hy = max(4, min(int(self._custom_home[1]), sh - h - 44))
                else:
                    hx = (sw - w) // 2
                    hy = (self._offset if self._position == "top"
                          else sh - h - self._offset)
                return hx, hy, sw, sh

            def place(entering: bool = False):
                w, h = self._dims()
                hx, hy, _, _ = home_pos()
                self._x_target = hx
                self._y_target = hy
                if entering:
                    self._x = float(hx)
                    self._y = hy + (-_SLIDE_PX if self._position == "top"
                                    else _SLIDE_PX) * self._scale
                    self._wcur, self._hcur = float(w), float(h)
                root.geometry(f"{w}x{h}+{int(self._x)}+{int(self._y)}")
                canvas.configure(width=w, height=h)

            def update_dodge():
                """Move away from the text zone — and STAY where we land.

                Sticky by design: once parked somewhere clear, the pill does
                not wander back home; it only moves again when the text zone
                reaches its current spot (no more ping-ponging while typing).
                """
                w, h = self._dims()
                hx, hy, sw, sh = home_pos()
                caret = _caret_screen_rect()
                from_caret = caret is not None
                if caret is None:
                    caret = _uia_focused_rect()
                if caret is None:
                    return  # nothing to dodge — stay wherever we are
                m = int(36 * self._scale)
                if from_caret:
                    # A bare caret means the TEXT LINE extends sideways — avoid
                    # the whole line band, forcing clean vertical hops.
                    zx0, zx1 = 0, sw
                else:
                    zx0, zx1 = caret[0] - m, caret[2] + m
                zy0, zy1 = caret[1] - m, caret[3] + m

                def clear(x, y):
                    return (x + w < zx0 or x > zx1 or y + h < zy0 or y > zy1)

                if clear(self._x_target, self._y_target):
                    return  # current spot is fine — don't move
                cands = [
                    (hx, hy),            # home, if it's free
                    (zx0 - w - 6, hy),   # slide left of the text zone
                    (zx1 + 6, hy),       # slide right of it
                    (hx, zy0 - h - 6),   # hop above it
                    (hx, zy1 + 6),       # drop below it
                ]
                valid = [(x, y) for x, y in cands
                         if 6 <= x <= sw - w - 6 and 6 <= y <= sh - h - 48
                         and clear(x, y)]
                if valid:
                    cur = (self._x, self._y)
                    self._x_target, self._y_target = min(
                        valid,
                        key=lambda p: (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2)

            def paint():
                lv_raw = self._get_level()
                self._display_level += (lv_raw - self._display_level) * 0.4
                img = self._render_frame(self._frame, self._state,
                                         int(self._wcur), int(self._hcur))
                a = int(255 * self._alpha * float(self._theme["alpha"]))
                if _ulw_paint(hwnd_of(), img, int(self._x), int(self._y), a):
                    self._ulw_fails = 0
                else:
                    self._ulw_fails += 1
                    if self._ulw_fails >= 5 and self._ulw_ok:
                        self._ulw_ok = False
                        log.warning("per-pixel alpha unavailable — using fallback")
                        try:
                            root.attributes("-transparentcolor", _CHROMA)
                        except tk.TclError:
                            pass

            def draw_fallback():
                canvas.delete("all")
                if self._state == "hidden":
                    return
                t = self._theme
                w, h = self._dims()
                r = (h - 4) // 2

                def pl(x0, y0, x1, y1, fill):
                    canvas.create_oval(x0, y0, x0 + 2 * r, y1, fill=fill, outline=fill)
                    canvas.create_oval(x1 - 2 * r, y0, x1, y1, fill=fill, outline=fill)
                    canvas.create_rectangle(x0 + r, y0, x1 - r, y1,
                                            fill=fill, outline=fill)

                pl(0, 0, w - 2, h - 3, t["border"])
                pl(1, 1, w - 3, h - 4, _darken(t["bg"], 0.30))
                if self._state in ("listening", "locked"):
                    color = t["dot"] if self._state == "listening" else t["accent"]
                    dr = 4.5 * self._scale
                    canvas.create_oval(18 - dr, h / 2 - dr, 18 + dr, h / 2 + dr,
                                       fill=color, outline=color)
                    lv = max(0.0, min(1.0, self._display_level))
                    x0, x1 = int(34 * self._scale), w - int(48 * self._scale)
                    amp = (2.2 + 12.5 * lv) * self._scale
                    for si, c in enumerate(t.get("strings")
                                           or ["#ff5fa2", "#8b5cf6", "#00d4ff"]):
                        pts = []
                        for j in range(31):
                            u = j / 30
                            env = math.sin(math.pi * u)
                            y = h / 2 + env * (
                                amp * 0.72 * math.sin(9.4 * u + self._frame * 0.17 + si * 2.1)
                                + amp * 0.5 * math.sin(14.6 * u - self._frame * 0.11 - si * 1.4))
                            pts += [x0 + u * (x1 - x0), y]
                        canvas.create_line(*pts, fill=c, width=2, smooth=True,
                                           capstyle="round")

            def set_state(state: str):
                if state == self._state:
                    return
                self._state = state
                if state == "hidden":
                    self._alpha_target = 0.0
                    self._y_target = self._y + 8 * self._scale
                else:
                    entering = not self._visible
                    place(entering=entering)
                    if entering:
                        if self._ulw_ok:
                            self._alpha = 0.0
                        root.deiconify()
                        root.update_idletasks()
                        style_window()
                        if self._ulw_ok:
                            paint()
                        self._visible = True
                    self._alpha_target = 1.0

            def tick():
                self._frame += 1
                try:
                    while True:
                        cmd, arg = self._q.get_nowait()
                        if cmd == "show":
                            set_state(arg)
                        elif cmd == "hide":
                            set_state("hidden")
                        elif cmd == "theme":
                            self._theme = get_theme(arg, self._overrides)
                            self._base_key = None
                        elif cmd == "wave":
                            self._wave = arg
                        elif cmd == "bg":
                            self._bg = arg
                            self._base_key = None
                        elif cmd == "quit":
                            root.destroy()
                            return
                except queue.Empty:
                    pass

                if abs(self._alpha - self._alpha_target) > 0.01:
                    self._alpha += (self._alpha_target - self._alpha) * _EASE
                else:
                    self._alpha = self._alpha_target
                # easter egg curtain call: shrink back once the show is over
                if (self._egg is not None
                        and self._frame - self._egg["t0"] > self._EGG_DUR):
                    gp = self._egg_pad()
                    self._egg = None
                    self._y += gp
                    self._y_target += gp
                    self._hcur = float(self._dims()[1])
                    self._base_key = None

                if self._visible:
                    if (self._frame % 10 == 0 and not self._dragging
                            and self._egg is None
                            and self._state in ("listening", "locked")):
                        update_dodge()
                    if abs(self._y - self._y_target) > 0.5:
                        self._y += (self._y_target - self._y) * _EASE
                    if abs(self._x - self._x_target) > 0.5:
                        self._x += (self._x_target - self._x) * _EASE
                    # expand/collapse: ease the pill size toward its target
                    wt, ht = self._dims()
                    if abs(self._wcur - wt) > 1 or abs(self._hcur - ht) > 1:
                        self._wcur += (wt - self._wcur) * 0.38
                        self._hcur += (ht - self._hcur) * 0.38
                        root.geometry(f"{int(self._wcur)}x{int(self._hcur)}"
                                      f"+{int(self._x)}+{int(self._y)}")
                        canvas.configure(width=int(self._wcur),
                                         height=int(self._hcur))
                if (self._alpha <= 0.03 and self._alpha_target == 0.0
                        and self._visible):
                    root.withdraw()
                    self._visible = False

                if self._visible:
                    if self._ulw_ok:
                        paint()
                    else:
                        root.geometry(f"+{int(self._x)}+{int(self._y)}")
                        root.attributes(
                            "-alpha", self._alpha * float(self._theme["alpha"]))
                        draw_fallback()
                # 25fps while visible; 100ms idle ticks when hidden — the
                # keyboard hook shares our GIL, so rendering must stay light.
                root.after(40 if self._visible else 100, tick)

            place()
            style_window()
            tick()
            root.mainloop()
            # Finalize Tcl in THIS thread — otherwise Python's exit GC deletes it
            # from the main thread and Tcl aborts with "Tcl_AsyncDelete".
            del canvas, root
            import gc

            gc.collect()
        except Exception:  # noqa: BLE001 — overlay must never take the app down
            log.exception("overlay crashed — continuing without it")
            self.enabled = False
