"""
Conversión del cuerpo en texto plano (con links en formato Markdown, tal como los genera
el Redactor) a HTML, y construcción de la firma con los iconos de redes sociales. Vive
aparte de gmail_client.py para no mezclar la construcción del MIME con el formateo del
contenido.
"""
import re
import html

# Los iconos se sirven como imágenes públicas normales (GitHub Pages, rama `gh-pages` con
# solo estos 3 assets — no expone nada más del repo privado) en vez de embebidos por
# Content-ID: las imágenes inline por CID no sobreviven al reenvío de un borrador desde la
# propia interfaz de Gmail (Gmail reconstruye el mensaje y las pierde). Con una URL normal
# no hay ese problema — es como lo hace cualquier firma de email real.
BASE_URL_ICONOS = "https://diegocalleb.github.io/bakandeya-agent-manager"

# (nombre visible, archivo de icono, campo correspondiente en epk['enlaces'])
REDES_SOCIALES = [
    ("YouTube", "youtube.png", "youtube_perfil"),
    ("Instagram", "instagram.png", "instagram"),
    ("TikTok", "tiktok.png", "tik_tok"),
]

_RE_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
# Red de seguridad: el LLM a veces escribe el link como '[url]' (sin el '(url)' de markdown)
# o como una URL suelta sin corchetes. Ambos se capturan aparte para no depender de que el
# Redactor acierte siempre el formato exacto.
_RE_BRACKET_URL = re.compile(r"\[(https?://[^\s\]]+)\]")
_RE_BARE_URL = re.compile(r"(?<![\"'>])(https?://[^\s<]+)")


def texto_a_html(cuerpo_texto):
    """
    Convierte el cuerpo en texto plano a un fragmento de HTML seguro: escapa el texto,
    convierte los links en formato Markdown ``[texto](url)`` (así los escribe el Redactor)
    en ``<a>`` reales, y los párrafos separados por línea en blanco en ``<p>``.
    """
    escapado = html.escape(cuerpo_texto)

    con_links = _RE_MARKDOWN_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escapado)
    con_links = _RE_BRACKET_URL.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', con_links)
    con_links = _RE_BARE_URL.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', con_links)

    parrafos = [p.replace("\n", "<br>") for p in con_links.split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in parrafos)


def construir_firma_html(epk):
    """
    Fila de iconos de redes sociales (imagen alojada en GitHub Pages) que enlazan a los
    perfiles reales del EPK. Devuelve un fragmento de HTML, o "" si el EPK no trae enlaces.
    """
    enlaces = (epk or {}).get("enlaces", {})
    iconos_html = []

    for nombre, archivo, campo in REDES_SOCIALES:
        url = enlaces.get(campo)
        if not url:
            continue
        iconos_html.append(
            f'<a href="{url}" style="text-decoration:none; margin-right:10px;">'
            f'<img src="{BASE_URL_ICONOS}/{archivo}" width="28" height="28" alt="{nombre}" '
            f'style="vertical-align:middle; border:0;"></a>'
        )

    if not iconos_html:
        return ""

    return f'<div style="margin-top:18px;">{"".join(iconos_html)}</div>'
