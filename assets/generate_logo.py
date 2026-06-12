#!/usr/bin/env python3
"""
generate_logo.py — Genera el logo SVG de AlphaBet v15.0.

Uso:
    py assets/generate_logo.py

Salida:
    assets/logo_alphabet.svg     ← logo principal (abre en Edge/Chrome)
    assets/logo_alphabet_sm.svg  ← versión pequeña 128x128 para app
    assets/favicon.svg           ← 64x64 solo el símbolo α

Solo usa módulos de la librería estándar (math, os).
"""

import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades geométricas
# ─────────────────────────────────────────────────────────────────────────────

def hex_pts(cx, cy, r, offset_angle=0):
    """Puntos SVG de un hexágono flat-top."""
    pts = []
    for i in range(6):
        a = math.radians(offset_angle + 60 * i)
        pts.append(f"{cx + r*math.cos(a):.1f},{cy + r*math.sin(a):.1f}")
    return " ".join(pts)


def hex_grid(center_x, center_y, clip_r, hex_r=20):
    """Genera posiciones (cx,cy) para una parrilla hex recortada a un círculo."""
    col_w = hex_r * 2
    row_h = hex_r * math.sqrt(3)
    n = int(clip_r / min(col_w, row_h)) + 2
    positions = []
    for row in range(-n, n + 1):
        for col in range(-n, n + 1):
            cx = col * col_w + (hex_r if row % 2 else 0)
            cy = row * row_h
            if math.hypot(cx, cy) <= clip_r - hex_r * 0.4:
                positions.append((center_x + cx, center_y + cy))
    return positions


def tick(cx, cy, r_in, r_out, angle_deg):
    a = math.radians(angle_deg)
    return (f'<line x1="{cx+r_in*math.cos(a):.1f}" y1="{cy+r_in*math.sin(a):.1f}" '
            f'x2="{cx+r_out*math.cos(a):.1f}" y2="{cy+r_out*math.sin(a):.1f}"/>')


def diamond(cx, cy, s=5):
    return (f'<polygon points="'
            f'{cx:.1f},{cy-s:.1f} {cx+s:.1f},{cy:.1f} '
            f'{cx:.1f},{cy+s:.1f} {cx-s:.1f},{cy:.1f}"/>')


def circle_pt(cx, cy, r, angle_deg, dot_r=2.5):
    a = math.radians(angle_deg)
    x, y = cx + r*math.cos(a), cy + r*math.sin(a)
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r}"/>'


# ─────────────────────────────────────────────────────────────────────────────
# Logo principal 400×400
# ─────────────────────────────────────────────────────────────────────────────

def make_svg_main():
    W, H, CX, CY = 400, 400, 200, 200
    R = 185   # outer ring radius

    # Hexagonal grid
    hexs = hex_grid(CX, CY, R - 8, hex_r=20)
    hex_el = "\n    ".join(
        f'<polygon points="{hex_pts(cx, cy, 19)}"/>'
        for cx, cy in hexs
    )

    # Tick marks
    major_t = "\n  ".join(tick(CX, CY, R-14, R-3, a) for a in [270, 0, 90, 180])
    minor_t = "\n  ".join(
        tick(CX, CY, R-9, R-3, a)
        for a in range(0, 360, 30) if a not in [270, 0, 90, 180]
    )

    # Cardinal diamonds
    diamonds = "\n  ".join(
        diamond(CX + R*math.cos(math.radians(a)),
                CY + R*math.sin(math.radians(a)), 5)
        for a in [270, 0, 90, 180]
    )

    # Orbit dots (large at 4 cardinal, small every 30°)
    orbit_main = "\n  ".join(circle_pt(CX, CY, 148, a, 2.5) for a in [270, 0, 90, 180])
    orbit_min  = "\n  ".join(circle_pt(CX, CY, 148, a, 1.2) for a in range(30, 360, 30)
                              if a not in [270, 0, 90, 180])

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  AlphaBet v15.0 — Logo revolucionario
  © 2026 Francesco Giuseppe Manolache
  Archivo: logo_alphabet.svg
