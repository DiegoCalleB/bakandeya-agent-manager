import os
import sys
import json
import uuid
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

def normalizar_nombre(texto):
    """
    Normaliza el texto quitando acentos, pasándolo a minúsculas y eliminando
    espacios y prefijos comunes para una comparación de deduplicación más limpia.
    """
    if not texto:
        return ""
    texto = texto.lower().strip()
    # Eliminar acentos
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    
    # Eliminar prefijos comunes
    prefijos = [
        "ayuntamiento de ", "ayuntamiento ", "concello de ", "concello ", "ayto de ", "concejo de ",
        "sala de conciertos ", "sala ", "discoteca de ", "discoteca ", "discotecas ", "club de ", "club ",
        "pub ", "teatro ", "auditorio ", "festival de musica ", "festival ", "fest "
    ]
    for prefijo in prefijos:
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):]
            
    # Eliminar sufijos comunes
    sufijos = [" festival", " fest", " sala", " discoteca", " club", " pub", " teatro", " auditorio"]
    for sufijo in sufijos:
        if texto.endswith(sufijo):
            texto = texto[:-len(sufijo)]
            
    return texto.replace(" ", "").replace("-", "").replace("_", "").strip()

def es_duplicado_difuso(nombre_cand, nombres_existentes_normalizados, umbral=0.80):
    """
    Comprueba si el nombre de un candidato es un duplicado (exacto, por subcadena o por similitud difusa)
    de algún lead existente en la base de datos.
    Devuelve (es_duplicado, nombre_normalizado_coincidente).
    """
    norm_cand = normalizar_nombre(nombre_cand)
    if not norm_cand:
        return True, ""
    if norm_cand in nombres_existentes_normalizados:
        return True, norm_cand

    for norm_existente in nombres_existentes_normalizados:
        if not norm_existente:
            continue
        # Coincidencia por subcadena relevante (ej: 'elsol' en 'elsolmadrid')
        if len(norm_existente) >= 4 and norm_existente in norm_cand:
            return True, norm_existente
        if len(norm_cand) >= 4 and norm_cand in norm_existente:
            return True, norm_existente

        # Coincidencia por similitud difusa (ratio de caracteres)
        ratio = difflib.SequenceMatcher(None, norm_cand, norm_existente).ratio()
        if ratio >= umbral:
            return True, norm_existente
    return False, norm_cand

def normalizar_tipo(tipo_str):
    """
    Mapea variaciones y plurales de tipos de recinto a una categoría estandarizada.
    (ej: 'discotecas' -> 'discoteca', 'festivales' -> 'festival', 'ayuntamientos' -> 'ayuntamiento')
    """
    t = tipo_str.strip().lower()
    if t in ["ayuntamiento", "ayuntamientos", "concello", "concellos", "municipio", "municipios"]:
        return "ayuntamiento"
    elif t in ["festival", "festivales", "fest", "festis", "ciclo", "ciclos"]:
        return "festival"
    elif t in ["discoteca", "discotecas", "club", "clubes", "sala de baile"]:
        return "discoteca"
    elif t in ["pub", "pubs", "bar", "bares"]:
        return "pub"
    elif t in ["teatro", "teatros", "auditorio", "auditorios"]:
        return "teatro"
    elif t in ["sala", "salas", "sala de conciertos"]:
        return "sala"
    else:
        # Para tipos personalizados, quitar 's' final si parece plural
        if len(t) > 3 and t.endswith("s"):
            return t[:-1]
        return t

