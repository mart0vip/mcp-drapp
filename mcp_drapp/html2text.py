"""HTML del editor de drapp -> texto plano, preservando tablas y listas."""
import html as _html
import re


def _celda(c: str) -> str:
    c = re.sub(r"(?i)<br\b[^>]*>", " ", c)
    c = re.sub(r"(?is)<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", c)
    c = re.sub(r"(?is)<(i|em)[^>]*>(.*?)</\1>", r"*\2*", c)
    c = re.sub(r"<[^>]+>", "", c)
    c = _html.unescape(c).replace("\xa0", " ")
    return re.sub(r"\s+", " ", c).strip().replace("|", r"\|")


def _tabla(m: re.Match) -> str:
    filas = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(0)):
        celdas = [_celda(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        if any(celdas):
            filas.append(celdas)
    if not filas:
        return ""
    ancho = max(len(f) for f in filas)
    filas = [f + [""] * (ancho - len(f)) for f in filas]
    out = ["| " + " | ".join(filas[0]) + " |", "|" + "---|" * ancho]
    out += ["| " + " | ".join(f) + " |" for f in filas[1:]]
    return "\n\n" + "\n".join(out) + "\n\n"


def to_text(h: str | None) -> str:
    """Convierte el HTML del editor a texto plano legible."""
    if not isinstance(h, str) or not h.strip():
        return ""
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)

    # las tablas se resuelven aparte: el HTML trae saltos de linea entre celdas
    tablas: list[str] = []

    def _stash(m: re.Match) -> str:
        tablas.append(_tabla(m))
        return f"\x00T{len(tablas) - 1}\x00"

    h = re.sub(r"(?is)<table[^>]*>.*?</table>", _stash, h)
    h = re.sub(r"(?i)<br\b[^>]*>", "\n", h)
    h = re.sub(r"(?i)</(p|div|h[1-6])>", "\n\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"(?is)<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", h)
    h = re.sub(r"(?is)<(i|em)[^>]*>(.*?)</\1>", r"*\2*", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = _html.unescape(h).replace("\xa0", " ")
    h = "\n".join(l.rstrip() for l in h.split("\n"))
    h = re.sub(r"\n{3,}", "\n\n", h).strip()
    for i, t in enumerate(tablas):
        h = h.replace(f"\x00T{i}\x00", t)
    return re.sub(r"\n{3,}", "\n\n", h).strip()
