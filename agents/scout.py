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

# Ranking de niveles de confianza. La IA etiqueta cada dato extraído con uno de estos
# niveles; solo escribimos en la Sheet los de confianza "alta". Los demás se anotan como
# sugerencias para revisión humana. Esto materializa la regla innegociable de verificación.
NIVELES_CONFIANZA = {"alta": 3, "media": 2, "baja": 1}


def _procesar_campos_extraidos(data, campos, umbral="alta"):
    """
    Separa los campos extraídos por la IA en (aceptados, sugerencias).

    Cada campo en `data` puede venir de dos formas:
      - Estructurado: {"valor": ..., "confianza": "alta|media|baja", "fuente": "[n] o URL"}
      - Plano (retrocompatibilidad con mocks/tests o funciones antiguas): el valor directo.

    Devuelve:
      - aceptados: dict {campo: valor} SOLO con los datos de confianza >= umbral.
      - sugerencias: lista de strings legibles con los datos de confianza insuficiente,
        para dejarlos en `notas` sin escribirlos como si fueran verificados.
    """
    aceptados = {}
    sugerencias = []
    umbral_num = NIVELES_CONFIANZA.get(umbral, 3)

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

        if NIVELES_CONFIANZA.get(confianza, 1) >= umbral_num:
            aceptados[campo] = valor
        else:
            sugerencias.append(f"{campo}={valor} (confianza {confianza}, fuente {fuente or '?'})")

    return aceptados, sugerencias


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
    res_str = ""
    for idx, r in enumerate(resultados, 1):
        res_str += f"[{idx}] Título: {r.get('title')}\n    URL: {r.get('href')}\n    Snippet: {r.get('body')}\n\n"
        
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

def obtener_resultados_busqueda(query, max_results=8):
    """
    Realiza una búsqueda en DuckDuckGo y devuelve la lista de resultados usando la librería ddgs.
    """
    from ddgs import DDGS
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"[scout.py] Error al buscar '{query}': {e}")
        return []

def extraer_datos_contacto_de_snippets(nombre_sala, ciudad, resultados, tipo="sala"):
    """
    Analiza los títulos y snippets de DuckDuckGo usando Gemini para extraer de forma directa
    email, teléfono, instagram y el enlace oficial (web o red social).
    """
    if not resultados:
        return {}
        
    res_str = ""
    for idx, r in enumerate(resultados, 1):
        res_str += f"[{idx}] Título: {r.get('title')}\n    URL: {r.get('href')}\n    Snippet: {r.get('body')}\n\n"
        
    if tipo == "ayuntamiento":
        objetivo_contacto = (
            "Tu objetivo es extraer la información de contacto oficial de la concejalía de cultura, festejos o del propio ayuntamiento:\n"
            "1. email: El email de contacto, programación, cultura o festejos del ayuntamiento (ej: cultura@..., festejos@..., prensa@..., info@..., o el correo principal si no hay otro).\n"
            "2. telefono: El teléfono oficial de contacto de las oficinas del ayuntamiento.\n"
            "3. instagram: El usuario de Instagram oficial del ayuntamiento o de su concejalía de cultura (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a la web oficial del ayuntamiento o portal de festejos/turismo.\n"
            "5. genero: Pon siempre 'Varios / Festivo'."
        )
    elif tipo == "festival":
        objetivo_contacto = (
            "Tu objetivo es extraer la información de contacto oficial del festival:\n"
            "1. email: El email de contacto oficial para booking, contratación, envío de propuestas, prensa o información general del festival.\n"
            "2. telefono: El teléfono oficial de contacto del festival/organización.\n"
            "3. instagram: El usuario de Instagram oficial del festival (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a la web oficial del festival.\n"
            "5. genero: El estilo o género musical predominante del festival (ej: 'Indie / Pop', 'Electrónica', 'Folk', etc.)."
        )
    else:
        objetivo_contacto = (
            "Tu objetivo es extraer cualquier información de contacto oficial de este local o evento:\n"
            "1. email: El email de contacto/programación oficial de la sala.\n"
            "2. telefono: El teléfono de contacto oficial.\n"
            "3. instagram: El usuario de Instagram (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a su canal oficial real (puede ser su web oficial .com/.es, o su página oficial de Facebook o de Instagram si no tiene web independiente).\n"
            "5. genero: El estilo o género musical habitual de la sala (ej: 'Rock / Indie', 'Jazz / Blues', 'Comercial / Pop', 'Varios', etc.)."
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
        "  \"genero\":    {\"valor\": \"genero o null\",    \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"}\n"
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
        data, campos=["email", "telefono", "instagram", "website", "genero"]
    )
    if sugerencias:
        aceptados["_sugerencias"] = sugerencias
    return aceptados