-->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
  <!-- Fondo radial oscuro -->
  <radialGradient id="bg" cx="38%" cy="35%" r="78%">
    <stop offset="0%"   stop-color="#0e2016"/>
    <stop offset="60%"  stop-color="#060e09"/>
    <stop offset="100%" stop-color="#020604"/>
  </radialGradient>

  <!-- Gradiente principal azul→verde (símbolo α y texto) -->
  <linearGradient id="g1" x1="0%" y1="10%" x2="100%" y2="90%">
    <stop offset="0%"   stop-color="#38bdf8"/>
    <stop offset="40%"  stop-color="#34d399"/>
    <stop offset="100%" stop-color="#22c55e"/>
  </linearGradient>

  <!-- Gradiente inverso (verde→azul) para variedad -->
  <linearGradient id="g2" x1="100%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%"   stop-color="#22c55e"/>
    <stop offset="100%" stop-color="#38bdf8"/>
  </linearGradient>

  <!-- Gradiente para el anillo exterior -->
  <linearGradient id="rg" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%"   stop-color="#22c55e" stop-opacity="0.95"/>
    <stop offset="50%"  stop-color="#38bdf8" stop-opacity="0.65"/>
    <stop offset="100%" stop-color="#22c55e" stop-opacity="0.95"/>
  </linearGradient>

  <!-- Filtro: destello fuerte (para el símbolo α) -->
  <filter id="glow-xl" x="-100%" y="-100%" width="300%" height="300%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="14" result="b1"/>
    <feGaussianBlur in="SourceGraphic" stdDeviation="5"  result="b2"/>
    <feMerge>
      <feMergeNode in="b1"/>
      <feMergeNode in="b2"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>

  <!-- Filtro: destello suave (anillo, diamantes, puntos) -->
  <filter id="glow-sm" x="-25%" y="-25%" width="150%" height="150%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="b"/>
    <feMerge>
      <feMergeNode in="b"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>

  <!-- Filtro: resplandor del anillo -->
  <filter id="ring-glow" x="-8%" y="-8%" width="116%" height="116%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b"/>
    <feMerge>
      <feMergeNode in="b"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>

  <!-- Recorte circular -->
  <clipPath id="cc"><circle cx="{CX}" cy="{CY}" r="{R}"/></clipPath>
</defs>

<!-- ═══ FONDO ═══════════════════════════════════════════════════════════════ -->
<!-- Halo exterior verde muy suave -->
<circle cx="{CX}" cy="{CY}" r="197" fill="#22c55e" fill-opacity="0.05"/>
<!-- Fondo principal -->
<circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#bg)"/>

<!-- ═══ PARRILLA HEXAGONAL (referencia al balón de fútbol) ══════════════════ -->
<g clip-path="url(#cc)" fill="none" stroke="#22c55e" stroke-width="0.9" opacity="0.07">
  {hex_el}
</g>

<!-- ═══ ELEMENTOS DE PROFUNDIDAD ════════════════════════════════════════════ -->
<!-- Curva de rendimiento (chart) -->
<path d="M 52,308 C 90,292 128,272 162,250 S 210,218 232,200 S 278,168 320,146 S 356,130 348,128"
      fill="none" stroke="#22c55e" stroke-width="1.2" stroke-opacity="0.13"
      stroke-dasharray="3 9" clip-path="url(#cc)"/>

<!-- Elipse orbital (eje de análisis) -->
<ellipse cx="{CX}" cy="{CY}" rx="130" ry="40" fill="none"
         stroke="#38bdf8" stroke-width="0.8" stroke-opacity="0.16"
         transform="rotate(-20, {CX}, {CY})"/>

<!-- Anillo interior punteado -->
<circle cx="{CX}" cy="{CY}" r="148" fill="none"
        stroke="#22c55e" stroke-width="0.7" stroke-opacity="0.18"
        stroke-dasharray="3 11"/>

<!-- ═══ ANILLO EXTERIOR + MARCAS ════════════════════════════════════════════ -->
<!-- Anillo principal con resplandor -->
<circle cx="{CX}" cy="{CY}" r="{R}" fill="none"
        stroke="url(#rg)" stroke-width="2.8" filter="url(#ring-glow)"/>

<!-- Marcas principales (N/E/S/O) -->
<g stroke="#22c55e" stroke-width="2.8" stroke-opacity="0.9" filter="url(#glow-sm)">
  {major_t}
