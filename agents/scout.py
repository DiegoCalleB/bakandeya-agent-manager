import os
import sys
import json
import time
import random
import urllib.parse
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

import lib.sheets as sheets
import lib.gemini_client as gemini_client
import lib.estados as estados
from lib.busqueda import buscar_duckduckgo, formatear_snippets

# Ranking de niveles de confianza. La IA etiqueta cada dato extraído con uno de estos
# niveles; solo escribimos en la Sheet los que superan su umbral. Los demás se anotan como
# sugerencias para revisión humana. Esto materializa la regla innegociable de verificación.
NIVELES_CONFIANZA = {"alta": 3, "media": 2, "baja": 1}

# Umbral de confianza mínimo para escribir cada campo en la Sheet.
# Estricto en los datos de contacto (con ellos se envía el pitch: no pueden ser inventados)
# y flexible en los datos "blandos" (género/aforo son deducciones por naturaleza, casi nunca
# aparecen literales; exigir 'alta' los dejaría siempre vacíos). El humano verifica todo antes
# de que un lead pase a 'aprobado', así que un blando 'media' no compromete ninguna regla.
UMBRALES_POR_CAMPO = {
    "email": "alta",
    "telefono": "alta",
    "website": "alta",
    "instagram": "alta",
    "genero": "media",
    "aforo": "media",
}


def _procesar_campos_extraidos(data, campos, umbral="alta", umbrales_por_campo=None):
    """
    Separa los campos extraídos por la IA en (aceptados, sugerencias).

    Cada campo en `data` puede venir de dos formas:
      - Estructurado: {"valor": ..., "confianza": "alta|media|baja", "fuente": "[n] o URL"}
      - Plano (retrocompatibilidad con mocks/tests o funciones antiguas): el valor directo.

    El umbral de aceptación se decide por campo: `umbrales_por_campo` (dict {campo: nivel})
    tiene prioridad y, si un campo no está ahí, se usa `umbral` como valor por defecto.

    Devuelve:
      - aceptados: dict {campo: valor} SOLO con los datos que superan su umbral.
      - sugerencias: lista de strings legibles con los datos de confianza insuficiente,
        para dejarlos en `notas` sin escribirlos como si fueran verificados.
    """
    umbrales_por_campo = umbrales_por_campo or {}
    aceptados = {}
    sugerencias = []

    for campo in campos:
        item = data.get(campo)
        if item is None:
            continue

        if isinstance(item, dict):
            valor = item.get("valor")
            confianza = str(item.get("confianza") or "baja").lower()
            fuente = item.get("fuente")
        else:
            # Valor plano: asumimos que viene de una fuente ya fiable (retrocompatibilidad).
            valor = item
            confianza = "alta"
            fuente = None

        # Descartar vacíos y nulos textuales ("null", "none", "n/a"...).
        if valor is None or str(valor).strip().lower() in ("", "null", "none", "n/a"):
            continue

        umbral_num = NIVELES_CONFIANZA.get(umbrales_por_campo.get(campo, umbral), 3)
        if NIVELES_CONFIANZA.get(confianza, 1) >= umbral_num:
            aceptados[campo] = valor
        else:
            sugerencias.append(f"{campo}={valor} (confianza {confianza}, fuente {fuente or '?'})")

    return aceptados, sugerencias


def _combinar(destino, nuevos, campos):
    """
    Rellena en `destino` (dict acumulador) los `campos` que aún estén vacíos con los
    valores de `nuevos`. Primera fuente que aporta un dato válido gana; no sobrescribe.
    """
    for campo in campos:
        if not destino.get(campo) and nuevos.get(campo):
            destino[campo] = nuevos[campo]


