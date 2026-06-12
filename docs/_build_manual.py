# -*- coding: utf-8 -*-
"""Genera el Manual de Usuario de AlphaBet v15.0 en PDF (con capturas)."""
import os
import logging
logging.getLogger("fontTools").setLevel(logging.CRITICAL)
logging.getLogger("fontTools.subset").setLevel(logging.CRITICAL)
logging.getLogger("fontTools.ttLib").setLevel(logging.CRITICAL)
from PIL import Image
from fpdf import FPDF

BASE = r"D:\football_analyzer"
IMG = os.path.join(BASE, "docs", "manual_img")
PDFIMG = os.path.join(BASE, "docs", "_pdfimg")
OUT = os.path.join(BASE, "AlphaBet_Manual_v15.pdf")
os.makedirs(PDFIMG, exist_ok=True)

FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
F_REG = os.path.join(FONTS, "segoeui.ttf")
F_BLD = os.path.join(FONTS, "segoeuib.ttf")
F_SB = os.path.join(FONTS, "seguisb.ttf")
F_LT = os.path.join(FONTS, "segoeuisl.ttf")

# Paleta
NAVY = (10, 16, 28)
NAVY2 = (16, 26, 44)
ACCENT = (34, 211, 238)     # cian
GREEN = (34, 197, 94)
INK = (33, 41, 54)
MUTED = (120, 130, 145)
LIGHT = (210, 216, 224)
WHITE = (240, 245, 250)

# ── Preparar logo (recorte del sidebar) ──────────────────────────────────────
shot = Image.open(os.path.join(IMG, "01_trading_desk.png")).convert("RGB")
logo_img = shot.crop((50, 66, 466, 396))  # logo sin la linea divisoria inferior
LOGO = os.path.join(PDFIMG, "_logo.png")
logo_img.save(LOGO)
# Fondo de portada = pixel mas oscuro del fondo del logo (fusion perfecta)
_smp = [logo_img.getpixel((x, y)) for x in (3, 10, 18) for y in (3, 10, 18, 300, 320)]
NAVY = min(_smp, key=lambda c: sum(c))


def prep(name):
    """Reescala una captura a 1280px de ancho para aligerar el PDF."""
    src = os.path.join(IMG, name + ".png")
    dst = os.path.join(PDFIMG, name + ".jpg")
    im = Image.open(src).convert("RGB")
    if im.width > 1280:
        im = im.resize((1280, round(1280 * im.height / im.width)), Image.LANCZOS)
    im.save(dst, quality=88)
    return dst


class Manual(FPDF):
    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_draw_color(*LIGHT)
        self.line(self.l_margin, self.get_y(), 210 - self.r_margin, self.get_y())
        self.set_y(-12)
        self.set_font("SUI", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, "AlphaBet v15.0  ·  Manual de Usuario", align="L")
        self.set_x(self.l_margin)
        self.cell(210 - self.l_margin - self.r_margin, 6,
                  "Página %d" % (self.page_no() - 1), align="R")


pdf = Manual(orientation="P", unit="mm", format="A4")
pdf.set_margins(16, 16, 16)
pdf.set_auto_page_break(True, margin=18)
pdf.add_font("SUI", "", F_REG)
pdf.add_font("SUI", "B", F_BLD)
pdf.add_font("SUISB", "", F_SB)
pdf.add_font("SUIL", "", F_LT)

PW = 210 - 32   # ancho util (178)


def p(text, h=5.7, size=10.5, color=INK, gap=2.2):
    pdf.set_font("SUI", "", size)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, h, text, align="J")
    pdf.ln(gap)


def h2(text):
    pdf.ln(1)
    pdf.set_font("SUISB", "", 12.5)
    pdf.set_text_color(*[int(c * 0.55) for c in ACCENT])
    pdf.multi_cell(0, 6.5, text)
    pdf.ln(1.2)


def bullets(items, size=10.5):
    for it in items:
        if pdf.get_y() > 297 - 24:
            pdf.add_page()
        y0 = pdf.get_y()
        pdf.set_font("SUI", "B", size)
        pdf.set_text_color(*GREEN)
        pdf.set_x(18)
        pdf.cell(5, 5.6, "•")
        pdf.set_font("SUI", "", size)
        pdf.set_text_color(*INK)
        pdf.set_xy(24, y0)
        pdf.multi_cell(PW - 8, 5.6, it, align="L")
        pdf.ln(0.8)
    pdf.ln(1.5)


