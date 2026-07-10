"""
Búsqueda web compartida por los agentes Scout (scout.py y scout_descubridor.py).

Antes cada uno tenía su propia copia idéntica de `obtener_resultados_busqueda` y repetía el
formateo de snippets en varias funciones. Aquí queda en un solo sitio: una fuente, un rate
limiting, un formato.
"""

import time
import random


def buscar_duckduckgo(query, max_results=8, pausa=True):
    """
    Busca en DuckDuckGo y devuelve la lista de resultados (dicts con title/href/body).

    `pausa=True` mete una pausa corta y aleatoria antes de la petición para no disparar
    búsquedas en bucle (DuckDuckGo bloquea si se abusa). Devuelve [] ante cualquier error.
    """
    from ddgs import DDGS

    if pausa:
        time.sleep(random.uniform(1.0, 2.5))

    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"[busqueda] Error al buscar '{query}': {e}")
        return []


def formatear_snippets(resultados, con_url=True):
    """
    Convierte los resultados de búsqueda en el bloque de texto numerado `[n]` que se le pasa a
    la IA. `con_url=False` omite la URL (para prompts donde solo importa el texto).
    """
    lineas = []
    for idx, r in enumerate(resultados, 1):
        if con_url:
            lineas.append(
                f"[{idx}] Título: {r.get('title')}\n    URL: {r.get('href')}\n    Snippet: {r.get('body')}\n"
            )
        else:
            lineas.append(f"[{idx}] Título: {r.get('title')}\n    Snippet: {r.get('body')}\n")
    return "\n".join(lineas)