def inferir_tipo_lead(nombre_lead):
    """
    Infiere si el lead es una 'sala', un 'festival' o un 'ayuntamiento' basándose en palabras clave.
    """
    nombre_lower = nombre_lead.lower()
    
    # Palabras clave para Ayuntamiento
    keywords_ayto = ["ayuntamiento", "concello", "ayto", "concejo", "patronato", "municipio", "alcaldia", "alcaldía", "diputacion", "diputación"]
    if any(k in nombre_lower for k in keywords_ayto):
        return "ayuntamiento"
        
    # Palabras clave para Festival
    keywords_fest = ["festival", "fest", "festi", "ciclo", "muestra", "encontro", "xacobeo"]
    if any(k in nombre_lower for k in keywords_fest):
        return "festival"
        
    return "sala"

def seleccionar_web_oficial_con_ia(nombre_sala, ciudad, resultados):
    """
    Analiza los resultados de búsqueda de DuckDuckGo usando Gemini para seleccionar
    únicamente el enlace que sea la web oficial de la sala/festival o ayuntamiento.
    Ignora blogs, guías turísticas (como EuroCheapo, TripAdvisor), directorios o noticias de prensa.
    """
    res_str = formatear_snippets(resultados)
        
    prompt = (
        f"Analiza los siguientes resultados de búsqueda en la web para encontrar la web oficial de la sala o festival '{nombre_sala}' en '{ciudad}':\n\n"
        f"{res_str}\n"
        "Reglas:\n"
        "1. Selecciona la URL que es estrictamente la web oficial de la sala, festival, local o del ayuntamiento (si es un festival municipal).\n"
        "2. Ignora directorios genéricos (Yelp, TripAdvisor, Facebook, Instagram, Páginas Amarillas, Taquilla.com, etc.).\n"
        "3. Ignora blogs, artículos de noticias (como Marca, periódicos), portales de turismo genéricos (ej: EuroCheapo, esmadrid.com) o guías de conciertos.\n"
        "4. Devuelve únicamente la URL seleccionada en texto plano sin explicaciones, sin comillas ni markdown. Si consideras que ninguno de los enlaces corresponde a la web oficial del local/evento, devuelve únicamente la palabra 'NULL'."
    )
    
    try:
        ans = gemini_client.generar_texto_gemini(
            prompt=prompt,
            model_name="gemini-2.5-flash",
            temperature=0.1
        )
        if ans:
            ans_clean = ans.strip().strip("`").strip()
            if ans_clean.upper() == "NULL" or "http" not in ans_clean:
                return None
            return ans_clean
        return None
    except Exception as e:
        print(f"[scout.py] Error al seleccionar web oficial con IA: {e}")
        return None