def buscar_web_sala(nombre_sala, ciudad):
    """
    Busca en DuckDuckGo la web oficial de la sala y devuelve el primer resultado relevante usando la librería ddgs.
    """
    results = obtener_resultados_busqueda(f"{nombre_sala} {ciudad} web oficial contacto", max_results=5)
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
            "3. Para el genero: extrae o infiere el estilo musical predominante del festival."
        )
    else:
        objetivo_contacto = (
            "1. Para el aforo: busca menciones del tamaño de la sala, capacidad, limitación de personas o aforo. Si es numérico ponlo como integer, si no pon null.\n"
            "2. Para el email: extrae solo correos corporativos o de contacto profesional de la sala (ej: programacion@..., info@..., contacto@...).\n"
            "3. Para el genero: extrae o infiere el estilo o género musical habitual de la sala (ej: 'Rock / Indie', 'Metal', 'Jazz', etc.)."
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
        data, campos=["email", "telefono", "instagram", "aforo", "genero"]
    )
    if sugerencias:
        aceptados["_sugerencias"] = sugerencias
    return aceptados

def buscar_aforo_especifico(nombre_sala, ciudad):
    """
    Realiza una búsqueda en DuckDuckGo dirigida a encontrar el aforo o capacidad del local
    y lo extrae usando Gemini.
    """
    query = f"{nombre_sala} {ciudad} aforo capacidad personas"
    print(f"[scout.py] Buscando aforo específico con query: '{query}'...")
    resultados = obtener_resultados_busqueda(query, max_results=5)
    if not resultados:
        return None
        
    res_str = ""
    for idx, r in enumerate(resultados, 1):
        res_str += f"[{idx}] Título: {r.get('title')}\n    Snippet: {r.get('body')}\n\n"
        
    prompt = (
        f"Analiza los siguientes snippets de resultados de búsqueda para encontrar el aforo, capacidad máxima de personas o limitación de espacio de la sala de conciertos '{nombre_sala}' en '{ciudad}':\n\n"
        f"{res_str}\n"
        "Reglas:\n"
        "1. Extrae únicamente el número entero que representa la capacidad de personas (ej. si dice 'aforo de 300 personas', devuelve 300).\n"
        "2. Si hay múltiples espacios con distintos aforos, selecciona el principal o el de la sala de conciertos.\n"
        "3. Devuelve únicamente el número entero en texto plano. Si no se menciona ningún aforo o capacidad numérica razonable, devuelve únicamente 'NULL'."
    )
    
    try:
        ans = gemini_client.generar_texto_gemini(
            prompt=prompt,
            model_name="gemini-2.5-flash",
            temperature=0.1
        )
        if ans:
            ans_clean = ans.strip().upper()
            if "NULL" in ans_clean:
                return None
            digits = "".join(c for c in ans_clean if c.isdigit())
            if digits:
                return int(digits)
        return None
    except Exception as e:
        print(f"[scout.py] Error al extraer aforo específico: {e}")
        return None