def image_full(name, caption="", w=PW):
    dst = prep(name)
    im = Image.open(dst)
    h = w * im.height / im.width
    if pdf.get_y() + h + 9 > 297 - 18:
        pdf.add_page()
    x = pdf.l_margin
    y = pdf.get_y() + 1
    pdf.image(dst, x=x, y=y, w=w)
    pdf.set_draw_color(*LIGHT)
    pdf.set_line_width(0.3)
    pdf.rect(x, y, w, h)
    pdf.set_y(y + h + 1.5)
    if caption:
        pdf.set_font("SUI", "", 8.6)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 4.5, caption, align="C")
    pdf.ln(3)


_chap = [0]


def h1(title):
    pdf.add_page()
    _chap[0] += 1
    y0 = pdf.get_y()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(16, y0 + 0.5, 5, 11, "F")
    pdf.set_xy(24, y0)
    pdf.set_font("SUI", "B", 19)
    pdf.set_text_color(*NAVY2)
    pdf.cell(0, 12, "%d.  %s" % (_chap[0], title))
    pdf.ln(15)
    pdf.set_draw_color(*LIGHT)
    pdf.set_line_width(0.4)
    pdf.line(16, pdf.get_y(), 194, pdf.get_y())
    pdf.ln(4)


# ── PORTADA ──────────────────────────────────────────────────────────────────
pdf.add_page()
pdf.set_fill_color(*NAVY)
pdf.rect(0, 0, 210, 297, "F")
# franja de acento superior
pdf.set_fill_color(*ACCENT)
pdf.rect(0, 0, 210, 3, "F")
pdf.set_fill_color(*GREEN)
pdf.rect(0, 3, 210, 1, "F")
# logo
lim = Image.open(LOGO)
lw = 78
lh = lw * lim.height / lim.width
pdf.image(LOGO, x=(210 - lw) / 2, y=34, w=lw)
# título
pdf.set_xy(0, 34 + lh + 10)
pdf.set_font("SUI", "B", 34)
pdf.set_text_color(*WHITE)
pdf.cell(210, 16, "Manual de Usuario", align="C")
pdf.ln(17)
pdf.set_font("SUIL", "", 16)
pdf.set_text_color(*ACCENT)
pdf.cell(210, 9, "AlphaBet v15.0  ·  Quant Pro", align="C")
pdf.ln(13)
pdf.set_font("SUI", "", 11.5)
pdf.set_text_color(*LIGHT)
pdf.cell(210, 7, "Análisis cuantitativo de fútbol · Picks, combinadas IA y gestión de banca",
         align="C")
# pie de portada
pdf.set_xy(0, 268)
pdf.set_font("SUI", "", 9.5)
pdf.set_text_color(*MUTED)
pdf.cell(210, 5, "© 2026 Francesco Giuseppe Manolache · Todos los derechos reservados", align="C")
pdf.ln(5)
pdf.cell(210, 5, "Edición junio 2026 · Software de uso privado", align="C")

# ── ÍNDICE ───────────────────────────────────────────────────────────────────
pdf.add_page()
pdf.set_font("SUI", "B", 22)
pdf.set_text_color(*NAVY2)
pdf.cell(0, 14, "Contenido")
pdf.ln(18)
toc = [
    "¿Qué es AlphaBet?",
    "Instalación y primer arranque",
    "Trading Desk — la pantalla principal",
    "Configuración (Strategy)",
    "Combinadas IA",
    "Quiniela IA",
    "Alertas y monitor de líneas",
    "Resultados",
    "Live Scores",
    "Calendario",
    "Manual Slip (simulador)",
    "Portfolio",
    "Performance",
    "Chat IA",
    "Flujo de trabajo recomendado",
    "Preguntas frecuentes",
    "Juego responsable y aviso legal",
]
for i, t in enumerate(toc, 1):
    pdf.set_font("SUI", "B", 11.5)
    pdf.set_text_color(*ACCENT)
    pdf.cell(10, 8, "%02d" % i)
    pdf.set_font("SUI", "", 12)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, "   " + t)
    pdf.ln(8.6)