def extraer_datos_contacto_de_snippets(nombre_sala, ciudad, resultados, tipo="sala"):
    """
    Analiza los títulos y snippets de DuckDuckGo usando Gemini para extraer de forma directa
    email, teléfono, instagram y el enlace oficial (web o red social).
    """
    if not resultados:
        return {}
        
    res_str = formatear_snippets(resultados)
        
    if tipo == "ayuntamiento":
        objetivo_contacto = (
            "Tu objetivo es extraer la información de contacto oficial de la concejalía de cultura, festejos o del propio ayuntamiento:\n"
            "1. email: El email de contacto, programación, cultura o festejos del ayuntamiento (ej: cultura@..., festejos@..., prensa@..., info@..., o el correo principal si no hay otro).\n"
            "2. telefono: El teléfono oficial de contacto de las oficinas del ayuntamiento.\n"
            "3. instagram: El usuario de Instagram oficial del ayuntamiento o de su concejalía de cultura (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a la web oficial del ayuntamiento o portal de festejos/turismo.\n"
            "5. genero: Pon siempre 'Varios / Festivo'.\n"
            "6. aforo: Pon siempre null."
        )
    elif tipo == "festival":
        objetivo_contacto = (
            "Tu objetivo es extraer la información de contacto oficial del festival:\n"
            "1. email: El email de contacto oficial para booking, contratación, envío de propuestas, prensa o información general del festival.\n"
            "2. telefono: El teléfono oficial de contacto del festival/organización.\n"
            "3. instagram: El usuario de Instagram oficial del festival (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a la web oficial del festival.\n"
            "5. genero: El estilo o género musical predominante del festival (ej: 'Indie / Pop', 'Electrónica', 'Folk', etc.).\n"
            "6. aforo: La capacidad o aforo del recinto del festival (número entero, o null si no se menciona)."
        )
    else:
        objetivo_contacto = (
            "Tu objetivo es extraer cualquier información de contacto oficial de este local o evento:\n"
            "1. email: El email de contacto/programación oficial de la sala.\n"
            "2. telefono: El teléfono de contacto oficial.\n"
            "3. instagram: El usuario de Instagram (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a su canal oficial real (puede ser su web oficial .com/.es, o su página oficial de Facebook o de Instagram si no tiene web independiente).\n"
            "5. genero: El estilo o género musical habitual de la sala, indicando los estilos predominantes específicos si se mencionan en los resultados (ej: 'Rock / Metal', 'Balkan / Ska / Reggae', 'Indie Pop', etc. Evita poner simplemente 'Varios' a menos que no exista otra información).\n"
            "6. aforo: El aforo de la sala (capacidad máxima de personas) si se menciona en los resultados (número entero, o null si no se menciona)."
        )

    prompt = (
        f"Analiza los siguientes snippets de resultados de búsqueda web para la entidad '{nombre_sala}' (tipo: {tipo}) en '{ciudad}':\n\n"
        f"{res_str}\n"
        f"{objetivo_contacto}\n\n"
        "Reglas:\n"
        "- Extrae solo datos de contacto reales de la entidad, no de empresas terceras ni directorios de entradas genéricos.\n"
        "- Para CADA dato indica tu nivel de confianza y de dónde lo sacaste:\n"
        "    * confianza='alta' solo si el dato aparece literal y claramente asociado a ESTA entidad en los snippets.\n"
        "    * confianza='media' si lo deduces de forma razonable pero no es literal.\n"
        "    * confianza='baja' si es una suposición. NUNCA inventes un dato con confianza alta.\n"
        "    * fuente = el índice del snippet que respalda el dato (ej: '[2]'), o null si no lo viste.\n"
        "- Si no encuentras un campo, pon valor=null y confianza='baja'.\n"
        "- Devuelve un objeto JSON con este esquema exacto (cada campo es un objeto con valor/confianza/fuente):\n"
        "{\n"
        "  \"email\":     {\"valor\": \"email o null\",     \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"telefono\":  {\"valor\": \"telefono o null\",  \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"instagram\": {\"valor\": \"instagram o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"website\":   {\"valor\": \"url o null\",       \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"genero\":    {\"valor\": \"genero o null\",    \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"aforo\":     {\"valor\": \"aforo o null\",     \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"}\n"
        "}"
    )

    ans = gemini_client.generar_texto_gemini(
        prompt=prompt,
        model_name="gemini-2.5-flash",
        temperature=0.1,
        forzar_json=True  # JSON mode: la respuesta es siempre JSON válido, sin fences.
    )
    if not ans:
        return {}

    try:
        data = json.loads(ans)
    except Exception as e:
        print(f"[scout.py] Error al parsear JSON de Gemini (snippets): {e}. Respuesta: {ans}")
        return {}

    aceptados, sugerencias = _procesar_campos_extraidos(
        data, campos=["email", "telefono", "instagram", "website", "genero", "aforo"],
        umbrales_por_campo=UMBRALES_POR_CAMPO,
    )
    if sugerencias:
        aceptados["_sugerencias"] = sugerencias
    return aceptados

def buscar_web_sala(nombre_sala, ciudad):
    """
    Busca en DuckDuckGo la web oficial de la sala y devuelve el primer resultado relevante usando la librería ddgs.
    """
    results = buscar_duckduckgo(f"{nombre_sala} {ciudad} web oficial contacto", max_results=5)
    if not results:
        return None
        
    web_oficial = seleccionar_web_oficial_con_ia(nombre_sala, ciudad, results)
    if web_oficial:
        print(f"[scout.py] IA seleccionó la web oficial: {web_oficial}")
        return web_oficial
        
    print(f"[scout.py] IA determinó que no hay web oficial en los resultados.")
    return None

