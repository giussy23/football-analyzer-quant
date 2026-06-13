# -*- coding: utf-8 -*-
"""Genera mockups de diseño (PNG) para AlphaBet — solo presentación, no se aplican."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

F = "C:/Windows/Fonts/"
def font(name, sz):
    return ImageFont.truetype(F + name, sz)

REG  = lambda s: font("segoeui.ttf", s)
BOLD = lambda s: font("segoeuib.ttf", s)
SEMI = lambda s: font("seguisb.ttf", s)
LIGHT= lambda s: font("segoeuil.ttf", s)
MONO = lambda s: font("consola.ttf", s)
MONOB= lambda s: font("consolab.ttf", s)

def hx(c):
    c = c.lstrip("#"); return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))

def vgrad(w, h, top, bot):
    t = np.array(hx(top), float); b = np.array(hx(bot), float)
    ys = np.linspace(0, 1, h)[:, None, None]
    arr = (t[None, None, :] * (1 - ys) + b[None, None, :] * ys)
    return np.tile(arr, (1, w, 1)).astype("uint8")

def glow(arr, cx, cy, rx, ry, col, strength):
    h, w, _ = arr.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    g = np.exp(-(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2))
    out = arr.astype(float) + g[..., None] * np.array(hx(col), float)[None, None, :] * strength
    return np.clip(out, 0, 255).astype("uint8")

def text(d, xy, s, fnt, fill, anchor="la"):
    d.text(xy, s, font=fnt, fill=fill, anchor=anchor)

def panel(d, box, fill=None, outline=None, radius=14, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


# ════════════════════════════════════════════════════════════════════════════
# MOCKUP 1 — QUANT TERMINAL  (data-first, denso, estilo Bloomberg)
# ════════════════════════════════════════════════════════════════════════════
def quant_terminal():
    W, H = 1200, 760
    bg = vgrad(W, H, "#0a0e14", "#070a10")
    img = Image.fromarray(bg); d = ImageDraw.Draw(img, "RGBA")
    ACC, AMB, RED, MUT, TXT = "#14e08a", "#ffb020", "#ff5a5a", "#5a6b7a", "#e6eef5"
    SB = "#0c1118"

    # Sidebar
    d.rectangle([0, 0, 188, H], fill=hx(SB))
    d.line([188, 0, 188, H], fill=hx("#16202c"), width=1)
    text(d, (24, 30), "α", BOLD(30), hx(ACC))
    text(d, (60, 34), "ALPHABET", SEMI(17), hx(TXT))
    text(d, (61, 58), "QUANT TERMINAL", REG(10), hx(MUT))
    nav = [("Trading desk", True), ("Combinadas", False), ("Quiniela", False),
           ("Mercado", False), ("Performance", False), ("Scanner", False),
           ("Alertas", False), ("Settings", False)]
    y = 110
    for name, active in nav:
        if active:
            d.rectangle([0, y - 6, 188, y + 22], fill=hx("#0f1f1a"))
            d.rectangle([0, y - 6, 3, y + 22], fill=hx(ACC))
        text(d, (24, y), name, SEMI(13) if active else REG(13),
             hx(ACC) if active else hx("#7e90a0"))
        y += 40
    # status dot
    d.ellipse([24, H-40, 32, H-32], fill=hx(ACC))
    text(d, (40, H-44), "LIVE · 6 ligas", MONO(11), hx(MUT))

    x0 = 188
    # Top ticker bar
    d.rectangle([x0, 0, W, 34], fill=hx("#0b1018"))
    d.line([x0, 34, W, 34], fill=hx("#16202c"), width=1)
    tick = "BANKROLL 1,000€   ·   ROI +6.4%   ·   CLV +2.1%   ·   PICKS HOY 7   ·   STREAK +3W   ·   SHARPE 1.82"
    text(d, (x0 + 18, 10), tick, MONO(12), hx("#8fa3b3"))

    # Header
    text(d, (x0 + 24, 54), "Trading Desk", LIGHT(30), hx(TXT))
    text(d, (x0 + 26, 92), "Picks de valor · edge vs mercado · ranking por liga", REG(12), hx(MUT))
    panel(d, [W-150, 58, W-24, 92], outline=hx("#1c2a38"), radius=8)
    text(d, (W-87, 75), "▶  Run Analysis", SEMI(12), hx(ACC), anchor="mm")

    # KPI strip (8 compactas)
    kpis = [("PARTIDOS", "126", TXT), ("PICKS", "7", ACC), ("EDGE MED.", "+4.1%", ACC),
            ("CLV", "+2.1%", ACC), ("ROI OOS", "+6.4%", ACC), ("WIN%", "54.3%", AMB),
            ("DRAWDN", "-3.2%", RED), ("KELLY", "1.4%", TXT)]
    kx, kw = x0 + 24, 120
    for lbl, val, col in kpis:
        panel(d, [kx, 116, kx + kw - 8, 168], fill=hx("#0c131c"), outline=hx("#15202c"), radius=8)
        text(d, (kx + 12, 126), lbl, REG(10), hx(MUT))
        text(d, (kx + 12, 140), val, MONOB(18), hx(col))
        kx += kw

    # Picks table (denso, monospace)
    ty = 188
    panel(d, [x0 + 24, ty, W - 24, H - 24], fill=hx("#0a0f16"), outline=hx("#15202c"), radius=10)
    cols = [("PARTIDO", x0+44, "l"), ("PICK", x0+300, "c"), ("CUOTA", x0+370, "c"),
            ("EDGE", x0+450, "c"), ("P.MOD", x0+530, "c"), ("CLV", x0+610, "c"),
            ("EV", x0+685, "c"), ("KELLY", x0+760, "c"), ("SEÑAL", x0+860, "c")]
    d.line([x0+40, ty+38, W-40, ty+38], fill=hx("#16202c"), width=1)
    for name, cx, al in cols:
        text(d, (cx, ty+18), name, SEMI(11), hx("#6f8295"), anchor="lm" if al=="l" else "mm")
    rows = [
        ("Man City  v  Arsenal",      "1",  "1.85", "+5.2%", "59%", "+3.1%", "+0.09", "1.8%", ACC, "VERDE"),
        ("Real Madrid  v  Girona",    "1",  "1.62", "+4.0%", "64%", "+1.4%", "+0.04", "1.2%", ACC, "VERDE"),
        ("Inter  v  Napoli",          "X",  "3.40", "+6.1%", "31%", "+2.0%", "+0.08", "1.5%", AMB, "ÁMBAR"),
        ("Bayern  v  Leipzig",        "O2.5","1.72","+3.8%", "61%", "+1.1%", "+0.05", "1.0%", ACC, "VERDE"),
        ("PSG  v  Marseille",         "1",  "1.55", "+2.9%", "67%", "-0.2%", "+0.03", "0.8%", AMB, "ÁMBAR"),
        ("Liverpool  v  Chelsea",     "2",  "3.10", "+7.4%", "36%", "+2.8%", "+0.11", "1.9%", ACC, "VERDE"),
        ("Atlético  v  Sevilla",      "1",  "1.78", "+1.2%", "58%", "+0.3%", "+0.01", "0.4%", RED, "ROJO"),
    ]
    ry = ty + 52
    for partido, pick, cuota, edge, pmod, clv, ev, kelly, scol, signal in rows:
        if (ry // 34) % 2 == 0:
            d.rectangle([x0+30, ry-10, W-40, ry+18], fill=hx("#0c131c"))
        text(d, (x0+44, ry), partido, REG(12), hx(TXT), anchor="lm")
        text(d, (x0+300, ry), pick, MONOB(13), hx(ACC), anchor="mm")
        text(d, (x0+370, ry), cuota, MONO(12), hx(TXT), anchor="mm")
        text(d, (x0+450, ry), edge, MONO(12), hx(scol), anchor="mm")
        text(d, (x0+530, ry), pmod, MONO(12), hx("#9fb0c0"), anchor="mm")
        text(d, (x0+610, ry), clv, MONO(12), hx(scol), anchor="mm")
        text(d, (x0+685, ry), ev, MONO(12), hx("#9fb0c0"), anchor="mm")
        text(d, (x0+760, ry), kelly, MONO(12), hx("#9fb0c0"), anchor="mm")
        # signal pill
        d.rounded_rectangle([x0+820, ry-9, x0+900, ry+9], radius=9, fill=hx(scol)+(38,))
        text(d, (x0+860, ry), signal, SEMI(10), hx(scol), anchor="mm")
        ry += 40

    img.save("/tmp/mock_quant.png")
    print("quant terminal OK")


# ════════════════════════════════════════════════════════════════════════════
# MOCKUP 2 — AURORA GLASS  (premium fintech, espacioso, elegante)
# ════════════════════════════════════════════════════════════════════════════
def aurora_glass():
    W, H = 1200, 760
    bg = vgrad(W, H, "#0c0a1c", "#08070f")
    bg = glow(bg, 760, -40, 520, 280, "#5b46c9", 0.55)
    bg = glow(bg, 1050, 20, 360, 240, "#2bb6c9", 0.40)
    img = Image.fromarray(bg); d = ImageDraw.Draw(img, "RGBA")
    VIO, CYA, MUT, TXT, GREEN, RED = "#a78bfa", "#4de3c8", "#7d78a8", "#eef0ff", "#46d39a", "#f87171"

    # Sidebar glass
    d.rounded_rectangle([16, 16, 210, H-16], radius=20, fill=(255,255,255,8), outline=(167,139,250,40), width=1)
    text(d, (44, 44), "α", BOLD(34), hx(VIO))
    text(d, (84, 50), "AlphaBet", SEMI(18), hx(TXT))
    text(d, (85, 76), "Quant Pro", REG(11), hx(MUT))
    nav = [("Trading desk", True), ("Combinadas", False), ("Quiniela", False),
           ("Mercado", False), ("Performance", False), ("Alertas", False),
           ("Chat IA", False), ("Settings", False)]
    y = 130
    for name, active in nav:
        if active:
            d.rounded_rectangle([28, y-8, 198, y+24], radius=10, fill=(167,139,250,30))
        text(d, (48, y), name, SEMI(13) if active else REG(13),
             hx(VIO) if active else hx("#9a95c0"))
        y += 44
    d.rounded_rectangle([28, H-72, 198, H-30], radius=12, fill=(124,92,255,55))
    text(d, (113, H-51), "Run Analysis", SEMI(13), hx("#ffffff"), anchor="mm")

    x0 = 210
    # Header hero con resplandor
    text(d, (x0+40, 44), "Performance", LIGHT(34), hx(TXT))
    text(d, (x0+42, 86), "Equity, calibración del modelo y CLV por liga", REG(13), hx("#9a95c0"))

    # KPI cards grandes (4)
    kpis = [("Picks rastreados", "248", "+12 esta semana", VIO),
            ("Win rate", "54.3%", "de 248 liquidados", GREEN),
            ("ROI acumulado", "+6.4%", "sobre stakes", GREEN),
            ("CLV medio", "+2.1%", "ventaja de cierre", CYA)]
    cx = x0 + 40; cw = 218
    for lbl, val, sub, col in kpis:
        d.rounded_rectangle([cx, 128, cx+cw-16, 226], radius=16, fill=(255,255,255,10), outline=(255,255,255,22), width=1)
        d.rounded_rectangle([cx, 128, cx+4, 226], radius=2, fill=hx(col))
        text(d, (cx+20, 146), lbl, REG(12), hx(MUT))
        text(d, (cx+20, 166), val, SEMI(30), hx(col))
        text(d, (cx+20, 204), sub, REG(11), hx("#8782ad"))
        cx += cw

    # Equity curve card (grande)
    ex0, ey0, ex1, ey1 = x0+40, 248, W-40, 500
    d.rounded_rectangle([ex0, ey0, ex1, ey1], radius=18, fill=(255,255,255,8), outline=(255,255,255,20), width=1)
    text(d, (ex0+24, ey0+18), "Curva de equity", SEMI(15), hx(TXT))
    text(d, (ex1-24, ey0+20), "+312€", SEMI(15), hx(GREEN), anchor="ra")
    # plot
    px0, py0, px1, py1 = ex0+30, ey0+56, ex1-30, ey1-28
    pts = [0,18,12,35,30,44,40,62,75,70,95,120,140,128,168,182,210,205,250,255]
    n = len(pts)//2
    rng = np.random.default_rng(3)
    ys = np.cumsum(rng.normal(0.6,1.0,46)); ys = ys - ys.min(); ys = ys/ys.max()
    xs = np.linspace(px0, px1, len(ys))
    yy = py1 - ys*(py1-py0)
    line = list(zip(xs.tolist(), yy.tolist()))
    # area fill
    d.polygon(line + [(px1, py1), (px0, py1)], fill=(70,211,154,26))
    d.line(line, fill=hx(GREEN), width=3, joint="curve")
    for gx in np.linspace(px0, px1, 6):
        d.line([gx, py0, gx, py1], fill=(255,255,255,10), width=1)

    # Mini cards inferiores (3)
    minis = [("Sharpe ratio", "1.82", "excelente", GREEN),
             ("Max drawdown", "-3.2%", "controlado", CYA),
             ("Racha actual", "+3W", "en racha", GREEN)]
    mx = x0+40; mw = (W-40 - (x0+40) - 32)//3
    for lbl, val, sub, col in minis:
        d.rounded_rectangle([mx, 516, mx+mw-16, 600], radius=14, fill=(255,255,255,8), outline=(255,255,255,18), width=1)
        text(d, (mx+18, 532), lbl, REG(12), hx(MUT))
        text(d, (mx+18, 552), val, SEMI(24), hx(col))
        text(d, (mx+18, 584), sub, REG(11), hx("#8782ad"))
        mx += mw

    # Footer pick destacado
    d.rounded_rectangle([x0+40, 616, W-40, H-24], radius=14, fill=(124,92,255,22), outline=(167,139,250,55), width=1)
    text(d, (x0+62, 632), "PICK DESTACADO", REG(11), hx(VIO))
    text(d, (x0+62, 650), "Liverpool  v  Chelsea  —  2  @ 3.10", SEMI(16), hx(TXT))
    text(d, (x0+64, 678), "edge +7.4% · CLV +2.8% · Kelly 1.9% · señal VERDE", REG(12), hx("#9a95c0"))
    d.rounded_rectangle([W-180, 636, W-60, 692], radius=12, fill=hx(GREEN)+(40,))
    text(d, (W-120, 664), "Apostar", SEMI(14), hx(GREEN), anchor="mm")

    img.save("/tmp/mock_aurora.png")
    print("aurora glass OK")


# ════════════════════════════════════════════════════════════════════════════
# MOCKUP 3 — SPORTSBOOK PRO  (visual, cards de partidos, vibrante)
# ════════════════════════════════════════════════════════════════════════════
def sportsbook():
    W, H = 1200, 760
    bg = vgrad(W, H, "#0f1626", "#0a0f1a")
    img = Image.fromarray(bg); d = ImageDraw.Draw(img, "RGBA")
    GRN, ORA, BLU, MUT, TXT, CARD = "#21d07a", "#ff8a3d", "#3d8bff", "#6b7a92", "#eaf1fb", "#141d30"

    # Sidebar
    d.rectangle([0, 0, 196, H], fill=hx("#0c1322"))
    d.ellipse([24, 28, 60, 64], outline=hx(GRN), width=2)
    text(d, (42, 46), "α", BOLD(22), hx(GRN), anchor="mm")
    text(d, (72, 34), "AlphaBet", SEMI(17), hx(TXT))
    text(d, (73, 57), "Sportsbook", REG(11), hx(MUT))
    nav = [("ti", "Trading desk", True), ("", "Partidos hoy", False), ("", "Combinadas", False),
           ("", "Quiniela", False), ("", "En vivo", False), ("", "Performance", False),
           ("", "Mi cartera", False), ("", "Ajustes", False)]
    y = 110
    for _, name, active in nav:
        if active:
            d.rectangle([0, y-7, 196, y+23], fill=hx("#10233a"))
            d.rectangle([0, y-7, 4, y+23], fill=hx(GRN))
        text(d, (28, y), name, SEMI(13) if active else REG(13),
             hx(GRN) if active else hx("#8294ab"))
        y += 42

    x0 = 196
    text(d, (x0+28, 34), "Partidos de hoy", LIGHT(30), hx(TXT))
    text(d, (x0+30, 72), "12 partidos · 7 picks de valor detectados", REG(13), hx(MUT))
    # filtro chips
    chips = [("Todos", True), ("Premier", False), ("La Liga", False), ("Valor +", False)]
    chx = W-360
    for name, on in chips:
        w = 12 + len(name)*8
        d.rounded_rectangle([chx, 44, chx+w, 72], radius=14,
                            fill=hx(GRN)+(40,) if on else None, outline=hx("#22324a"), width=1)
        text(d, (chx+w//2, 58), name, SEMI(11), hx(GRN) if on else hx(MUT), anchor="mm")
        chx += w + 10

    # Match cards (grid 2 columnas)
    matches = [
        ("PREMIER LEAGUE · 18:30", "Manchester City", "Arsenal", "1.85","3.60","4.20", 0, "+5.2%", 0.74),
        ("LA LIGA · 21:00", "Real Madrid", "Girona", "1.62","3.90","5.50", 0, "+4.0%", 0.81),
        ("SERIE A · 20:45", "Inter", "Napoli", "2.10","3.20","3.50", 1, "+6.1%", 0.58),
        ("BUNDESLIGA · 18:30", "Bayern", "Leipzig", "1.72","4.00","4.50", 2, "+3.8%", 0.66),
    ]
    cardw, cardh, gap = 462, 196, 24
    positions = [(x0+28, 96), (x0+28+cardw+gap, 96),
                 (x0+28, 96+cardh+gap), (x0+28+cardw+gap, 96+cardh+gap)]
    odds_lbl = ["1", "X", "2"]
    for (mx, my), (league, home, away, o1, ox, o2, pickidx, edge, conf) in zip(positions, matches):
        d.rounded_rectangle([mx, my, mx+cardw, my+cardh], radius=16, fill=hx(CARD), outline=hx("#1d2b42"), width=1)
        text(d, (mx+22, my+18), league, SEMI(10), hx("#5f7characteristic".replace("characteristic","a90")[:7]) if False else hx("#6f82a0"))
        # edge badge
        d.rounded_rectangle([mx+cardw-92, my+14, mx+cardw-18, my+38], radius=12, fill=hx(GRN)+(40,))
        text(d, (mx+cardw-55, my+26), "VALOR "+edge, SEMI(10), hx(GRN), anchor="mm")
        # teams
        text(d, (mx+22, my+48), home, SEMI(19), hx(TXT))
        text(d, (mx+22, my+78), away, SEMI(19), hx("#b9c6d8"))
        text(d, (mx+cardw-30, my+58), "vs", REG(13), hx(MUT), anchor="ra")
        # odds buttons
        odds = [o1, ox, o2]
        bx = mx+22; bw = (cardw-44-16)//3
        for i, (lab, od) in enumerate(zip(odds_lbl, odds)):
            sel = (i == pickidx)
            d.rounded_rectangle([bx, my+112, bx+bw, my+156], radius=12,
                                fill=hx(GRN)+(45,) if sel else hx("#0e1726"),
                                outline=hx(GRN) if sel else hx("#26344c"), width=2 if sel else 1)
            text(d, (bx+bw//2, my+124), lab, REG(11), hx(GRN) if sel else hx(MUT), anchor="mm")
            text(d, (bx+bw//2, my+142), od, SEMI(16), hx(GRN) if sel else hx(TXT), anchor="mm")
            bx += bw + 8
        # confidence bar
        text(d, (mx+22, my+166), "Confianza del modelo", REG(10), hx(MUT))
        d.rounded_rectangle([mx+150, my+170, mx+cardw-22, my+178], radius=4, fill=hx("#1b2740"))
        d.rounded_rectangle([mx+150, my+170, mx+150+int((cardw-172)*conf), my+178], radius=4, fill=hx(GRN))

    img.save("/tmp/mock_sportsbook.png")
    print("sportsbook OK")


quant_terminal()
aurora_glass()
sportsbook()
print("DONE")