# ── 1. QUÉ ES ────────────────────────────────────────────────────────────────
h1("¿Qué es AlphaBet?")
p("AlphaBet es tu analista cuantitativo de fútbol en el escritorio. Reúne en una sola "
  "aplicación todo lo que necesitas para detectar valor en las apuestas: un modelo de "
  "Machine Learning combinado con Poisson y consenso de múltiples casas, generación de "
  "combinadas inteligentes, control de banca con criterio profesional y un seguimiento "
  "honesto de tus resultados.")
p("No es una bola de cristal: es una herramienta de decisión. AlphaBet calcula la "
  "probabilidad real de cada resultado, la compara con la cuota del mercado y solo te "
  "señala las jugadas donde existe ventaja estadística (valor esperado positivo). Tú "
  "mantienes siempre el control; la app te da la información para decidir mejor.")
h2("Lo que hace por ti")
bullets([
    "Calcula picks con ventaja (1X2, doble oportunidad y goles) y los clasifica por fiabilidad: VERDE, AMARILLO o ROJO.",
    "Genera combinadas IA de 2 a 4 selecciones optimizando probabilidad y valor esperado.",
    "Gestiona tu banca con staking tipo Kelly y un cortacircuitos que reduce el riesgo tras una mala racha.",
    "Aprende de tu historial: calibra sus probabilidades para que cada vez se acerquen más a la realidad.",
    "Te avisa por Telegram de los mejores picks, movimientos de cuota y resultados de tus combinadas.",
    "Lleva la cuenta por ti: liquida automáticamente picks, quinielas y combinadas, y calcula tu ROI verificado.",
])

# ── 2. INSTALACIÓN ───────────────────────────────────────────────────────────
h1("Instalación y primer arranque")
p("AlphaBet se distribuye como instalador para Windows (AlphaBet_Setup.exe). Solo tienes "
  "que ejecutarlo y seguir el asistente; se crea un acceso directo en el escritorio y en "
  "el menú de inicio. Antes del primer análisis hay un único paso obligatorio: activar "
  "The Odds API (lo vemos a continuación). El resto de ajustes son opcionales.")
h2("Dónde se guardan tus datos")
p("Toda tu información (historial de picks, combinadas, ROI, ajustes y el modelo "
  "entrenado) se guarda localmente en tu equipo, en la carpeta personal de la aplicación "
  "(%LOCALAPPDATA%\\AlphaBet). Nada se sube a Internet: tus datos son tuyos.")
h2("The Odds API: la clave imprescindible")
p("Antes de poder analizar necesitas conectar The Odds API. Es la fuente de la que "
  "AlphaBet obtiene los partidos próximos y sus cuotas reales de múltiples casas; sin "
  "ella, la aplicación no dispone de encuentros que analizar (la fuente histórica de "
  "respaldo solo cubre algunas ligas europeas mientras está su temporada en curso). La "
  "buena noticia: tiene un plan gratuito de 500 peticiones al mes —de sobra para un uso "
  "normal— y no pide tarjeta de crédito. Te explico cómo activarla en el apartado de "
  "Configuración.")
h2("Otras APIs (opcionales)")
p("El resto de servicios son opcionales y solo añaden extras: análisis en lenguaje "
  "natural con Claude IA, datos de lesiones en tiempo real, conexión con Betfair y "
  "notificaciones por Telegram. Puedes empezar sin ninguno de ellos y añadirlos cuando "
  "quieras desde la sección Strategy.")

# ── 3. TRADING DESK ──────────────────────────────────────────────────────────
h1("Trading Desk — la pantalla principal")
p("Es el centro de mando. Desde aquí eliges qué ligas analizar, ajustas tus filtros y "
  "lanzas el análisis. A la izquierda está el menú de navegación; en el panel central, "
  "el control de ligas y parámetros; a la derecha, los resultados con los mejores picks.")
