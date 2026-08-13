import os
import sys
import json
import time
import random
import unicodedata
import argparse
import difflib
from dotenv import load_dotenv

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

import lib.sheets as sheets
import lib.gemini_client as gemini_client
import lib.estados as estados
from lib.busqueda import buscar_duckduckgo, formatear_snippets

BAND_ID_DEFAULT = sheets.BAND_ID_DEFAULT

# Reutilizamos el motor de confianza/extracción anti-alucinación de scout.py en vez de
# duplicarlo: mismo umbral, mismo esquema valor/confianza/fuente, mismo regex de emails.
from agents.scout import (
    NIVELES_CONFIANZA,
    _extraer_emails_con_regex,
    _procesar_campos_extraidos,
    descargar_texto_pagina,
)

UMBRALES_MEDIOS = {
    "email": "media",
    "enfoque_editorial": "media",
    "direccion": "alta",
}


def normalizar_nombre(texto):
    """
    Normaliza el nombre de un medio para deduplicación (minúsculas, sin acentos, sin espacios).
    """
    if not texto:
        return ""
    texto = texto.lower().strip()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return texto.replace(" ", "").replace("-", "").replace("_", "").strip()


def es_duplicado_difuso(nombre_cand, nombres_existentes_normalizados, umbral=0.85):
    """
    Igual que en scout_descubridor.py: exacto, subcadena o similitud difusa.
    """
    norm_cand = normalizar_nombre(nombre_cand)
    if not norm_cand:
        return True, ""
    if norm_cand in nombres_existentes_normalizados:
        return True, norm_cand
    for norm_existente in nombres_existentes_normalizados:
        if not norm_existente:
            continue
        if len(norm_existente) >= 4 and norm_existente in norm_cand:
            return True, norm_existente
        if len(norm_cand) >= 4 and norm_cand in norm_existente:
            return True, norm_existente
        if difflib.SequenceMatcher(None, norm_cand, norm_existente).ratio() >= umbral:
            return True, norm_existente
    return False, norm_cand


def obtener_queries_busqueda_medios(tipo_medio, ciudad):
    """
    Genera variaciones de queries de búsqueda en DuckDuckGo, forzando 'España' para
    desambiguación geográfica (igual criterio que scout_descubridor.py para salas/festivales).
    """
    t = tipo_medio.lower().strip()
    ciudad_ctx = ciudad if "españa" in ciudad.lower() or "espana" in ciudad.lower() else f"{ciudad} España"

    if t == "radio":
        return [
            f"emisoras de radio {ciudad_ctx}",
            f"radio local musica en directo {ciudad_ctx}",
        ]
    elif t == "tv":
        return [
            f"television local canal de television {ciudad_ctx}",
            f"tv local programas de musica {ciudad_ctx}",
        ]
    elif t == "prensa":
        return [
            f"periodico diario local prensa {ciudad_ctx}",
            f"revista cultural agenda de conciertos {ciudad_ctx}",
        ]
    elif t == "blog":
        return [
            f"blog de musica independiente {ciudad_ctx}",
            f"medio digital cultura musica {ciudad_ctx}",
        ]
    elif t == "podcast":
        return [
            f"podcast de musica en español {ciudad_ctx}",
            f"podcast entrevistas bandas musica {ciudad_ctx}",
        ]
    else:
        return [
            f"{t} de musica cultura {ciudad_ctx}",
        ]