def buscar_genero_especifico(nombre_sala, ciudad, tipo):
    """
    Realiza una búsqueda en DuckDuckGo dirigida a encontrar el estilo/género musical principal
    que programa la sala o festival y lo extrae con Gemini.
    """
    if tipo == "ayuntamiento":
        return "Varios / Festivo"
        
    query = f"{nombre_sala} {ciudad} estilo musical programación conciertos género"
    print(f"[scout.py] Buscando género específico con query: '{query}'...")
    resultados = obtener_resultados_busqueda(query, max_results=5)
    if not resultados:
        return None
        
    res_str = ""
    for idx, r in enumerate(resultados, 1):
        res_str += f"[{idx}] Título: {r.get('title')}\n    Snippet: {r.get('body')}\n\n"
        
    prompt = (
        f"Analiza los siguientes snippets de resultados de búsqueda para determinar qué estilo o género de música (ej: Rock, Indie, Electrónica, Jazz, Pop, etc.) se programa habitualmente en la entidad '{nombre_sala}' en '{ciudad}':\n\n"
        f"{res_str}\n"
        "Reglas:\n"
        "1. Identifica el género o géneros musicales dominantes (ej: 'Rock / Indie', 'Jazz', 'Electrónica / Techno', 'Pop').\n"
        "2. Sé breve y conciso (máximo 3 palabras).\n"
        "3. Si los resultados son ambiguos o no mencionan estilos de música concretos, devuelve 'Varios' o 'N/A'.\n"
        "4. Devuelve únicamente la respuesta en texto plano sin markdown, sin comillas ni explicaciones."
    )
    
    try:
        ans = gemini_client.generar_texto_gemini(
            prompt=prompt,
            model_name="gemini-2.5-flash",
            temperature=0.2
        )
        if ans:
            ans_clean = ans.strip()
            if len(ans_clean) < 45:
                return ans_clean
        return None
    except Exception as e:
        print(f"[scout.py] Error al extraer género específico: {e}")
        return None