image_full("01_trading_desk", "Trading Desk: panel de ligas y control (izquierda) y resultados con la tabla de picks (derecha).")
h2("Paso a paso")
bullets([
    "Requisito previo: ten The Odds API activada en Strategy (capítulo 4). Es la fuente de los partidos a analizar y de sus cuotas; sin ella no aparecerán encuentros.",
    "Marca las ligas que quieres analizar en «Ligas y control» (Premier League, La Liga, Serie A, Bundesliga, etc.).",
    "Ajusta el «Edge 1X2» y el «Edge Over 2.5»: son las ventajas mínimas que exiges para que un pick aparezca (por defecto valores prudentes).",
    "Indica tu «Bankroll base» (banca) para que el staking se calcule sobre tu capital real.",
    "Activa, si quieres, «Solo VERDE» o «Solo picks con valor» para ver únicamente las jugadas más fiables.",
    "Pulsa el botón «Run Analysis» (abajo a la izquierda) y espera unos segundos.",
])
p("Cuando el análisis termina, la tabla de la derecha se llena con los partidos, la "
  "predicción, la cuota, el edge (ventaja) y la fiabilidad de cada pick. Los códigos de "
  "color te guían de un vistazo: VERDE (alta confianza), AMARILLO (moderada) y ROJO "
  "(especulativa).")

# ── 4. CONFIGURACIÓN ─────────────────────────────────────────────────────────
h1("Configuración (Strategy)")
p("En la sección Strategy ajustas la app a tu gusto y conectas los servicios externos. El "
  "primero, The Odds API, es necesario para poder analizar; los demás son opcionales. "
  "Cada bloque es independiente y se guarda con su propio botón «Guardar».")
image_full("02_config_1", "Strategy: selector de tema de color (cambio instantáneo).")
h2("Tema de color")
p("Elige entre seis esquemas (Navy, Púrpura, Esmeralda, Carmesí, Dorado y Océano). El "
  "cambio es instantáneo; los paneles muestran el tema completo al refrescarse.")
h2("The Odds API — cuotas en tiempo real (IMPRESCINDIBLE)")
p("Es la API principal y necesaria: de aquí salen los partidos próximos y sus cuotas "
  "reales de múltiples casas, la base sobre la que el modelo calcula el valor. Sin esta "
  "clave activada, el análisis no encontrará encuentros que procesar. Configurarla es "
  "rápido: regístrate gratis en the-odds-api.com, copia tu API key, pégala en este bloque "
  "y marca la casilla «Usar The Odds API». El plan gratuito (500 peticiones al mes, sin "
  "tarjeta de crédito) es suficiente para el uso diario.")
image_full("02_config_2", "Bloques de tema y The Odds API.")
h2("Banca (bankroll)")
p("Introduce tu banca total en euros. Es la base sobre la que la app calcula el staking "
  "recomendado (fracción de Kelly) y el cortacircuitos de riesgo.")
h2("Claude IA (Anthropic) — análisis en lenguaje natural")
p("Si añades tu clave de Anthropic (console.anthropic.com), la app redacta un breve "
  "análisis explicativo para cada pick VERDE o AMARILLO tras cada análisis. Opcional, "
  "pero muy útil para entender el «porqué» de cada jugada.")
image_full("02_config_3", "Banca, Claude IA y datos de lesiones.")
h2("Lesiones (API-Football) y Betfair")
p("Con una clave gratuita de api-sports.io puedes incorporar bajas y lesiones en tiempo "
  "real al análisis. Además, puedes conectar tus credenciales de Betfair para consultar "
  "el exchange. Todos estos servicios son opcionales.")
h2("Telegram — notificaciones y bot")
p("Crea un bot con @BotFather, pega el token y (opcionalmente) tu Chat ID. Podrás recibir "
  "automáticamente los mejores picks, las alertas de cuota y los resultados de tus "
  "combinadas. El bot interactivo permite además consultar ROI, riesgo y CLV desde el "
  "propio Telegram. Marca «Telegram activado» y «Auto-enviar tras análisis» según prefieras.")
image_full("02_config_4", "Telegram y opciones de la combinada.")
h2("Combinada y filtros")
p("Define el tamaño de la combinada del Builder (de 2 a 4 selecciones) y los filtros de "
  "calidad (solo VERDE, solo picks con ventaja) que se aplican a todo el sistema.")

# ── 5. COMBINADAS IA ─────────────────────────────────────────────────────────
h1("Combinadas IA")
p("La app construye combinadas de 2 a 4 selecciones equilibrando probabilidad de acierto "
  "y valor esperado. Elige el número máximo de selecciones y el modo (Inteligente prioriza "
  "el valor; Seguras prioriza el porcentaje de acierto con doble oportunidad y goles).")