</g>
<!-- Marcas secundarias -->
<g stroke="#38bdf8" stroke-width="1.2" stroke-opacity="0.28">
  {minor_t}
</g>

<!-- Diamantes cardinales -->
<g fill="url(#g1)" filter="url(#glow-sm)" opacity="0.95">
  {diamonds}
</g>

<!-- Puntos orbitales -->
<g fill="#38bdf8" filter="url(#glow-sm)" opacity="0.9">
  {orbit_main}
</g>
<g fill="#34d399" opacity="0.3">
  {orbit_min}
</g>

<!-- ═══ SÍMBOLO α (elemento principal) ════════════════════════════════════ -->
<!-- Capa de destello exterior (gran blur verde) -->
<text x="{CX}" y="228"
      font-family="Georgia, 'Times New Roman', 'Palatino Linotype', serif"
      font-size="158" font-style="italic" font-weight="bold"
      fill="#22c55e" fill-opacity="0.18"
      text-anchor="middle" filter="url(#glow-xl)">α</text>

<!-- Símbolo α principal con gradiente -->
<text x="{CX}" y="228"
      font-family="Georgia, 'Times New Roman', 'Palatino Linotype', serif"
      font-size="158" font-style="italic" font-weight="bold"
      fill="url(#g1)" text-anchor="middle">α</text>

<!-- ═══ TIPOGRAFÍA ══════════════════════════════════════════════════════════ -->
<!-- Línea separadora -->
<line x1="118" y1="270" x2="282" y2="270"
      stroke="url(#rg)" stroke-width="0.9" stroke-opacity="0.5"/>

<!-- Nombre principal "AlphaBet" -->
<text x="{CX}" y="297"
      font-family="'Segoe UI', 'Helvetica Neue', 'Arial', sans-serif"
      font-size="27" font-weight="700"
      fill="url(#g1)" text-anchor="middle" letter-spacing="7">AlphaBet</text>

<!-- Subtítulo -->
<text x="{CX}" y="315"
      font-family="'Segoe UI', 'Helvetica Neue', 'Arial', sans-serif"
      font-size="8.5" font-weight="400"
      fill="#4ade80" fill-opacity="0.52" text-anchor="middle" letter-spacing="3.5">QUANT PRO  ·  v15.0</text>

<!-- Puntos decorativos datos -->
<g fill="#22c55e" opacity="0.55">
  <rect x="144" y="327" width="4" height="4" rx="1"/>
  <rect x="152" y="327" width="4" height="4" rx="1"/>
  <rect x="160" y="327" width="4" height="4" rx="1"/>
  <rect x="236" y="327" width="4" height="4" rx="1"/>
  <rect x="244" y="327" width="4" height="4" rx="1"/>
  <rect x="252" y="327" width="4" height="4" rx="1"/>
</g>

<!-- Borde exterior final muy sutil -->
<circle cx="{CX}" cy="{CY}" r="196" fill="none"
        stroke="#22c55e" stroke-width="0.4" stroke-opacity="0.25"/>
</svg>"""


# ─────────────────────────────────────────────────────────────────────────────
# Favicon 64×64
# ─────────────────────────────────────────────────────────────────────────────

def make_svg_favicon():
    return """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
<defs>
  <radialGradient id="bg" cx="40%" cy="35%" r="75%">
    <stop offset="0%" stop-color="#0e2016"/>
    <stop offset="100%" stop-color="#020604"/>
  </radialGradient>
  <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#38bdf8"/>
    <stop offset="100%" stop-color="#22c55e"/>
  </linearGradient>
  <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>
<circle cx="32" cy="32" r="31" fill="#22c55e" fill-opacity="0.06"/>
<circle cx="32" cy="32" r="30" fill="url(#bg)"/>
<circle cx="32" cy="32" r="30" fill="none" stroke="url(#g)" stroke-width="1.5" stroke-opacity="0.8"/>
<text x="32" y="44"
      font-family="Georgia, serif"
      font-size="38" font-style="italic" font-weight="bold"
      fill="url(#g)" text-anchor="middle" filter="url(#glow)">α</text>