def extraer_candidatos_medios_con_ia(resultados, tipo_medio, ciudad):
    """
    Usa Gemini para extraer nombres de medios reales a partir de snippets de búsqueda,
    con grounding obligatorio (igual criterio anti-alucinación que scout_descubridor.py).
    """
    if not resultados:
        return []

    res_str = formatear_snippets(resultados)

    prompt = (
        f"Analiza los siguientes resultados de búsqueda web para encontrar nombres de medios de "
        f"comunicación de tipo '{tipo_medio}' en la ciudad/región de '{ciudad}' (ESPAÑA):\n\n"
        f"{res_str}\n"
        f"Tu objetivo es extraer una lista de medios REALES de tipo '{tipo_medio}' que emitan o "
        f"publiquen en la zona de '{ciudad}', España.\n"
        "Reglas estrictas:\n"
        "1. DESAMBIGUACIÓN GEOGRÁFICA: extrae únicamente medios ubicados o que emiten en ESPAÑA. "
        "Descarta cualquier medio de fuera de España aunque el nombre de la ciudad coincida.\n"
        f"2. TIPO EXACTO: extrae únicamente entidades que correspondan al tipo '{tipo_medio}' (ej: si "
        "el tipo es 'radio', emisoras de radio reales, no genéricas ni agregadores de streaming).\n"
        "3. GROUNDING: no inventes medios. Extrae SOLO los que aparezcan explícitamente en los "
        "snippets de arriba. Para cada candidato, 'fuente' debe ser el índice del snippet que lo "
        "respalda (ej: '[3]'). Si no puedes señalar un snippet concreto, NO incluyas ese candidato.\n"
        "4. Descarta directorios genéricos, agregadores o listados (ej: 'Guía de emisoras de España') "
        "que no sean ellos mismos un medio concreto.\n"
        "5. Devuelve un objeto JSON con este esquema exacto:\n"
        "{\n"
        "  \"candidatos\": [\n"
        "    {\n"
        "      \"nombre\": \"Nombre oficial del medio\",\n"
        "      \"ciudad\": \"Localidad/alcance\",\n"
        "      \"fuente\": \"[n]\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    system_prompt = (
        "Eres un extractor experto de medios de comunicación reales a partir de resultados de "
        "búsqueda web. Tu única salida posible debe ser un objeto JSON válido según el esquema "
        "solicitado. No inventes medios: si no está en los snippets, no existe para ti."
    )

    ans = gemini_client.generar_texto_gemini(
        prompt=prompt,
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        temperature=0.1,
        forzar_json=True
    )
    if not ans:
        return []

    try:
        data = json.loads(ans)
        return data.get("candidatos", [])
    except Exception as e:
        print(f"[scout_medios.py] Error al parsear JSON de Gemini: {e}. Respuesta: {ans}")
        return []


def descubrir_medios(ciudad, tipo_medio="radio", limite=10, band_id=BAND_ID_DEFAULT):
    """
    Busca medios de un tipo en una ciudad/región, los deduplica contra los existentes en la
    hoja 'medios', y los crea en estado 'nuevo'. Devuelve la lista de filas creadas.
    """
    tipo_medio = tipo_medio.strip().lower()
    print(f"[scout_medios.py] Descubriendo medios de tipo '{tipo_medio}' en '{ciudad}' (España)...")

    queries = obtener_queries_busqueda_medios(tipo_medio, ciudad)
    resultados_combinados = []
    urls_vistas = set()
    for q in queries:
        print(f"[scout_medios.py] Buscando: '{q}'...")
        res = buscar_duckduckgo(q, max_results=8)
        for r in res:
            href = r.get("href")
            if href not in urls_vistas:
                urls_vistas.add(href)
                resultados_combinados.append(r)

    if not resultados_combinados:
        print("[scout_medios.py] No se obtuvieron resultados de búsqueda.")
        return []

    candidatos = extraer_candidatos_medios_con_ia(resultados_combinados, tipo_medio, ciudad)
    print(f"[scout_medios.py] IA extrajo {len(candidatos)} posibles candidatos.")

    medios_existentes = sheets.obtener_leads(nombre_hoja="medios_scout")
    nombres_existentes_normalizados = {
        normalizar_nombre(m.get("nombre_medio")) for m in medios_existentes if m.get("nombre_medio")
    }

    medios_a_crear = []
    for cand in candidatos:
        nombre = cand.get("nombre")
        ciudad_cand = cand.get("ciudad") or ciudad
        fuente_snippet = cand.get("fuente")

        if not nombre:
            continue

        es_dup, norm_nombre = es_duplicado_difuso(nombre, nombres_existentes_normalizados)
        if es_dup:
            print(f"[scout_medios.py] Ignorando '{nombre}' (duplicado de '{norm_nombre}').")
            continue

        medio_id = f"medio_{random.getrandbits(32):08x}"
        nuevo_medio = {
            "id": medio_id,
            "nombre_medio": nombre,
            "tipo_medio": tipo_medio,
            "ciudad": ciudad_cand,
            "alcance": "",
            "email_contacto": "",
            "enfoque_editorial": "",
            "band_id": band_id,
            "fuente": f"Scout Medios: {ciudad}",
            "estado": estados.NUEVO,
            "pitch_generado": "",
            "fecha_envio": "",
            "fecha_ultima_respuesta": "",
            "notas": (
                f"Descubierto automáticamente por scout_medios.py (tipo: {tipo_medio})"
                + (f" (snippet {fuente_snippet})." if fuente_snippet else ".")
                + " Contacto SIN verificar: pendiente de enriquecer."
            ),
        }
        medios_a_crear.append(nuevo_medio)
        nombres_existentes_normalizados.add(norm_nombre)

        if len(medios_a_crear) >= limite:
            break

    if not medios_a_crear:
        print("[scout_medios.py] Todos los candidatos ya existían en la hoja 'medios'.")
        return []

    print(f"[scout_medios.py] Insertando {len(medios_a_crear)} nuevos medios...")
    exito = sheets.crear_leads(medios_a_crear, nombre_hoja="medios_scout")
    if not exito:
        print("[scout_medios.py] Error al insertar medios en la Google Sheet.")
        return []

    return medios_a_crear


