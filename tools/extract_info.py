import sys, marshal, dis, types, os

PYC_BASE = r"D:\football_analyzer\AlphaBet.exe_extracted\PYZ.pyz_extracted\football_analyzer"
OUT_BASE = r"D:\football_analyzer_recovered"

files = [
    ("app.pyc", "app.py"),
    (r"core\accumulator.pyc", r"core\accumulator.py"),
    (r"core\ai_analysis.pyc", r"core\ai_analysis.py"),
    (r"core\analyzer.pyc", r"core\analyzer.py"),
    (r"core\club_elo.pyc", r"core\club_elo.py"),
    (r"core\config.pyc", r"core\config.py"),
    (r"core\data.pyc", r"core\data.py"),
    (r"core\elo.pyc", r"core\elo.py"),
    (r"core\features.pyc", r"core\features.py"),
    (r"core\model.pyc", r"core\model.py"),
    (r"core\odds_api.pyc", r"core\odds_api.py"),
    (r"core\poisson.pyc", r"core\poisson.py"),
    (r"core\quiniela_lae.pyc", r"core\quiniela_lae.py"),
    (r"core\storage.pyc", r"core\storage.py"),
    (r"core\telegram_bot.pyc", r"core\telegram_bot.py"),
    (r"ui\views\accumulator.pyc", r"ui\views\accumulator.py"),
    (r"ui\views\analysis.pyc", r"ui\views\analysis.py"),
    (r"ui\views\portfolio.pyc", r"ui\views\portfolio.py"),
    (r"ui\views\quiniela.pyc", r"ui\views\quiniela.py"),
    (r"ui\views\results.pyc", r"ui\views\results.py"),
    (r"ui\views\settings.pyc", r"ui\views\settings.py"),
    (r"ui\widgets.pyc", r"ui\widgets.py"),
]

def get_all_code_objects(code):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from get_all_code_objects(const)

for pyc_rel, py_rel in files:
    src = os.path.join(PYC_BASE, pyc_rel)
    dst = os.path.join(OUT_BASE, py_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        with open(src, "rb") as f:
            f.read(16)
            code = marshal.loads(f.read())

        lines = [f"# === {py_rel} ===", ""]
        for co in get_all_code_objects(code):
            if co.co_name != "<module>":
                lines.append(f"# FUNCTION/CLASS: {co.co_name}")
            # String constants (docstrings, labels, SQL, etc.)
            str_consts = [c for c in co.co_consts if isinstance(c, str) and len(c) > 5 and "\n" not in c]
            if str_consts:
                lines.append(f"#   strings: {str_consts[:8]}")
            # Variable names
            if co.co_varnames:
                lines.append(f"#   vars: {list(co.co_varnames[:12])}")
            lines.append("")

        with open(dst, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"OK: {py_rel}")
    except Exception as e:
        print(f"ERR {py_rel}: {e}")

print("Done.")