def descargar_texto_pagina(url):
    """
    Descarga el contenido de una URL, extrae su texto plano limpio y enlaces comunes de contacto.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code != 200:
            print(f"[scout.py] No se pudo descargar la página (Status {response.status_code}): {url}")
            return "", []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Eliminar scripts y estilos
        for script in soup(["script", "style"]):
            script.decompose()
            
        texto = soup.get_text(separator="\n")
        # Limpiar espacios en blanco innecesarios
        lineas = (line.strip() for line in texto.splitlines())
        chunks = (phrase.strip() for line in lineas for phrase in line.split("  "))
        texto_limpio = "\n".join(chunk for chunk in chunks if chunk)
        
        # Buscar enlaces de contacto alternativos en la web (aviso legal, contacto, etc.)
        enlaces_contacto = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            href_lower = href.lower()
            if any(term in href_lower for term in ["contact", "aviso", "legal", "nosotros", "quienes", "info"]):
                abs_url = urllib.parse.urljoin(url, href)
                enlaces_contacto.append(abs_url)
                
        return texto_limpio[:4000], list(set(enlaces_contacto))[:3]
    except Exception as e:
        print(f"[scout.py] Error al descargar {url}: {e}")
        return "", []

def extraer_datos_contacto(texto, url_origen, tipo="sala"):
    """
    Utiliza Gemini para extraer email, teléfono, instagram y aforo a partir de texto de la web.
    """
    if not texto.strip():
        return {}
        
    if tipo == "ayuntamiento":
        objetivo_contacto = (
            "1. Para el aforo: pon null (los ayuntamientos no tienen aforo fijo, aunque puedes ignorarlo).\n"
            "2. Para el email: extrae el correo de la concejalía de cultura, de festejos, de juventud o el general del ayuntamiento (ej: cultura@..., festejos@..., concejalia.cultura@..., info@...).\n"
            "3. Para el genero: extrae o infiere el tipo de música (pon 'Varios / Festivo')."
        )
    elif tipo == "festival":
        objetivo_contacto = (
            "1. Para el aforo: busca la capacidad del recinto del festival o asistencia estimada. Si es numérico ponlo como integer, si no pon null.\n"
            "2. Para el email: extrae el correo de contratación, booking, propuestas artísticas, producción o el de información general.\n"
            "3. Para el genero: extrae o infiere el estilo musical predominante del festival, indicando los géneros específicos (ej: 'Indie Pop', 'Folk Rock', etc.)."
        )
    else:
        objetivo_contacto = (
            "1. Para el aforo: busca menciones del tamaño de la sala, capacidad, limitación de personas o aforo. Si es numérico ponlo como integer, si no pon null.\n"
            "2. Para el email: extrae solo correos corporativos o de contacto profesional de la sala (ej: programacion@..., info@..., contacto@...).\n"
            "3. Para el genero: extrae o infiere el estilo o género musical habitual de la sala, detallando los estilos predominantes de forma específica (ej: 'Rock / Metal', 'Balkan / Ska / Reggae', 'Electrónica / Techno', etc. Evita poner 'Varios' a menos que no exista otra información)."
        )

    prompt = (
        f"Analiza el siguiente texto plano extraído de la página web '{url_origen}' de la entidad (tipo: {tipo}) y extrae la información de contacto:\n\n"
        f"{texto}\n\n"
        "Reglas:\n"
        f"{objetivo_contacto}\n"
        "- Para CADA dato indica confianza y fuente:\n"
        "    * confianza='alta' solo si el dato aparece literal en el texto de la web.\n"
        "    * confianza='media' si lo deduces razonablemente; 'baja' si es una suposición.\n"
        "    * NUNCA inventes un dato con confianza alta. fuente = fragmento/sección donde aparece, o null.\n"
        "- Si no encuentras un campo, pon valor=null y confianza='baja'.\n"
        "- Devuelve un objeto JSON con este esquema exacto (cada campo es un objeto valor/confianza/fuente):\n"
        "{\n"
        '  "email":     {"valor": "correo@sala.com o null", "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "telefono":  {"valor": "+34... o null",          "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "instagram": {"valor": "@usuario o null",        "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "aforo":     {"valor": 300,                       "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "genero":    {"valor": "genero o null",          "confianza": "alta|media|baja", "fuente": "texto o null"}\n'
        "}"
    )

    system_prompt = (
        "Eres un analizador de textos web experto en extracción de datos de contacto. "
        "Tu única salida posible debe ser un objeto JSON válido según el esquema solicitado."
    )

    respuesta = gemini_client.generar_texto_gemini(
        prompt,
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        temperature=0.2,
        forzar_json=True  # JSON mode: respuesta siempre JSON válido, sin fences.
    )

    if not respuesta:
        return {}

    try:
        data = json.loads(respuesta)
    except Exception as e:
        print(f"[scout.py] Error al parsear JSON de Gemini (web): {e}. Respuesta: {respuesta}")
        return {}

    aceptados, sugerencias = _procesar_campos_extraidos(
        data, campos=["email", "telefono", "instagram", "aforo", "genero"],
        umbrales_por_campo=UMBRALES_POR_CAMPO,
    )
    if sugerencias:
        aceptados["_sugerencias"] = sugerencias
    return aceptados

def obtener_mapa_regiones_ciudades(ciudades):
    """
    Usa Gemini para mapear una lista de ciudades de España a su Provincia y Comunidad Autónoma.
    Esto permite filtrar leads por región/provincia de forma inteligente (ej: detectar que
    Pamplona y Tudela pertenecen a Navarra).
    """
    if not ciudades:
        return {}
        
    prompt = (
        "Dada la siguiente lista de ciudades/municipios de España, asocia cada una con su Provincia y su Comunidad Autónoma correspondiente.\n"
        f"Ciudades: {json.dumps(ciudades)}\n\n"
        "Devuelve únicamente un objeto JSON con el siguiente formato exacto, sin explicaciones ni markdown:\n"
        "{\n"
        "  \"Nombre de la ciudad\": {\"provincia\": \"nombre_provincia\", \"comunidad\": \"nombre_comunidad\"}\n"
        "}"
    )
    
    try:
        res = gemini_client.generar_texto_gemini(
            prompt=prompt,
            model_name="gemini-2.5-flash",
            temperature=0.1,
            forzar_json=True
        )
        if res:
            return json.loads(res)
    except Exception as e:
        print(f"[scout.py] Error al mapear regiones de ciudades con IA: {e}")
    return {}


def enriquecer_leads_sin_contacto(limite_leads=3, region=None):
    """
    Busca leads en la Google Sheet que tengan datos incompletos (especialmente email_contacto)
    y los enriquece de forma exhaustiva.
    
    Si se busca por región (ej. manual/chatbot), permite cargar leads en estados:
      - nuevo (si le falta email, teléfono, web o instagram)
      - pendiente_aprobacion (solo si le falta el email de contacto)
      - sin_contacto (para reintentar enriquecimiento, solo si le falta el email)
    Si no hay filtro de región (cron rutinario):
      - nuevo (si le falta algún dato de contacto)
      - pendiente_aprobacion (solo si le falta el email)
    """
    print("[scout.py] Iniciando proceso de enriquecimiento de leads...")
    
    if region:
        # Cargar todos los leads e incluir los estados correspondientes
        leads_todos = sheets.obtener_leads()
        estados_permitidos = [estados.NUEVO, estados.PENDIENTE, estados.SIN_CONTACTO]
        leads = [l for l in leads_todos if l.get("estado") in estados_permitidos]
    else:
        # Cargar sólo 'nuevo' y 'pendiente_aprobacion' si carece de email
        leads_nuevos = sheets.obtener_leads(estado=estados.NUEVO)
        leads_todos = sheets.obtener_leads()
        leads_pendientes_sin_email = [
            l for l in leads_todos 
            if l.get("estado") == estados.PENDIENTE and not l.get("email_contacto")
        ]
        leads = leads_nuevos + leads_pendientes_sin_email
    
    if region:
        # Extraer ciudades únicas de los leads para consultar a la IA a qué provincia/comunidad pertenecen
        ciudades_unicas = list(set([str(l.get("ciudad")).strip() for l in leads if l.get("ciudad")]))
        mapa_regiones = obtener_mapa_regiones_ciudades(ciudades_unicas)
        
        region_clean = region.strip().lower()
        leads_filtrados = []
        
        for l in leads:
            ciudad = str(l.get("ciudad") or "").strip()
            reg_col = str(l.get("region") or "").strip().lower()
            ciudad_col = ciudad.lower()
            
            # 1. Comprobación directa (si el texto coincide con la columna region o ciudad)
            match_directo = region_clean in reg_col or region_clean in ciudad_col
            
            # 2. Comprobación de provincia o comunidad autónoma mediante mapa de IA de la ciudad
            match_ia = False
            info_ciudad = mapa_regiones.get(ciudad)
            if info_ciudad:
                provincia = str(info_ciudad.get("provincia") or "").lower()
                comunidad = str(info_ciudad.get("comunidad") or "").lower()
                match_ia = region_clean in provincia or region_clean in comunidad
                
            if match_directo or match_ia:
                leads_filtrados.append(l)
                
        leads = leads_filtrados
        print(f"[scout.py] Filtrando leads para la región/ciudad/provincia: '{region}'. Encontrados: {len(leads)}")
        
    # Filtrar leads a los que les falte algún dato clave según su estado
    leads_incompletos = []
    for l in leads:
        falta_email = not l.get("email_contacto")
        falta_tel = not l.get("telefono")
        falta_web = not l.get("website")
        falta_insta = not l.get("instagram")
        
        # Para leads 'nuevo', enriquecemos si falta cualquier dato básico de contacto
        if l.get("estado") == estados.NUEVO:
            if falta_email or falta_tel or falta_web or falta_insta:
                leads_incompletos.append(l)
        # Para leads 'pendiente_aprobacion' o 'sin_contacto', enriquecemos solo si les falta el email de contacto (crítico)
        else:
            if falta_email:
                leads_incompletos.append(l)
            
    print(f"[scout.py] Se encontraron {len(leads_incompletos)} leads incompletos a procesar.")
    
    if not leads_incompletos:
        print("[scout.py] No hay leads incompletos para enriquecer.")
        return 0
        
    enriquecidos = 0
    leads_a_procesar = leads_incompletos[:limite_leads]
    
    for lead in leads_a_procesar:
        lead_id = lead.get("id")
        nombre_sala = lead.get("nombre_sala")
        ciudad = lead.get("ciudad")
        
        # Obtener o inferir el tipo de lead
        tipo = lead.get("tipo")
        if not tipo or tipo.strip() == "":
            tipo = inferir_tipo_lead(nombre_sala)
            print(f"[scout.py] Tipo de lead no especificado. Inferido como: {tipo}")
        else:
            tipo = tipo.strip().lower()
            
        print(f"\n[scout.py] >>> Procesando '{nombre_sala}' ({ciudad}) [Tipo: {tipo}] [ID: {lead_id}]")
        
        # Acumulador de datos aceptados (ya filtrados por confianza en cada extractor).
        # Primera fuente que aporta un dato válido gana; _combinar no sobrescribe.
        datos = {}
        # Datos de confianza insuficiente: se juntan aquí para dejarlos en 'notas' como pistas
        # a verificar, nunca en los campos verificados de la Sheet.
        sugerencias_totales = []
        CAMPOS = ["email", "telefono", "instagram", "website", "genero", "aforo"]

        # 1. Una única búsqueda amplia + extracción estructurada desde snippets.
        # Antes había hasta 4 búsquedas y 6 llamadas a la IA por lead; ahora arrancamos con 1
        # de cada y solo profundizamos si falta el dato crítico (email).
        if tipo == "ayuntamiento":
            query_busqueda = f"{nombre_sala} concejalía festejos cultura contacto email telefono"
        elif tipo == "festival":
            query_busqueda = f"{nombre_sala} contacto booking contratacion email telefono"
        else:
            query_busqueda = f"{nombre_sala} {ciudad} web oficial contacto email telefono aforo"

        results = buscar_duckduckgo(query_busqueda, max_results=8)
        datos_snippets = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results, tipo=tipo)
        sugerencias_totales.extend(datos_snippets.get("_sugerencias") or [])
        _combinar(datos, datos_snippets, CAMPOS)

        # 2. Si la web es standalone (no red social), descargamos su HTML: es la mejor fuente
        # de aforo y género (datos que rara vez salen en un snippet).
        web = datos.get("website")
        is_social = bool(web) and any(
            s in web.lower() for s in ["facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com"]
        )

        if web and not is_social:
            print(f"[scout.py] Intentando descargar web oficial: {web}")
            texto_home, paginas_contacto = descargar_texto_pagina(web)

            if texto_home:
                datos_web = extraer_datos_contacto(texto_home, web, tipo=tipo)
                sugerencias_totales.extend(datos_web.get("_sugerencias") or [])
                _combinar(datos, datos_web, CAMPOS)

                # Profundizamos en la página de contacto solo si aún falta email o aforo
                # (el email es crítico; el aforo casi siempre vive en "el local"/"sobre nosotros").
                if (not datos.get("email") or not datos.get("aforo")) and paginas_contacto:
                    url_contacto = paginas_contacto[0]
                    print(f"[scout.py] Buscando en página de contacto: {url_contacto}")
                    texto_contacto, _ = descargar_texto_pagina(url_contacto)
                    datos_contacto = extraer_datos_contacto(texto_contacto, url_contacto, tipo=tipo)
                    sugerencias_totales.extend(datos_contacto.get("_sugerencias") or [])
                    _combinar(datos, datos_contacto, CAMPOS)
        elif is_social:
            print(f"[scout.py] Canal oficial es red social ({web}), omitiendo scraping directo.")
        else:
            print(f"[scout.py] No se encontró web oficial standalone para descargar.")

        # 3. Fallback dirigido: solo si sigue faltando el email (el único dato imprescindible).
        # No gastamos una búsqueda extra por un teléfono o un instagram que faltan.
        if not datos.get("email"):
            print(f"[scout.py] Fallback: buscando específicamente el email de contacto de '{nombre_sala}'...")
            if tipo == "ayuntamiento":
                query_fallback = f"{nombre_sala} concejalía cultura correo electrónico"
            elif tipo == "festival":
                query_fallback = f"{nombre_sala} enviar propuesta artistas mail"
            else:
                query_fallback = f"{nombre_sala} {ciudad} contacto email correo telefono"

            results_fallback = buscar_duckduckgo(query_fallback, max_results=8)
            if results_fallback:
                datos_fallback = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results_fallback, tipo=tipo)
                sugerencias_totales.extend(datos_fallback.get("_sugerencias") or [])
                _combinar(datos, datos_fallback, CAMPOS)

        # 4. Formatear y guardar los resultados
        def _limpiar(v):
            return v.strip() if isinstance(v, str) else v

        email = _limpiar(datos.get("email"))
        telefono = _limpiar(datos.get("telefono"))
        instagram = _limpiar(datos.get("instagram"))
        web = _limpiar(datos.get("website"))
        genero = _limpiar(datos.get("genero"))
        aforo = datos.get("aforo")

        # Validar formato básico de email
        if email and "@" not in email:
            email = None

        if email or telefono or instagram or web or genero:
            print(f"[scout.py] [SUCCESS] Datos encontrados - Email: {email or 'N/A'}, Teléfono: {telefono or 'N/A'}, Instagram: {instagram or 'N/A'}, Web: {web or 'N/A'}, Género: {genero or 'N/A'}")
            
            notas_previas = lead.get("notas") or ""
            nuevas_notas = (
                f"{notas_previas} | Scout enriquecido: "
                f"Teléfono: {telefono or 'N/A'}. "
                f"Instagram: {instagram or 'N/A'}. "
                f"Web: {web or 'N/A'}."
            ).strip()

            # Datos de confianza insuficiente: se anotan para revisión humana, NO se escriben
            # en los campos verificados de la Sheet.
            if sugerencias_totales:
                nuevas_notas += " | A verificar (baja confianza): " + "; ".join(sugerencias_totales)
            
            datos_actualizar = {
                "notas": nuevas_notas
            }
            
            # Guardar el tipo inferido/detectado
            if not lead.get("tipo"):
                datos_actualizar["tipo"] = tipo
                
            if email and not lead.get("email_contacto"):
                datos_actualizar["email_contacto"] = email
            if telefono and not lead.get("telefono"):
                datos_actualizar["telefono"] = telefono
            if web and not lead.get("website"):
                datos_actualizar["website"] = web
            if instagram and not lead.get("instagram"):
                datos_actualizar["instagram"] = instagram
            if genero and (not lead.get("genero") or lead.get("genero").strip() == ""):
                datos_actualizar["genero"] = genero
                
            if aforo and (not lead.get("aforo") or int(lead.get("aforo")) == 0):
                print(f"[scout.py] Aforo detectado: {aforo} personas.")
                datos_actualizar["aforo"] = aforo
                
            res = sheets.actualizar_datos_lead(lead_id, datos_actualizar)
            if res:
                enriquecidos += 1

            # Coordinación de estados: si tras enriquecer sigue SIN email, el redactor no puede
            # trabajar el lead. Lo sacamos de 'nuevo' a 'sin_contacto' para que no se reintente
            # en cada ejecución del cron. (El teléfono/web encontrados se conservan.)
            email_final = lead.get("email_contacto") or email
            if not email_final:
                estados.transicionar(lead, estados.SIN_CONTACTO)
        else:
            print(f"[scout.py] [ERROR] No se logró extraer ningún dato de contacto para '{nombre_sala}'.")
            notas_previas = lead.get("notas") or ""

            # Guardar el tipo inferido/detectado aunque falle el enriquecimiento
            if not lead.get("tipo"):
                sheets.actualizar_datos_lead(lead_id, {"tipo": tipo})

            # Sin ningún contacto: a 'sin_contacto' (terminal), fuera del bucle de reintentos.
            estados.transicionar(
                lead, estados.SIN_CONTACTO,
                notas=f"{notas_previas} | Scout: búsqueda exhaustiva sin resultados de contacto.",
            )
            
        # Respetar rate limits
        delay = random.uniform(3, 5)
        time.sleep(delay)
        
    print(f"\n[scout.py] Enriquecimiento finalizado. Leads completados con éxito: {enriquecidos}")
    return enriquecidos

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agente Scout para enriquecer leads.")
    parser.add_argument("--limit", type=int, default=3, help="Límite de leads a procesar.")
    parser.add_argument("--all", action="store_true", help="Procesar todos los leads incompletos.")
    parser.add_argument("--region", type=str, default=None, help="Filtrar por región o provincia.")
    args = parser.parse_args()
    
    limite = 99999 if args.all else args.limit
    enriquecer_leads_sin_contacto(limite_leads=limite, region=args.region)