def extraer_datos_medio_de_snippets(nombre_medio, ciudad, resultados, tipo_medio):
    """
    Extrae email de contacto y enfoque editorial a partir de snippets de búsqueda, con el mismo
    esquema valor/confianza/fuente que usa scout.py (reutilizando _procesar_campos_extraidos).
    """
    if not resultados:
        return {}

    res_str = formatear_snippets(resultados)

    prompt = (
        f"Analiza los siguientes snippets de resultados de búsqueda web para el medio de comunicación "
        f"'{nombre_medio}' (tipo: {tipo_medio}) en '{ciudad}':\n\n"
        f"{res_str}\n"
        "Tu objetivo es extraer:\n"
        "1. email: el email de contacto/redacción/prensa oficial de este medio (ej: redaccion@..., "
        "info@..., contacto@...). NUNCA el email de un tercero o de un directorio genérico.\n"
        "2. enfoque_editorial: una frase breve (máx. 20 palabras) sobre qué tipo de contenido cubre "
        "este medio (música, cultura, actualidad local...), basada SOLO en lo que dice el texto.\n"
        "3. direccion: la dirección postal completa (calle, número, código postal) de la sede/redacción "
        "de este medio, SOLO si aparece literal en el texto. Si no aparece, null.\n\n"
        "Reglas:\n"
        "- Para CADA dato indica tu nivel de confianza y de dónde lo sacaste:\n"
        "    * confianza='alta' solo si el dato aparece literal y claramente asociado a ESTE medio.\n"
        "    * confianza='media' si lo deduces de forma razonable pero no es literal.\n"
        "    * confianza='baja' si es una suposición. NUNCA inventes un dato con confianza alta.\n"
        "    * fuente = el índice del snippet que respalda el dato (ej: '[2]'), o null si no lo viste.\n"
        "- Si no encuentras un campo, pon valor=null y confianza='baja'.\n"
        "- Devuelve un objeto JSON con este esquema exacto:\n"
        "{\n"
        "  \"email\": {\"valor\": \"email o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"enfoque_editorial\": {\"valor\": \"frase breve o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"direccion\": {\"valor\": \"direccion postal o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"}\n"
        "}"
    )

    ans = gemini_client.generar_texto_gemini(
        prompt=prompt,
        model_name="gemini-2.5-flash",
        temperature=0.1,
        forzar_json=True
    )
    if not ans:
        return {}

    try:
        data = json.loads(ans)
    except Exception as e:
        print(f"[scout_medios.py] Error al parsear JSON de Gemini (snippets): {e}. Respuesta: {ans}")
        return {}

    aceptados, sugerencias = _procesar_campos_extraidos(
        data, campos=["email", "enfoque_editorial", "direccion"], umbrales_por_campo=UMBRALES_MEDIOS,
    )
    if sugerencias:
        aceptados["_sugerencias"] = sugerencias
    return aceptados