image_full("03_combinadas_ia", "Combinadas IA: control de selecciones máximas y modo de generación.")
h2("Cómo usarlas")
bullets([
    "Ejecuta primero el análisis en Trading Desk; después abre «Combinadas IA» y pulsa Generar.",
    "Revisa cada tarjeta: cuota total, probabilidad estimada, EV esperado, fiabilidad media y el detalle de cada selección.",
    "La «Apuesta recomendada» (marcada con una estrella) aplica un triple filtro: ML + Poisson + consenso de casas.",
    "Pulsa «Guardar en Portfolio» en cualquier combinada que te guste para hacerle seguimiento.",
])
h2("Seguimiento automático")
p("Las combinadas que guardas en el Portfolio se liquidan solas (GANADA / perdida) en "
  "cuanto hay resultados de todas sus selecciones, y pasan a contar en tu ROI. Si tienes "
  "Telegram activado, recibirás un aviso con el resultado. Así sabes siempre si las "
  "combinadas IA aciertan o no, sin anotar nada a mano.")

# ── 6. QUINIELA IA ───────────────────────────────────────────────────────────
h1("Quiniela IA")
p("Genera tu pronóstico de quiniela (1 / X / 2) con la probabilidad de cada signo, "
  "sugerencias de dobles y triples, y el coste de la apuesta. Los boletos que guardes se "
  "verifican automáticamente contra los resultados reales y te informan de los aciertos.")
image_full("04_quiniela_ia", "Quiniela IA: pronóstico por partido con dobles, triples, coste y probabilidad.")

# ── 7. ALERTAS ───────────────────────────────────────────────────────────────
h1("Alertas y monitor de líneas")
p("AlphaBet vigila el mercado por ti. El monitor de líneas detecta movimientos bruscos de "
  "cuota (steam) que suelen anticipar hacia dónde se mueve el dinero inteligente, y ajusta "
  "las probabilidades cuando hay bajas relevantes. Configura el intervalo de sondeo y el "
  "umbral de detección en Strategy.")
image_full("05_alertas", "Centro de alertas: monitor de líneas, detección de steam y ajuste por bajas.")

# ── 8. RESULTADOS ────────────────────────────────────────────────────────────
h1("Resultados")
p("Aquí se registra el seguimiento real de tus picks. La app liquida automáticamente cada "
  "selección con los resultados oficiales y calcula tu ROI verificado, para que veas sin "
  "autoengaños cómo está rindiendo el sistema.")
image_full("06_resultados", "Resultados: seguimiento de picks reales y ROI verificado.")

# ── 9. LIVE SCORES ───────────────────────────────────────────────────────────
h1("Live Scores")
p("Marcadores en tiempo real de los partidos del día, con auto-refresco cada 60 segundos "
  "y notificaciones. Ideal para seguir tus picks en directo sin salir de la aplicación.")
image_full("07_live_scores", "Live Scores: marcadores en directo con auto-refresco.")

# ── 10. CALENDARIO ───────────────────────────────────────────────────────────
h1("Calendario")
p("Una vista mensual de tus picks. Haz clic en un día para ver el detalle de los partidos "
  "y las jugadas previstas. Perfecto para planificar la semana de un vistazo.")
image_full("08_calendario", "Calendario: vista mensual de picks; clic en un día para el detalle.")

# ── 11. MANUAL SLIP ──────────────────────────────────────────────────────────
h1("Manual Slip (simulador)")
p("Un simulador manual para calcular al instante el retorno de una apuesta: introduce el "
  "signo (1 / X / 2), la cuota y el stake, y la app te muestra el beneficio potencial. "
  "Útil para tantear escenarios rápidos.")
image_full("09_manual_slip", "Manual Slip: simulación de 1X2 con cuota, stake y retorno.")

# ── 12. PORTFOLIO ────────────────────────────────────────────────────────────
h1("Portfolio")
p("El historial de todas tus combinadas (del Builder y de Combinadas IA), con su estado "
  "(pendiente / ganada / perdida), el beneficio y el ROI agregado. Desde aquí puedes "
  "liquidar manualmente cualquier combinada que no se haya resuelto sola.")
image_full("10_portfolio", "Portfolio: historial de combinadas, ROI y liquidación.")