</svg>"""


# ─────────────────────────────────────────────────────────────────────────────
# Versión horizontal 480×140 (para cabecera de app)
# ─────────────────────────────────────────────────────────────────────────────

def make_svg_banner():
    return """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 140" width="480" height="140">
<defs>
  <radialGradient id="bg" cx="30%" cy="50%" r="80%">
    <stop offset="0%" stop-color="#0d1f14"/>
    <stop offset="100%" stop-color="#030806"/>
  </radialGradient>
  <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#38bdf8"/>
    <stop offset="50%" stop-color="#34d399"/>
    <stop offset="100%" stop-color="#22c55e"/>
  </linearGradient>
  <filter id="glow-xl" x="-80%" y="-80%" width="260%" height="260%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="b1"/>
    <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b2"/>
    <feMerge><feMergeNode in="b1"/><feMergeNode in="b2"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="glow-sm" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <clipPath id="cc"><rect x="0" y="0" width="480" height="140" rx="16"/></clipPath>
</defs>

<rect x="0" y="0" width="480" height="140" rx="16" fill="url(#bg)"/>
<rect x="0" y="0" width="480" height="140" rx="16" fill="none"
      stroke="url(#g1)" stroke-width="1.5" stroke-opacity="0.6"/>

<!-- Hex grid sutil -->
<g clip-path="url(#cc)" fill="none" stroke="#22c55e" stroke-width="0.8" opacity="0.06">
  <polygon points="55,10 72,20 72,40 55,50 38,40 38,20"/>
  <polygon points="89,10 106,20 106,40 89,50 72,40 72,20"/>
  <polygon points="72,40 89,50 89,70 72,80 55,70 55,50"/>
  <polygon points="55,70 72,80 72,100 55,110 38,100 38,80"/>
  <polygon points="89,70 106,80 106,100 89,110 72,100 72,80"/>
  <polygon points="38,40 55,50 55,70 38,80 21,70 21,50"/>
  <polygon points="106,40 123,50 123,70 106,80 89,70 89,50"/>
</g>

<!-- Línea decorativa vertical separadora -->
<line x1="155" y1="20" x2="155" y2="120"
      stroke="#22c55e" stroke-width="0.8" stroke-opacity="0.25"
      stroke-dasharray="3 6"/>

<!-- Símbolo α -->
<text x="78" y="100"
      font-family="Georgia, serif"
      font-size="95" font-style="italic" font-weight="bold"
      fill="#22c55e" fill-opacity="0.15"
      text-anchor="middle" filter="url(#glow-xl)">α</text>
<text x="78" y="100"
      font-family="Georgia, serif"
      font-size="95" font-style="italic" font-weight="bold"
      fill="url(#g1)" text-anchor="middle">α</text>

<!-- "AlphaBet" nombre -->
<text x="318" y="75"
      font-family="'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
      font-size="42" font-weight="700"
      fill="url(#g1)" text-anchor="middle" letter-spacing="4">AlphaBet</text>

<!-- Línea separadora -->
<line x1="185" y1="85" x2="452" y2="85"
      stroke="url(#g1)" stroke-width="0.8" stroke-opacity="0.4"/>

<!-- Subtítulo -->
<text x="318" y="104"
      font-family="'Segoe UI', Arial, sans-serif"
      font-size="11" font-weight="400"
      fill="#4ade80" fill-opacity="0.55" text-anchor="middle" letter-spacing="3">QUANTITATIVE FOOTBALL ANALYSIS  ·  v15.0</text>

<!-- Puntos de datos -->
<g fill="#22c55e" filter="url(#glow-sm)" opacity="0.7">
  <circle cx="185" cy="38" r="2.5"/>
  <circle cx="452" cy="38" r="2.5"/>
  <circle cx="185" cy="120" r="2.5"/>
  <circle cx="452" cy="120" r="2.5"/>
