"""Monta as páginas do simulador 3D a partir de saida/dados.json.

    python3 viewer/montar.py            -> saida/simulador3d.html            (offline, autocontido)
                                           saida/simulador3d_artefato.html   (Three.js via CDN, para publicar)
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ.parent / "saida"
TJS = RAIZ / "node_modules" / "three"

CDN = ('<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>\n'
       '<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>')

dados = (SAIDA / "dados.json").read_text(encoding="utf-8").replace("</", "<\\/")
main = (RAIZ / "src" / "main.js").read_text(encoding="utf-8")
pagina = (RAIZ / "src" / "pagina.html").read_text(encoding="utf-8")


def preencher(libs: str) -> str:
    return pagina.replace("{{DADOS}}", dados).replace("{{LIBS}}", libs).replace("{{MAIN}}", main)


# versão para publicar como artefato: fragmento sem <html>/<head>/<body>, bibliotecas por CDN
(SAIDA / "simulador3d_artefato.html").write_text(preencher(CDN), encoding="utf-8")

# versão offline: documento completo, Three.js embutido (abre com duplo clique, sem internet)
libs = "<script>\n" + (TJS / "build" / "three.min.js").read_text(encoding="utf-8") + "\n</script>\n<script>\n" + \
       (TJS / "examples" / "js" / "controls" / "OrbitControls.js").read_text(encoding="utf-8") + "\n</script>"
doc = ('<!doctype html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
       '<style>:root{color-scheme:light}html,body{margin:0}</style>\n</head>\n<body>\n'
       + preencher(libs) + "\n</body>\n</html>\n")
(SAIDA / "simulador3d.html").write_text(doc, encoding="utf-8")
for n in ("simulador3d.html", "simulador3d_artefato.html"):
    print(n, round((SAIDA / n).stat().st_size / 1024), "KB")