def enriquecer_leads_sin_contacto(limite_leads=3, region=None):
    """
    Busca leads en la Google Sheet en estado 'nuevo' que tengan datos incompletos
    (falta de email, teléfono, website o instagram) y los enriquece de forma exhaustiva.
    """
    print("[scout.py] Iniciando proceso de enriquecimiento de leads...")
    leads = sheets.obtener_leads(estado="nuevo")
    
    if region:
        leads = [l for l in leads if (l.get("region") and region.lower() in str(l.get("region")).lower()) or (l.get("ciudad") and region.lower() in str(l.get("ciudad")).lower())]
        print(f"[scout.py] Filtrando leads en estado 'nuevo' para la región/ciudad: '{region}'. Encontrados: {len(leads)}")
        
    # Filtrar leads a los que les falte algún dato clave
    leads_incompletos = []
    for l in leads:
        falta_email = not l.get("email_contacto")
        falta_tel = not l.get("telefono")
        falta_web = not l.get("website")
        falta_insta = not l.get("instagram")
        
        if falta_email or falta_tel or falta_web or falta_insta:
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
        
        # 1. Búsqueda principal en DuckDuckGo y extracción desde snippets
        if tipo == "ayuntamiento":
            query_busqueda = f"{nombre_sala} concejalía festejos cultura contacto email"
        elif tipo == "festival":
            query_busqueda = f"{nombre_sala} contacto booking contratacion email"
        else:
            query_busqueda = f"{nombre_sala} {ciudad} web oficial contacto email telefono"
            
        results = obtener_resultados_busqueda(query_busqueda, max_results=8)
        datos_snippets = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results, tipo=tipo)

        # Acumula los datos de confianza media/baja que la IA no dio por seguros, para
        # dejarlos en 'notas' como pistas a verificar en vez de escribirlos como verificados.
        sugerencias_totales = list(datos_snippets.get("_sugerencias") or [])

        email = datos_snippets.get("email")
        telefono = datos_snippets.get("telefono")
        instagram = datos_snippets.get("instagram")
        web = datos_snippets.get("website")
        genero = datos_snippets.get("genero")
        aforo = None
        
        # 2. Si conseguimos una web que sea standalone (no facebook/instagram),
        # intentamos descargar su HTML para extraer más detalles (especialmente aforo y género)
        web_descargable = web
        is_social = False
        if web_descargable:
            web_lower = web_descargable.lower()
            if any(social in web_lower for social in ["facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com"]):
                is_social = True
                
        if web_descargable and not is_social:
            print(f"[scout.py] Intentando descargar web oficial: {web_descargable}")
            texto_home, paginas_contacto = descargar_texto_pagina(web_descargable)
            
            if texto_home:
                datos_web = extraer_datos_contacto(texto_home, web_descargable, tipo=tipo)
                sugerencias_totales.extend(datos_web.get("_sugerencias") or [])

                # Combinar datos
                if datos_web.get("email") and not email:
                    email = datos_web["email"]
                if datos_web.get("telefono") and not telefono:
                    telefono = datos_web["telefono"]
                if datos_web.get("instagram") and not instagram:
                    instagram = datos_web["instagram"]
                if datos_web.get("genero") and not genero:
                    genero = datos_web["genero"]
                if datos_web.get("aforo"):
                    aforo = datos_web["aforo"]
                    
                # Si no hay email, intentar en página de contacto
                if not email and paginas_contacto:
                    url_contacto = paginas_contacto[0]
                    print(f"[scout.py] Buscando en página de contacto: {url_contacto}")
                    texto_contacto, _ = descargar_texto_pagina(url_contacto)
                    datos_contacto = extraer_datos_contacto(texto_contacto, url_contacto, tipo=tipo)
                    sugerencias_totales.extend(datos_contacto.get("_sugerencias") or [])

                    if datos_contacto.get("email") and not email:
                        email = datos_contacto["email"]
                    if datos_contacto.get("telefono") and not telefono:
                        telefono = datos_contacto["telefono"]
                    if datos_contacto.get("instagram") and not instagram:
                        instagram = datos_contacto["instagram"]
                    if datos_contacto.get("genero") and not genero:
                        genero = datos_contacto["genero"]
                    if datos_contacto.get("aforo") and not aforo:
                        aforo = datos_contacto["aforo"]
        else:
            if is_social:
                print(f"[scout.py] Canal oficial es red social ({web_descargable}), omitiendo scraping directo.")
            else:
                print(f"[scout.py] No se encontró web oficial standalone para descargar.")
 
        # 3. Fallback: Si sigue faltando email o teléfono, buscamos snippets con query más específica
        if not email or not telefono:
            print(f"[scout.py] Fallback: buscando específicamente datos de contacto para '{nombre_sala}'...")
            if tipo == "ayuntamiento":
                query_fallback = f"{nombre_sala} concejalía cultura correo electrónico"
            elif tipo == "festival":
                query_fallback = f"{nombre_sala} enviar propuesta artistas mail"
            else:
                query_fallback = f"{nombre_sala} {ciudad} contacto email correo telefono"
                
            results_fallback = obtener_resultados_busqueda(query_fallback, max_results=8)
            
            if results_fallback:
                datos_fallback = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results_fallback, tipo=tipo)
                sugerencias_totales.extend(datos_fallback.get("_sugerencias") or [])
                if datos_fallback.get("email") and not email:
                    email = datos_fallback["email"]
                if datos_fallback.get("telefono") and not telefono:
                    telefono = datos_fallback["telefono"]
                if datos_fallback.get("instagram") and not instagram:
                    instagram = datos_fallback["instagram"]
                if datos_fallback.get("website") and not web:
                    web = datos_fallback["website"]
                if datos_fallback.get("genero") and not genero:
                    genero = datos_fallback["genero"]
                    
        # 3.5 Búsquedas ultra-dirigidas de aforo y género si siguen vacíos
        if not aforo or int(aforo or 0) == 0:
            aforo_especifico = buscar_aforo_especifico(nombre_sala, ciudad)
            if aforo_especifico:
                aforo = aforo_especifico
                
        if not genero or genero.strip().lower() in ["", "varios", "n/a", "null"]:
            genero_especifico = buscar_genero_especifico(nombre_sala, ciudad, tipo)
            if genero_especifico:
                genero = genero_especifico

        # 4. Formatear y guardar los resultados
        email = email.strip() if (email and isinstance(email, str)) else None
        telefono = telefono.strip() if (telefono and isinstance(telefono, str)) else None
        instagram = instagram.strip() if (instagram and isinstance(instagram, str)) else None
        web = web.strip() if (web and isinstance(web, str)) else None
        genero = genero.strip() if (genero and isinstance(genero, str)) else None
        
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
        else:
            print(f"[scout.py] [ERROR] No se logró extraer ningún dato de contacto para '{nombre_sala}'.")
            notas_previas = lead.get("notas") or ""
            
            datos_actualizar = {
                "estado": "nuevo",
                "notas": f"{notas_previas} | Scout: Búsqueda exhaustiva sin resultados de contacto."
            }
            # Guardar el tipo inferido/detectado aunque falle el enriquecimiento
            if not lead.get("tipo"):
                datos_actualizar["tipo"] = tipo
                
            sheets.actualizar_datos_lead(lead_id, datos_actualizar)
            
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
