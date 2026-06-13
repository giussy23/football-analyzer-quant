# Captura de pantallas de AlphaBet para el manual (uso interno, temporal).
# Arranca el mainloop real y captura la region de la ventana con GDI (BitBlt),
# encadenando la navegacion entre vistas con after().
import os, sys, time, ctypes
from ctypes import wintypes

# DPI-aware ANTES de crear ventanas (winfo_* y captura en px fisicos)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

sys.path.insert(0, r"D:\\")
import tkinter as tk
from PIL import Image
import football_analyzer.app as appmod

# Neutralizar arranques que tocan red/hilos (capturas limpias y deterministas)
for _m in ("_start_auto_audit_loop", "_start_quiniela_autoverify",
           "_start_combo_autosettle", "_start_wake_watchdog", "_try_maximize"):
    setattr(appmod.PremiumApp, _m, lambda self, *a, **k: None)

OUT = r"D:\football_analyzer\docs\manual_img"
os.makedirs(OUT, exist_ok=True)

# ── GDI screen capture (equivalente a .NET CopyFromScreen) ───────────────────
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def capture_region(x, y, w, h):
    SRCCOPY = 0x00CC0020
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h          # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")


# ── App ──────────────────────────────────────────────────────────────────────
app = appmod.PremiumApp()
app.update_idletasks()
# Ventana horizontal de diseno (apaisado) en posicion y tamano FIJOS.
W, H = 1600, 1000
PX, PY = 0, 0

def fix_geometry():
    try:
        app.state("normal")
    except Exception:
        pass
    try:
        app.resizable(False, False)
    except Exception:
        pass
    app.geometry("%dx%d+%d+%d" % (W, H, PX, PY))
    app.update_idletasks()

fix_geometry()
app.lift()
try:
    app.attributes("-topmost", True)
except Exception:
    pass
app.update_idletasks()


def find_canvas(widget):
    if isinstance(widget, tk.Canvas):
        return widget
    for ch in widget.winfo_children():
        r = find_canvas(ch)
        if r is not None:
            return r
    return None


def nav(method):
    def _a():
        try:
            getattr(app, method)()
        except Exception as e:
            print("NAV_ERR", method, e)
    return _a


def settings_scroll(frac):
    def _a():
        try:
            app.show_settings_view()
            c = find_canvas(app.settings_view)
            if c is not None:
                c.yview_moveto(frac)
        except Exception as e:
            print("SET_ERR", e)
    return _a


steps = [
    (nav("show_analysis_view"),    "01_trading_desk"),
    (nav("show_accumulator_view"), "03_combinadas_ia"),
    (nav("show_quiniela_view"),    "04_quiniela_ia"),
    (nav("show_alerts_view"),      "05_alertas"),
    (nav("show_results_view"),     "06_resultados"),
    (nav("show_live_view"),        "07_live_scores"),
    (nav("show_calendar_view"),    "08_calendario"),
    (nav("show_execution_view"),   "09_manual_slip"),
    (nav("show_portfolio_view"),   "10_portfolio"),
    (nav("show_performance_view"), "11_performance"),
    (nav("show_chat_view"),        "12_chat_ia"),
    (settings_scroll(0.0),         "02_config_1"),
    (settings_scroll(0.34),        "02_config_2"),
    (settings_scroll(0.70),        "02_config_3"),
    (settings_scroll(1.0),         "02_config_4"),
]

_idx = [0]


def do_step():
    if _idx[0] >= len(steps):
        teardown()
        return
    action, name = steps[_idx[0]]
    _idx[0] += 1
    action()
    fix_geometry()                     # re-aplicar tamano fijo tras navegar
    app.after(1000, lambda n=name: capture_and_next(n))


def capture_and_next(name):
    try:
        app.lift()
        app.update_idletasks(); app.update(); app.update_idletasks()
        # bbox FIJO y conocido (no dependemos de winfo, que la app altera)
        img = capture_region(PX, PY, W, H)
        img.save(os.path.join(OUT, name + ".png"))
        print("SAVED", name, (W, H))
    except Exception as e:
        print("CAP_ERR", name, e)
    app.after(150, do_step)


def teardown():
    try:
        app.attributes("-topmost", False)
    except Exception:
        pass
    try:
        app.destroy()
    except Exception:
        pass
    print("DONE")


app.after(1000, do_step)
app.mainloop()
