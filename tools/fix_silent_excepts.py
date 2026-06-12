"""Reemplaza handlers `except Exception:` cuyo cuerpo es solo `pass` por
logger.debug(..., exc_info=True), para que los errores dejen rastro en debug.

Solo toca ficheros que ya definen `logger = logging.getLogger(...)` a nivel
de módulo. Uso único (tools/), se puede borrar después.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(
    r"(?P<except>^(?P<ind>[ \t]*)except Exception:[ \t]*\n)"
    r"(?P<body>(?P=ind)[ \t]+)pass[ \t]*$",
    re.MULTILINE,
)

changed = []
for path in list(ROOT.glob("core/*.py")) + list(ROOT.glob("ui/**/*.py")) + [ROOT / "app.py"]:
    text = path.read_text(encoding="utf-8")
    if "logger = logging.getLogger" not in text:
        continue

    def repl(m: re.Match) -> str:
        return (
            m.group("except")
            + m.group("body")
            + 'logger.debug("Excepción ignorada", exc_info=True)'
        )

    new, n = PATTERN.subn(repl, text)
    if n:
        path.write_text(new, encoding="utf-8")
        changed.append((path.relative_to(ROOT), n))

for p, n in changed:
    print(f"{p}: {n}")
print("Total ficheros:", len(changed), "— total reemplazos:", sum(n for _, n in changed))