def obtener_queries_busqueda(tipo_individual, region, genero=None):
    """
    Genera variaciones de queries de búsqueda en DuckDuckGo añadiendo explícitamente 'España'
    para garantizar la desambiguación geográfica (ej: Guadalajara España vs Guadalajara México).

    `genero` (opcional): filtro de estilo musical (ej. 'reggae') que se inserta en la query
    para acotar la búsqueda a ese género — de momento solo tiene efecto en tipo 'festival'.
    """
    t = tipo_individual.lower().strip()
    region_ctx = region if "españa" in region.lower() or "espana" in region.lower() else f"{region} España"
    genero = (genero or "").strip()

    if t == "ayuntamiento":
        return [
            f"municipios y ayuntamientos de la provincia de {region_ctx}",
            f"concellos ayuntamientos cultura festejos {region_ctx}"
        ]
    elif t == "festival":
        if genero:
            return [
                f"festivales de musica {genero} {region_ctx}",
                f"festival {genero} carteles ediciones {region_ctx}"
            ]
        return [
            f"festivales de musica ciclos conciertos {region_ctx}",
            f"festival de musica eventos carteles {region_ctx}"
        ]
    elif t == "discoteca":
        return [
            f"discotecas clubs de musica salas de baile {region_ctx}",
            f"discotecas clubbing musica en vivo {region_ctx}"
        ]
    elif t == "pub":
        return [
            f"pubs bares de musica en vivo {region_ctx}",
            f"locales musica directo pubs {region_ctx}"
        ]
    elif t == "teatro":
        return [
            f"teatros auditorios recintos culturales {region_ctx}",
            f"teatro auditorio programación conciertos {region_ctx}"
        ]
    elif t == "sala":
        return [
            f"salas de conciertos locales de musica en vivo {region_ctx}",
            f"salas de musica directos programación {region_ctx}"
        ]
    else:
        return [
            f"{t}s recintos de musica conciertos {region_ctx}",
            f"{t}s locales cultura en vivo {region_ctx}"
        ]

def extraer_candidatos_con_ia(resultados, tipo, region, genero=None):
    """
    Utiliza Gemini para analizar snippets de búsqueda y extraer nombres de candidatos estructurados.

    `genero` (opcional): si se especifica, se añade una regla de filtrado estricta para
    descartar candidatos que no sean claramente de ese estilo musical.
    """
    if not resultados:
        return []

    res_str = formatear_snippets(resultados)
    genero = (genero or "").strip()

    regla_genero = (
        f"6. FILTRO DE GÉNERO (CRÍTICO): Extrae ÚNICAMENTE entidades cuya programación esté "
        f"centrada de verdad en el género '{genero}' (según lo que digan los propios snippets). "
        f"Si el snippet no menciona '{genero}' ni nada claramente relacionado, descarta ese "
        "candidato aunque encaje en el tipo general — es mejor devolver menos resultados que "
        "colar festivales de otro estilo.\n"
        if genero else ""
    )

    prompt = (
        f"Analiza los siguientes resultados de búsqueda web para encontrar nombres de {tipo}"
        f"{f' de género {genero}' if genero else ''} en la provincia/región de '{region}' (ESPAÑA):\n\n"
        f"{res_str}\n"
        f"Tu objetivo es extraer una lista de entidades reales de tipo '{tipo}' pertenecientes a la zona geográfica de '{region}' en España.\n"
        "Reglas estrictas:\n"
        f"1. DESAMBIGUACIÓN GEOGRÁFICA (CRÍTICA): Extrae ÚNICAMENTE entidades ubicadas en ESPAÑA. Descarta categóricamente cualquier recinto ubicado fuera de España (ej: si ves 'Guadalajara' pero pertenece a México, NO la incluyas; si ves 'Valencia' pero es de Venezuela o 'Córdoba' de Argentina, NO la incluyas).\n"
        f"2. FILTRO DE IDONEIDAD ARTÍSTICA: Extrae únicamente entidades que celebren eventos culturales, conciertos o música en vivo. Descarta directorios genéricos, agencias o locales comerciales sin actividad de conciertos/eventos.\n"
        f"3. TIPO EXACTO: Extrae únicamente entidades reales que correspondan exactamente al tipo '{tipo}' (ej: si el tipo es 'discoteca', discotecas o clubes de música; si es 'festival', festivales de música; si es 'ayuntamiento', ayuntamientos o concellos; si es 'sala', salas de conciertos).\n"
        "4. GROUNDING: no inventes entidades. Extrae SOLO las que aparezcan explícitamente en los\n"
        "   snippets de arriba. Para cada candidato, 'fuente' debe ser el índice del snippet que lo\n"
        "   respalda (ej: '[3]'). Si no puedes señalar un snippet concreto, NO incluyas ese candidato.\n"
        f"{regla_genero}"
        "5. Devuelve un objeto JSON con este esquema exacto:\n"
        "{\n"
        "  \"candidatos\": [\n"
        "    {\n"
        "      \"nombre\": \"Nombre oficial de la entidad\",\n"
        "      \"ciudad\": \"Localidad/Municipio\",\n"
        "      \"fuente\": \"[n]\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    system_prompt = (
        "Eres un extractor experto de entidades geográficas y culturales a partir de textos de búsqueda. "
        "Tu única salida posible debe ser un objeto JSON válido según el esquema solicitado. "
        "No inventes entidades: si no está en los snippets, no existe para ti."
    )

    ans = gemini_client.generar_texto_gemini(
        prompt=prompt,
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        temperature=0.1,
        forzar_json=True  # JSON mode: respuesta siempre JSON válido, sin fences.
    )
    if not ans:
        return []

    try:
        data = json.loads(ans)
        return data.get("candidatos", [])
    except Exception as e:
        print(f"[scout_descubridor.py] Error al parsear JSON de Gemini: {e}. Respuesta: {ans}")
        return []

