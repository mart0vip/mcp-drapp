"""Texto de los adjuntos de la HCE, para que la busqueda los alcance.

Tres origenes, en orden de confianza:
  - `pdf`: capa de texto del PDF (pypdf). Fiel, es el texto que el laboratorio
    genero.
  - `ocr`: reconocimiento optico sobre imagenes y PDFs escaneados, con el
    framework Vision de Apple. **Corre entero en la maquina**: ningun documento
    clinico sale a un servicio externo.
  - `sin_texto`: no se pudo extraer nada.

El texto se guarda en data/adjuntos_texto/<paciente>/<registro>.txt y es
derivado: se puede borrar y regenerar desde los binarios.
"""
import pathlib
import warnings

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADJUNTOS = ROOT / "data" / "adjuntos"
TEXTOS = ROOT / "data" / "adjuntos_texto"

# Debajo de esto se asume que el PDF es un escaneo sin capa de texto util.
MINIMO_TEXTO = 40


def texto_de_pdf(ruta: pathlib.Path) -> str:
    from pypdf import PdfReader
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            r = PdfReader(str(ruta))
            return "\n".join((p.extract_text() or "") for p in r.pages).strip()
        except Exception:
            return ""


def _ocr_imagen(cg_image) -> str:
    import Vision
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)                     # 0 = accurate, 1 = fast
    req.setRecognitionLanguages_(["es-ES", "en-US"])
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, None)
    ok, _ = handler.performRequests_error_([req], None)
    if not ok:
        return ""
    partes = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if cand:
            partes.append(str(cand[0].string()))
    return "\n".join(partes).strip()


def ocr_de_imagen(ruta: pathlib.Path) -> str:
    import Quartz
    url = Quartz.CFURLCreateFromFileSystemRepresentation(
        None, str(ruta).encode("utf-8"), len(str(ruta).encode("utf-8")), False)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if not src or Quartz.CGImageSourceGetCount(src) == 0:
        return ""
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    return _ocr_imagen(img) if img else ""


def ocr_de_pdf(ruta: pathlib.Path, max_paginas: int = 12) -> str:
    """Rasteriza cada pagina y le pasa OCR. Para PDFs escaneados."""
    import Quartz
    url = Quartz.CFURLCreateFromFileSystemRepresentation(
        None, str(ruta).encode("utf-8"), len(str(ruta).encode("utf-8")), False)
    doc = Quartz.CGPDFDocumentCreateWithURL(url)
    if not doc:
        return ""
    total = min(Quartz.CGPDFDocumentGetNumberOfPages(doc), max_paginas)
    salida = []
    for n in range(1, total + 1):
        page = Quartz.CGPDFDocumentGetPage(doc, n)
        if not page:
            continue
        caja = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        escala = 2.0                                # ~144 dpi: legible sin pesar
        ancho, alto = int(caja.size.width * escala), int(caja.size.height * escala)
        if ancho < 10 or alto < 10 or ancho * alto > 40_000_000:
            continue
        espacio = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(
            None, ancho, alto, 8, 0, espacio,
            Quartz.kCGImageAlphaNoneSkipLast)
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, ancho, alto))
        Quartz.CGContextScaleCTM(ctx, escala, escala)
        Quartz.CGContextDrawPDFPage(ctx, page)
        img = Quartz.CGBitmapContextCreateImage(ctx)
        if img:
            salida.append(_ocr_imagen(img))
    return "\n".join(x for x in salida if x).strip()


def extraer(ruta: pathlib.Path) -> tuple[str, str]:
    """Devuelve (texto, origen) para un adjunto. Nunca levanta excepcion."""
    try:
        if ruta.suffix.lower() == ".pdf":
            t = texto_de_pdf(ruta)
            if len(t) >= MINIMO_TEXTO:
                return t, "pdf"
            t = ocr_de_pdf(ruta)
            return (t, "ocr") if len(t) >= MINIMO_TEXTO else ("", "sin_texto")
        t = ocr_de_imagen(ruta)
        return (t, "ocr") if len(t) >= MINIMO_TEXTO else ("", "sin_texto")
    except Exception:
        return "", "sin_texto"


def ruta_texto(consumer_id: str, record_id: str) -> pathlib.Path:
    return TEXTOS / consumer_id / f"{record_id}.txt"


def leer_texto(consumer_id: str, record_id: str) -> str:
    """Texto ya extraido de un adjunto, o cadena vacia si no hay."""
    p = ruta_texto(consumer_id, record_id)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""
