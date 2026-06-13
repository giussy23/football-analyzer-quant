"""Segunda pasada: vistas UI sin logger de módulo. Añade
`import logging` + `logger = logging.getLogger(__name__)` antes de la primera
clase/función top-level y reemplaza los `except Exception: pass` silenciosos.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(
    r"(?P<except>^(?P<ind>[ \t]*)except Exception:[ \t]*\n)"
    r"(?P<body>(?P=ind)[ \t]+)pass[ \t]*$",
    re.MULTILINE,
)
FIRST_TOPLEVEL = re.compile(r"^(class |def |[A-Z_]+\s*[:=])", re.MULTILINE)

changed = []
for path in list(ROOT.glob("ui/**/*.py")):
    text = path.read_text(encoding="utf-8")
    if not PATTERN.search(text):
        continue

    if "logger = logging.getLogger" not in text:
        m = FIRST_TOPLEVEL.search(text)
        if not m:
            continue
        head = "" if re.search(r"^import logging$", text, re.MULTILINE) else "import logging\n\n"
        text = text[: m.start()] + head + "logger = logging.getLogger(__name__)\n\n\n" + text[m.start():]

    def repl(m: re.Match) -> str:
        return (
            m.group("except")
            + m.group("body")
            + 'logger.debug("Excepción ignorada", exc_info=True)'
        )

    new, n = PATTERN.subn(repl, text)
    path.write_text(new, encoding="utf-8")
    changed.append((str(path.relative_to(ROOT)), n))

for p, n in changed:
    print(f"{p}: {n}")