</g>
</svg>"""


# ─────────────────────────────────────────────────────────────────────────────
# Guardar ficheros
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    files = {
        "logo_alphabet.svg":    make_svg_main(),
        "favicon.svg":          make_svg_favicon(),
        "logo_banner.svg":      make_svg_banner(),
    }

    for filename, content in files.items():
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[OK] {path}")

    print()
    print("Abre los .svg en Edge o Chrome para ver los logos.")
    print("Para convertir a PNG: instala Pillow (pip install Pillow cairosvg)")
    print("o abre el SVG en el navegador, clic derecho -> Guardar imagen.")


# ── Logo sidebar PNG (requiere Pillow) ────────────────────────────────────────

def generate_sidebar_logo(path: str, W: int = 210, H: int = 248) -> None:
    """
    Genera el logo del sidebar como PNG de alta calidad usando PIL.
    Fondo galáctico con nebulosas + campo estelar + α con glow de neón.
    """
    import random as _rnd
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    S  = 3                         # factor de supersampling
    SW, SH = W * S, H * S         # 630 × 744
    cx = SW // 2                   # 315
    cy = int(SH * 0.395)           # ~294 — centro del símbolo α

    # ═══ 1. Fondo espacio profundo ══════════════════════════════════════════
    img = Image.new("RGBA", (SW, SH), (4, 12, 24, 255))   # mismo fondo que sidebar #040c18

    # ═══ 2. Nubes de nebulosa / polvo galáctico ═════════════════════════════
    rng = _rnd.Random(7777)
    nebula_specs = [
        # (color_rgb,  n_blobs, max_r_px, max_alpha)
        ((4,  42, 62), 14, 155, 32),    # cyan oscuro difuso
        ((8,  72, 60),  9, 130, 25),    # teal medio
        ((14, 28, 72),  7, 110, 18),    # índigo profundo
        ((35,  8, 55),  4,  90, 12),    # violeta muy sutil
        (( 0, 55, 45), 11,  80, 20),    # teal-verde acento
    ]
    for (nr, ng, nb), n_blobs, max_r, max_a in nebula_specs:
        layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for _ in range(n_blobs):
            bx = rng.randint(-SW // 6, SW + SW // 6)
            by = rng.randint(-SH // 6, int(SH * 0.80))
            br = rng.randint(max_r // 2, max_r)
            ba = rng.randint(max_a // 2, max_a)
            rx = int(br * rng.uniform(0.55, 1.45))
            ry = int(br * rng.uniform(0.55, 1.45))
            ld.ellipse([bx - rx, by - ry, bx + rx, by + ry], fill=(nr, ng, nb, ba))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=38))
        img = Image.alpha_composite(img, layer)

    # Halo central alrededor de la α (núcleo de la nebulosa)
    core = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ImageDraw.Draw(core).ellipse(
        [cx - 140, cy - 120, cx + 140, cy + 120], fill=(6, 48, 52, 45))
    core = core.filter(ImageFilter.GaussianBlur(radius=55))
    img = Image.alpha_composite(img, core)

    # ═══ 3. Campo de estrellas ══════════════════════════════════════════════
    star_layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(star_layer)
    glow_l = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_l)

    rng2 = _rnd.Random(12345)
    for _ in range(540):
        sx = rng2.randint(0, SW)
        sy = rng2.randint(0, SH)
        rv = rng2.random()

        if rv > 0.978:                      # ── ultra-brillante con picos ──
            br = rng2.randint(230, 255)
            bl = rng2.randint(195, 255)
            sr = rng2.randint(2, 4)
            sd.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(br, br, bl, 255))
            spike = sr * 10
            sd.line([sx-spike, sy, sx+spike, sy], fill=(br, br, bl, 95), width=1)
            sd.line([sx, sy-spike, sx, sy+spike], fill=(br, br, bl, 95), width=1)
            gd.ellipse([sx-sr*8, sy-sr*8, sx+sr*8, sy+sr*8],
                       fill=(br//4, br//4, bl//3, 55))

        elif rv > 0.935:                    # ── brillante ──
            br = rng2.randint(190, 240)
            bl = rng2.randint(175, 255)
            sd.ellipse([sx-2, sy-2, sx+2, sy+2], fill=(br, br, bl, 255))
            gd.ellipse([sx-7, sy-7, sx+7, sy+7], fill=(br//4, br//4, bl//3, 45))

        elif rv > 0.76:                     # ── media, con tinte de color ──
            br = rng2.randint(140, 215)
            tint = rng2.random()
            if tint > 0.60:
                col = (br, br, min(255, br + 42))    # azul-blanca
            elif tint > 0.30:
                col = (min(255, br+20), min(255, br+32), min(255, br+52))
            else:
                col = (br, min(255, br+20), br)      # cálida tenue
            sd.point((sx, sy), fill=(*col, rng2.randint(185, 255)))

        else:                               # ── tenue ──
            br = rng2.randint(40, 155)
            sd.point((sx, sy), fill=(br, br, min(255, br+28),
                                     rng2.randint(100, 215)))

    glow_l = glow_l.filter(ImageFilter.GaussianBlur(radius=4))
    img = Image.alpha_composite(img, glow_l)
    img = Image.alpha_composite(img, star_layer)

    # ═══ 4. Arco espiral galáctico muy tenue ════════════════════════════════
    arc_l = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc_l)
    rng3 = _rnd.Random(3141)
    for i in range(220):
        theta = i * 0.11
        r_sp  = 22 + theta * 16
        spx   = int(cx + r_sp * math.cos(theta - 0.3))
        spy   = int(cy * 0.55 + r_sp * 0.32 * math.sin(theta - 0.3))
        if 0 <= spx < SW and 0 <= spy < SH:
            brightness = max(3, 18 - int(theta * 0.5))
            ad.point((spx, spy),
                     fill=(brightness, brightness * 2, brightness * 3, brightness * 3))
    arc_l = arc_l.filter(ImageFilter.GaussianBlur(radius=5))
    img = Image.alpha_composite(img, arc_l)

    # ═══ 5. Símbolo α — glow de neón multicapa ══════════════════════════════
    fs = 360
    try:
        fnt = ImageFont.truetype("C:\\Windows\\Fonts\\georgiaz.ttf", fs)
    except OSError:
        fnt = ImageFont.load_default()

    glow_specs = [
        (( 4,  90,  70,  38), 54),   # niebla teal exterior
        ((10, 130,  90,  62), 28),   # teal medio
        ((30, 185, 128,  95), 13),   # teal-verde cerca
        ((52, 211, 153, 135),  6),   # teal nítido
        ((90, 225, 195,  75),  3),   # cyan highlight
    ]
    for (r, g, b, a), blur_r in glow_specs:
        layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((cx, cy), "α", font=fnt,
                                   fill=(r, g, b, a), anchor="mm")
        layer = layer.filter(ImageFilter.GaussianBlur(radius=blur_r))
        img = Image.alpha_composite(img, layer)

    sharp = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ImageDraw.Draw(sharp).text((cx, cy), "α", font=fnt,
                               fill=(52, 211, 153, 255), anchor="mm")
    img = Image.alpha_composite(img, sharp)

    # ═══ 6. Tipografía ══════════════════════════════════════════════════════
    ty = cy + int(fs * 0.56)
    try:
        fnt_name  = ImageFont.truetype("C:\\Windows\\Fonts\\segoeuib.ttf", 44 * S)
        fnt_badge = ImageFont.truetype("C:\\Windows\\Fonts\\segoeui.ttf",  22 * S)
    except OSError:
        fnt_name = fnt_badge = ImageFont.load_default()

    for lyr_fill, blur_r in [((52, 211, 153, 72), 9), ((52, 211, 153, 255), 0)]:
        txt_layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
        ImageDraw.Draw(txt_layer).text((cx, ty), "AlphaBet",
                                       font=fnt_name, fill=lyr_fill, anchor="mm")
        if blur_r:
            txt_layer = txt_layer.filter(ImageFilter.GaussianBlur(radius=blur_r))
        img = Image.alpha_composite(img, txt_layer)

    badge = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ImageDraw.Draw(badge).text(
        (cx, ty + 54 * S), "v15  ·  Quant Pro",
        font=fnt_badge, fill=(58, 115, 85, 200), anchor="mm"
    )
    img = Image.alpha_composite(img, badge)

    # ═══ 7. Downscale 3× → 1× con anti-aliasing ════════════════════════════
    result = img.convert("RGB").resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    result.save(path, "PNG")


# (generate_galaxy_bg eliminada: el fondo galáctico de la ventana se retiró;
#  el logo del sidebar sigue usando generate_sidebar_logo más arriba.)