# ── 13. PERFORMANCE ──────────────────────────────────────────────────────────
h1("Performance")
p("El cuadro de mando de tu rendimiento: curva de capital (equity), calibración del "
  "modelo (cómo de bien se ajustan sus probabilidades a la realidad), CLV (valor frente al "
  "cierre de línea) y ROI por liga. Es donde compruebas, con datos, que el sistema mejora.")
image_full("11_performance", "Performance: equity, calibración del modelo, CLV y ROI por liga.")

# ── 14. CHAT IA ──────────────────────────────────────────────────────────────
h1("Chat IA")
p("Un analista cuantitativo con el que conversar. Pregúntale sobre un pick concreto, sobre "
  "tu estrategia o sobre cómo gestionar la banca, y responde teniendo en cuenta el contexto "
  "de tu análisis actual. (Requiere la clave de Claude configurada en Strategy.)")
image_full("12_chat_ia", "Chat IA: pregunta sobre picks, estrategia y bankroll.")

# ── 15. FLUJO ────────────────────────────────────────────────────────────────
h1("Flujo de trabajo recomendado")
p("Una rutina sencilla para sacarle el máximo partido a AlphaBet día a día:")
bullets([
    "1) Una sola vez: en Strategy, indica tu banca y, si quieres, conecta The Odds API y Telegram.",
    "2) Cada jornada: en Trading Desk elige las ligas y pulsa «Run Analysis».",
    "3) Revisa los Top Picks VERDE/AMARILLO y lee el análisis IA si lo tienes activado.",
    "4) Abre Combinadas IA, genera y guarda en el Portfolio las que te convenzan.",
    "5) Deja que la app trabaje: liquida picks, quinielas y combinadas sola y te avisa por Telegram.",
    "6) Revisa de vez en cuando Resultados y Performance para confirmar que vas en verde.",
])

# ── 16. FAQ ──────────────────────────────────────────────────────────────────
h1("Preguntas frecuentes")
h2("¿Necesito alguna API para empezar?")
p("Sí, una: The Odds API. Es la que aporta los partidos próximos y sus cuotas, así que "
  "resulta imprescindible para analizar; aun así, su plan gratuito (500 peticiones al mes, "
  "sin tarjeta) basta para el uso normal. El resto de APIs —Claude IA, lesiones, Betfair y "
  "Telegram— son totalmente opcionales y también tienen planes gratuitos.")
h2("¿Las combinadas IA cuentan en mi ROI?")
p("Sí, siempre que las guardes en el Portfolio. A partir de ahí se liquidan automáticamente "
  "y su acierto o fallo se refleja en tu rendimiento.")
h2("¿Qué partidos se liquidan solos?")
p("Los de las ligas cubiertas por la fuente de resultados (principales competiciones "
  "europeas y varias internacionales). El resto puede liquidarse a mano en el Portfolio.")
h2("¿El modelo aprende de sus errores?")
p("Sí. AlphaBet calibra sus probabilidades con tu historial (regresión isotónica) para que "
  "cada vez se acerquen más a la realidad, algo especialmente importante en las combinadas.")
h2("¿Dónde están mis datos si reinstalo?")
p("En %LOCALAPPDATA%\\AlphaBet. Mientras no borres esa carpeta, conservas tu historial y tu "
  "modelo entrenado aunque actualices la aplicación.")

# ── 17. LEGAL ────────────────────────────────────────────────────────────────
h1("Juego responsable y aviso legal")
p("AlphaBet es una herramienta de análisis estadístico con fines informativos. No "
  "garantiza beneficios: ninguna metodología elimina el riesgo inherente a las apuestas. "
  "Las decisiones que tomes son de tu entera responsabilidad.")
p("Apuesta solo con dinero que puedas permitirte perder y nunca persigas las pérdidas. "
  "Establece límites y respétalos. Si sientes que el juego deja de ser un entretenimiento, "
  "busca ayuda: en España puedes llamar al 900 200 225 (línea de atención sobre ludopatía).")
p("Debes ser mayor de edad y cumplir la legislación de tu país. © 2026 Francesco Giuseppe "
  "Manolache. Software de uso privado; prohibida su distribución sin autorización expresa.")

pdf.output(OUT)
print("PDF_OK", OUT)
print("PAGES", pdf.page_no())
print("SIZE_KB", round(os.path.getsize(OUT) / 1024))