def descubrir_y_añadir_leads(region, tipo, limite=10, band_id=BAND_ID_DEFAULT, genero=None):
    """
    Busca leads de uno o varios tipos específicos (separados por comas o lista) en una región/provincia,
    los deduplica contra los existentes en la Google Sheet, y los crea masivamente en estado 'nuevo'.

    `genero` (opcional): filtro de estilo musical (ej. 'reggae') que acota tanto la búsqueda
    como la extracción con IA, y se guarda directamente como 'genero' del lead creado (ya no
    hace falta que scout.py lo adivine después).
    """
    tipos_raw = []
    if isinstance(tipo, (list, tuple)):
        for item in tipo:
            if item:
                tipos_raw.extend([t.strip() for t in str(item).split(",") if t.strip()])
    elif isinstance(tipo, str):
        tipos_raw = [t.strip() for t in tipo.split(",") if t.strip()]
    else:
        tipos_raw = [str(tipo).strip()]

    tipos = []
    for t in tipos_raw:
        norm_t = normalizar_tipo(t)
        if norm_t not in tipos:
            tipos.append(norm_t)

    print(f"[scout_descubridor.py] Iniciando descubrimiento en la región/provincia '{region}' (España) para los tipos: {tipos}")
    
    todos_candidatos = []
    
    # 1. Generar búsquedas variadas (multi-query) y extraer candidatos por cada tipo individual
    for tipo_individual in tipos:
        queries = obtener_queries_busqueda(tipo_individual, region, genero=genero)
        resultados_combinados = []
        urls_vistas = set()

        for q in queries:
            print(f"[scout_descubridor.py] Buscando en DuckDuckGo para tipo '{tipo_individual}' con query: '{q}'...")
            res = buscar_duckduckgo(q, max_results=8)
            for r in res:
                href = r.get("href")
                if href not in urls_vistas:
                    urls_vistas.add(href)
                    resultados_combinados.append(r)

        if not resultados_combinados:
            print(f"[scout_descubridor.py] No se obtuvieron resultados para tipo '{tipo_individual}'. Saltando.")
            continue

        candidatos = extraer_candidatos_con_ia(resultados_combinados, tipo_individual, region, genero=genero)
        print(f"[scout_descubridor.py] IA extrajo {len(candidatos)} posibles candidatos de tipo '{tipo_individual}'.")

        # Guardar la asignación del tipo correspondiente (y el género, si se ha filtrado por uno)
        for c in candidatos:
            c["tipo"] = tipo_individual
            if genero:
                c["genero"] = genero

        todos_candidatos.extend(candidatos)
        
    if not todos_candidatos:
        print("[scout_descubridor.py] No se extrajeron candidatos válidos de ningún tipo.")
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=0, leads_enriquecidos=[])
        return 0
        
    # 2. Cargar leads existentes para deduplicación exacta y difusa
    leads_existentes = sheets.obtener_leads()
    nombres_existentes_normalizados = {normalizar_nombre(l.get("nombre_sala")) for l in leads_existentes if l.get("nombre_sala")}
    
    leads_a_crear = []
    
    for cand in todos_candidatos:
        nombre = cand.get("nombre")
        ciudad = cand.get("ciudad") or region
        fuente_snippet = cand.get("fuente")
        tipo_cand = cand.get("tipo")

        if not nombre:
            continue

        es_dup, norm_nombre = es_duplicado_difuso(nombre, nombres_existentes_normalizados, umbral=0.85)
        if es_dup:
            print(f"[scout_descubridor.py] Ignorando '{nombre}' (Duplicado exacto o difuso de '{norm_nombre}').")
            continue

        # Generar ID de 8 caracteres único para no colisionar
        lead_id = f"lead_{uuid.uuid4().hex[:5]}"

        nuevo_lead = {
            "id": lead_id,
            "nombre_sala": nombre,
            "ciudad": ciudad or region,
            "region": region,  # Guardar la provincia/región real solicitada (ej. Guadalajara, Pontevedra)
            "tipo": tipo_cand,
            "genero": cand.get("genero") or "",
            "band_id": band_id,
            "fuente": f"Scout Descubridor: {region}" + (f" (género: {genero})" if genero else ""),
            "estado": estados.NUEVO,
            "notas": (
                f"Descubierto automáticamente por el agente Scout Descubridor (tipo: {tipo_cand})"
                + (f" (snippet {fuente_snippet})." if fuente_snippet else ".")
                + " Contacto SIN verificar: pendiente de enriquecer por el Scout."
            ),
        }
        
        leads_a_crear.append(nuevo_lead)
        nombres_existentes_normalizados.add(norm_nombre) # Prevenir duplicación en la misma corrida
        
        if len(leads_a_crear) >= limite:
            break
            
    if not leads_a_crear:
        print("[scout_descubridor.py] Todos los candidatos descubiertos ya existían en la Google Sheet.")
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=0, leads_enriquecidos=[])
        return 0
        
    print(f"[scout_descubridor.py] Insertando {len(leads_a_crear)} nuevos leads en la Google Sheet...")
    exito = sheets.crear_leads(leads_a_crear)
    
    if exito:
        print(f"[scout_descubridor.py] Proceso completado. Se añadieron {len(leads_a_crear)} leads.")
        print(f"\n[scout_descubridor.py] Iniciando enriquecimiento automático para los {len(leads_a_crear)} nuevos leads...")
        leads_enriquecidos = []
        try:
            from agents.scout import enriquecer_leads_sin_contacto
            leads_enriquecidos = enriquecer_leads_sin_contacto(limite_leads=len(leads_a_crear), region=region, enviar_webhook=False)
        except Exception as e:
            print(f"[scout_descubridor.py] Error al enriquecer automáticamente: {e}")
        
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=len(leads_a_crear), leads_enriquecidos=leads_enriquecidos)
        return len(leads_a_crear)
    else:
        print("[scout_descubridor.py] Error al insertar leads en la Google Sheet.")
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=0, leads_enriquecidos=[])
        return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente Scout Descubridor para búsqueda activa de leads.")
    parser.add_argument("--region", type=str, required=True, help="Región o Provincia donde buscar.")
    parser.add_argument(
        "--tipo",
        action="append",
        required=True,
        help="Tipo(s) de entidad a buscar. Puedes especificarlo varias veces (--tipo discotecas --tipo festivales) o separado por comas (--tipo 'discotecas,festivales')."
    )
    parser.add_argument("--limit", type=int, default=10, help="Límite máximo de nuevos leads a añadir.")
    parser.add_argument("--banda", type=str, default=BAND_ID_DEFAULT, help="band_id al que pertenecen los leads descubiertos (multi-tenant). Por defecto, band-bakandeya.")
    parser.add_argument("--genero", type=str, default=None, help="Filtro de estilo musical (ej. 'reggae') que acota la búsqueda y se guarda como género del lead. Solo tiene efecto real en tipo 'festival' por ahora.")
    args = parser.parse_args()
    
    descubrir_y_añadir_leads(region=args.region, tipo=args.tipo, limite=args.limit, band_id=args.banda, genero=args.genero)