def enriquecer_un_medio(medio):
    """
    Enriquece un único medio (email_contacto + enfoque_editorial). Igual patrón que
    procesar_un_lead en scout.py: solo escribe datos de confianza suficiente; si no encuentra
    email tras la búsqueda, no lo deja atascado reintentándose para siempre (queda en 'nuevo'
    pero anotado en notas, ya que 'medios' aún no tiene un estado terminal tipo SIN_CONTACTO).
    """
    medio_id = medio.get("id")
    nombre_medio = medio.get("nombre_medio")
    ciudad = medio.get("ciudad") or ""
    tipo_medio = (medio.get("tipo_medio") or "medio").strip().lower()

    time.sleep(random.uniform(0.1, 1.5))
    print(f"\n[scout_medios.py] >>> Enriqueciendo '{nombre_medio}' ({ciudad}) [ID: {medio_id}]")

    query = f"{nombre_medio} {ciudad} contacto redaccion email"
    resultados = buscar_duckduckgo(query, max_results=15)
    datos = extraer_datos_medio_de_snippets(nombre_medio, ciudad, resultados, tipo_medio)
    sugerencias = list(datos.get("_sugerencias") or [])

    email = datos.get("email")
    enfoque_editorial = datos.get("enfoque_editorial")
    direccion = datos.get("direccion")

    emails_regex = _extraer_emails_con_regex(formatear_snippets(resultados))
    if emails_regex and not email:
        email = emails_regex[0]

    if email and "@" not in email:
        email = None

    if email or enfoque_editorial or direccion:
        print(f"[scout_medios.py] [SUCCESS] Email: {email or 'N/A'}, Enfoque: {enfoque_editorial or 'N/A'}, Dirección: {direccion or 'N/A'}")
        notas_previas = medio.get("notas") or ""
        nuevas_notas = notas_previas
        if sugerencias:
            nuevas_notas += " | A verificar (baja confianza): " + "; ".join(sugerencias)

        datos_actualizar = {"notas": nuevas_notas}
        if email and not medio.get("email_contacto"):
            datos_actualizar["email_contacto"] = email
        if enfoque_editorial and not medio.get("enfoque_editorial"):
            datos_actualizar["enfoque_editorial"] = enfoque_editorial
        if direccion and not medio.get("direccion"):
            datos_actualizar["direccion"] = direccion

        # Si la escritura en el Sheet falla (p. ej. corte de red), NO reportamos éxito: el
        # llamador usaría ese resultado para notificar/contar como enriquecido algo que en
        # realidad no quedó guardado.
        res = sheets.actualizar_datos_lead(medio_id, datos_actualizar, nombre_hoja="medios_scout")

        if email and res:
            return {"id": medio_id, "nombre": nombre_medio, "email": email, "enfoque_editorial": enfoque_editorial or ""}
        return None
    else:
        print(f"[scout_medios.py] [ERROR] No se encontró contacto para '{nombre_medio}'.")
        notas_previas = medio.get("notas") or ""
        sheets.actualizar_datos_lead(
            medio_id,
            {"notas": f"{notas_previas} | Scout medios: búsqueda sin resultados de contacto."},
            nombre_hoja="medios_scout",
        )
        return None


def enriquecer_medios_sin_contacto(limite=10):
    """
    Busca filas en 'medios' en estado 'nuevo' sin email_contacto y las enriquece en paralelo,
    igual que enriquecer_leads_sin_contacto en scout.py.
    """
    medios = sheets.obtener_leads(estado=estados.NUEVO, nombre_hoja="medios_scout")
    medios_sin_contacto = [m for m in medios if not m.get("email_contacto")]
    print(f"[scout_medios.py] {len(medios_sin_contacto)} medios sin contacto para enriquecer.")

    if not medios_sin_contacto:
        return []

    medios_a_procesar = medios_sin_contacto[:limite]

    from concurrent.futures import ThreadPoolExecutor
    max_workers = min(3, len(medios_a_procesar))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        resultados = list(executor.map(enriquecer_un_medio, medios_a_procesar))

    enriquecidos = [r for r in resultados if r is not None]
    print(f"[scout_medios.py] Enriquecimiento finalizado. Medios con contacto encontrado: {len(enriquecidos)}")
    return enriquecidos


def descubrir_y_enriquecer_medios(ciudad, tipo_medio="radio", limite=10, band_id=BAND_ID_DEFAULT):
    """
    Punto de entrada principal: descubre candidatos nuevos y enriquece de inmediato los que
    acaba de crear (mismo flujo que scout_descubridor.py -> scout.py).
    """
    creados = descubrir_medios(ciudad, tipo_medio=tipo_medio, limite=limite, band_id=band_id)
    if not creados:
        return [], []

    print(f"\n[scout_medios.py] Enriqueciendo los {len(creados)} medios recién descubiertos...")
    enriquecidos = enriquecer_medios_sin_contacto(limite=len(creados))
    return creados, enriquecidos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente Scout de Medios: descubre y enriquece contactos de prensa/radio/TV.")
    parser.add_argument("--ciudad", type=str, required=True, help="Ciudad o región donde buscar.")
    parser.add_argument("--tipo", type=str, default="radio", help="Tipo de medio: radio, tv, prensa, blog, podcast.")
    parser.add_argument("--limit", type=int, default=10, help="Límite máximo de nuevos medios a añadir.")
    parser.add_argument("--banda", type=str, default=BAND_ID_DEFAULT, help="band_id al que pertenecen los medios descubiertos (multi-tenant). Por defecto, band-bakandeya.")
    args = parser.parse_args()

    creados, enriquecidos = descubrir_y_enriquecer_medios(args.ciudad, tipo_medio=args.tipo, limite=args.limit, band_id=args.banda)
    print(f"\n[scout_medios.py] Resumen: {len(creados)} medios descubiertos, {len(enriquecidos)} con contacto encontrado.")
