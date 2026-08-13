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
import lib.google_places as google_places
from lib.busqueda import buscar_duckduckgo, formatear_snippets

# Ranking de niveles de confianza. La IA etiqueta cada dato extraído con uno de estos
# niveles; solo escribimos en la Sheet los que superan su umbral. Los demás se anotan como
# sugerencias para revisión humana. Esto materializa la regla innegociable de verificación.
NIVELES_CONFIANZA = {"alta": 3, "media": 2, "baja": 1}

# Umbral de confianza mínimo para escribir cada campo en la Sheet.
# Estricto en los datos de contacto (con ellos se envía el pitch: no pueden ser inventados)
# y flexible en los datos "blandos" (género/aforo son deducciones por naturaleza).
# El humano verifica todo en 'pendiente_aprobacion' antes de que un lead pase a 'aprobado'.
UMBRALES_POR_CAMPO = {
    "email": "media",
    "telefono": "alta",
    "website": "alta",
    "instagram": "alta",
    "genero": "media",
    "aforo": "media",
    "contacto_nombre": "media",
    "contexto_extra": "media",
    # 'alta' a propósito: una dirección mal extraída es peor que no tener ninguna — se usa
    # para calcular rutas y gastos de gira, así que un dato dudoso no debe pasar como verificado.
    "direccion": "alta",
}

DOMINIOS_IGNORADOS_REGEX = [
    "sentry.io", "wix.com", "wixpress.com", "example.com", "domain.com",
    "taquilla.com", "tripadvisor.com", "facebook.com", "instagram.com",
    "schema.org", "google.com", "github.com", "twitter.com", "youtube.com"
]

EXTENSIONES_IMAGEN_IGNORADAS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]

import re

def _extraer_emails_con_regex(texto):
    """
    Busca direcciones de correo electrónico en un texto usando expresiones regulares,
    descartando dominios de ruido técnico, imágenes o plataformas genéricas de entradas.
    """
    if not texto or not isinstance(texto, str):
        return []
    
    patron = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    coincidencias = re.findall(patron, texto)
    emails_validos = []
    
    for email in coincidencias:
        email_clean = email.strip().lower()
        
        # Ignorar si termina en una extensión de imagen típica de srcset/HTML
        if any(email_clean.endswith(ext) for ext in EXTENSIONES_IMAGEN_IGNORADAS):
            continue
            
        # Ignorar si pertenece a un dominio en la lista negra
        dominio = email_clean.split("@")[-1]
        if any(dom in dominio for dom in DOMINIOS_IGNORADOS_REGEX):
            continue
            
        if email_clean not in emails_validos:
            emails_validos.append(email_clean)
            
    return emails_validos


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
            "6. aforo: Pon siempre null.\n"
            "7. contacto_nombre: El nombre y apellido de la persona responsable (concejal/a de cultura, festejos o juventud) SOLO si aparece explícitamente nombrada en el texto. Si no aparece, null.\n"
            "8. contexto_extra: Una frase breve (máx. 20 palabras) sobre qué tipo de eventos, fiestas patronales o programación cultural organiza este ayuntamiento, basada SOLO en lo que dice el texto. Si no hay información concreta, null.\n"
            "9. direccion: La dirección postal completa (calle, número, código postal) de la sede del ayuntamiento o del recinto donde se celebran los eventos, SOLO si aparece literal en el texto. Si no aparece, null."
        )
    elif tipo == "festival":
        objetivo_contacto = (
            "Tu objetivo es extraer la información de contacto oficial del festival:\n"
            "1. email: El email de contacto oficial para booking, contratación, envío de propuestas, prensa o información general del festival.\n"
            "2. telefono: El teléfono oficial de contacto del festival/organización.\n"
            "3. instagram: El usuario de Instagram oficial del festival (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a la web oficial del festival.\n"
            "5. genero: El estilo o género musical predominante del festival (ej: 'Indie / Pop', 'Electrónica', 'Folk', etc.).\n"
            "6. aforo: La capacidad o aforo del recinto del festival (número entero, o null si no se menciona).\n"
            "7. contacto_nombre: El nombre y apellido de la persona de programación, dirección artística o booking SOLO si aparece explícitamente nombrada en el texto. Si no aparece, null.\n"
            "8. contexto_extra: Una frase breve (máx. 20 palabras) sobre el ambiente, edición actual, artistas destacados o carácter del festival, basada SOLO en lo que dice el texto. Si no hay información concreta, null.\n"
            "9. direccion: La dirección postal completa (calle, número, código postal) del recinto donde se celebra el festival, SOLO si aparece literal en el texto. Si no aparece, null."
        )
    else:
        objetivo_contacto = (
            "Tu objetivo es extraer cualquier información de contacto oficial de este local o evento:\n"
            "1. email: El email de contacto/programación oficial de la sala.\n"
            "2. telefono: El teléfono de contacto oficial.\n"
            "3. instagram: El usuario de Instagram (ej: @nombre o nombre_usuario).\n"
            "4. website: El enlace a su canal oficial real (puede ser su web oficial .com/.es, o su página oficial de Facebook o de Instagram si no tiene web independiente).\n"
            "5. genero: El estilo o género musical habitual de la sala, indicando los estilos predominantes específicos si se mencionan en los resultados (ej: 'Rock / Metal', 'Balkan / Ska / Reggae', 'Indie Pop', etc. Evita poner simplemente 'Varios' a menos que no exista otra información).\n"
            "6. aforo: El aforo de la sala (capacidad máxima de personas) si se menciona en los resultados (número entero, o null si no se menciona).\n"
            "7. contacto_nombre: El nombre y apellido de la persona programadora o responsable de booking SOLO si aparece explícitamente nombrada en el texto. Si no aparece, null.\n"
            "8. contexto_extra: Una frase breve (máx. 20 palabras) sobre qué tipo de conciertos/eventos organiza habitualmente la sala, su ambiente o su público, basada SOLO en lo que dice el texto. Si no hay información concreta, null.\n"
            "9. direccion: La dirección postal completa (calle, número, código postal) de la sala, SOLO si aparece literal en el texto. Si no aparece, null."
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
        "  \"aforo\":     {\"valor\": \"aforo o null\",     \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"contacto_nombre\": {\"valor\": \"nombre o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"contexto_extra\":  {\"valor\": \"frase breve o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"},\n"
        "  \"direccion\":  {\"valor\": \"direccion postal o null\", \"confianza\": \"alta|media|baja\", \"fuente\": \"[n] o null\"}\n"
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
        data, campos=["email", "telefono", "instagram", "website", "genero", "aforo", "contacto_nombre", "contexto_extra", "direccion"],
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
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return "", []

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
            "3. Para el genero: extrae o infiere el tipo de música (pon 'Varios / Festivo').\n"
            "4. Para contacto_nombre: nombre y apellido del/de la concejal/a de cultura, festejos o juventud SOLO si aparece literal en el texto. Si no, null.\n"
            "5. Para contexto_extra: una frase breve (máx. 20 palabras) sobre las fiestas patronales o programación cultural del municipio, basada solo en el texto. Si no hay info concreta, null.\n"
            "6. Para direccion: la dirección postal completa (calle, número, código postal) de la sede del ayuntamiento, SOLO si aparece literal en el texto. Si no, null."
        )
    elif tipo == "festival":
        objetivo_contacto = (
            "1. Para el aforo: busca la capacidad del recinto del festival o asistencia estimada. Si es numérico ponlo como integer, si no pon null.\n"
            "2. Para el email: extrae el correo de contratación, booking, propuestas artísticas, producción o el de información general.\n"
            "3. Para el genero: extrae o infiere el estilo musical predominante del festival, indicando los géneros específicos (ej: 'Indie Pop', 'Folk Rock', etc.).\n"
            "4. Para contacto_nombre: nombre y apellido de la persona de programación, dirección artística o booking SOLO si aparece literal en el texto. Si no, null.\n"
            "5. Para contexto_extra: una frase breve (máx. 20 palabras) sobre el ambiente, edición actual o artistas destacados del festival, basada solo en el texto. Si no hay info concreta, null.\n"
            "6. Para direccion: la dirección postal completa (calle, número, código postal) del recinto del festival, SOLO si aparece literal en el texto. Si no, null."
        )
    else:
        objetivo_contacto = (
            "1. Para el aforo: busca menciones del tamaño de la sala, capacidad, limitación de personas o aforo. Si es numérico ponlo como integer, si no pon null.\n"
            "2. Para el email: extrae solo correos corporativos o de contacto profesional de la sala (ej: programacion@..., info@..., contacto@...).\n"
            "3. Para el genero: extrae o infiere el estilo o género musical habitual de la sala, detallando los estilos predominantes de forma específica (ej: 'Rock / Metal', 'Balkan / Ska / Reggae', 'Electrónica / Techno', etc. Evita poner 'Varios' a menos que no exista otra información).\n"
            "4. Para contacto_nombre: nombre y apellido de la persona programadora o responsable de booking SOLO si aparece literal en el texto. Si no, null.\n"
            "5. Para contexto_extra: una frase breve (máx. 20 palabras) sobre qué tipo de conciertos organiza habitualmente la sala, su ambiente o su público, basada solo en el texto. Si no hay info concreta, null.\n"
            "6. Para direccion: la dirección postal completa (calle, número, código postal) de la sala, SOLO si aparece literal en el texto. Si no, null."
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
        '  "genero":    {"valor": "genero o null",          "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "contacto_nombre": {"valor": "nombre o null",    "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "contexto_extra":  {"valor": "frase breve o null", "confianza": "alta|media|baja", "fuente": "texto o null"},\n'
        '  "direccion":  {"valor": "direccion postal o null", "confianza": "alta|media|baja", "fuente": "texto o null"}\n'
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
        data, campos=["email", "telefono", "instagram", "aforo", "genero", "contacto_nombre", "contexto_extra", "direccion"],
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


def procesar_un_lead(lead):
    """
    Procesa y enriquece un único lead.
    Retorna el diccionario de datos enriquecidos si tuvo éxito, o None si no.
    """
    lead_id = lead.get("id")
    nombre_sala = lead.get("nombre_sala")
    ciudad = lead.get("ciudad")
    
    # Evitar llamadas simultáneas exactas a DuckDuckGo e IA
    time.sleep(random.uniform(0.1, 1.5))
    
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
    CAMPOS = ["email", "telefono", "instagram", "website", "genero", "aforo", "contacto_nombre", "contexto_extra", "direccion", "imagen_url", "icono"]

    # 0. Google Places, si está configurado (opcional — ver lib/google_places.py): dato
    # estructurado y verificado por Google, se trata como confianza 'alta' directamente. No
    # tiene email (ese campo no existe en Places), pero da dirección/teléfono/web fiables desde
    # el principio y extrae/sube la foto verificada a Supabase Storage (imagen_url e icono).
    # Solo se llama si al lead le falta alguno de esos tres datos o la foto — no gasta cuota en vano.
    if google_places.esta_configurado() and not (lead.get("direccion") and lead.get("telefono") and lead.get("website") and lead.get("imagen_url")):
        datos_places = google_places.buscar_lugar(nombre_sala, ciudad, lead_id=lead_id)
        if datos_places:
            _combinar(datos, datos_places, CAMPOS)
            print(f"[scout.py] Google Places aportó: dirección={datos.get('direccion') or 'N/A'}, teléfono={datos.get('telefono') or 'N/A'}, web={datos.get('website') or 'N/A'}, imagen={datos.get('imagen_url') or 'N/A'}")

    # 1. Una única búsqueda amplia + extracción estructurada desde snippets + Regex de correos.
    if tipo == "ayuntamiento":
        query_busqueda = f"{nombre_sala} concejalía festejos cultura contacto email telefono"
    elif tipo == "festival":
        query_busqueda = f"{nombre_sala} contacto booking contratacion email telefono"
    else:
        query_busqueda = f"{nombre_sala} {ciudad} web oficial contacto email telefono aforo"

    results = buscar_duckduckgo(query_busqueda, max_results=15)
    datos_snippets = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results, tipo=tipo)
    sugerencias_totales.extend(datos_snippets.get("_sugerencias") or [])
    _combinar(datos, datos_snippets, CAMPOS)

    # Respaldo Regex sobre los snippets iniciales
    emails_regex = _extraer_emails_con_regex(formatear_snippets(results))
    if emails_regex and not datos.get("email"):
        datos["email"] = emails_regex[0]

    # 2. Si no se encontró la web oficial en los snippets amplios, la buscamos de manera dedicada
    web = datos.get("website")
    if not web:
        print(f"[scout.py] Web no encontrada en snippets. Buscando web oficial de forma dedicada...")
        web = buscar_web_sala(nombre_sala, ciudad)
        if web:
            datos["website"] = web

    # 3. Si la web es standalone (no red social), descargamos su HTML: es la mejor fuente
    # de aforo y género.
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

            emails_web_regex = _extraer_emails_con_regex(texto_home)
            if emails_web_regex and not datos.get("email"):
                datos["email"] = emails_web_regex[0]

            # Profundizamos en la página de contacto solo si aún falta email o aforo
            if (not datos.get("email") or not datos.get("aforo")) and paginas_contacto:
                url_contacto = paginas_contacto[0]
                print(f"[scout.py] Buscando en página de contacto: {url_contacto}")
                texto_contacto, _ = descargar_texto_pagina(url_contacto)
                datos_contacto = extraer_datos_contacto(texto_contacto, url_contacto, tipo=tipo)
                sugerencias_totales.extend(datos_contacto.get("_sugerencias") or [])
                _combinar(datos, datos_contacto, CAMPOS)

                emails_contacto_regex = _extraer_emails_con_regex(texto_contacto)
                if emails_contacto_regex and not datos.get("email"):
                    datos["email"] = emails_contacto_regex[0]
    elif is_social:
        print(f"[scout.py] Canal oficial es red social ({web}), omitiendo scraping HTML directo.")
    else:
        print(f"[scout.py] No se encontró web oficial standalone para descargar.")

    # 4. Búsqueda dirigida a Redes Sociales (Instagram / Facebook / Linktree) si aún falta email
    if not datos.get("email"):
        print(f"[scout.py] Buscando perfiles de contacto en redes sociales (Instagram/Facebook/Linktree)...")
        query_social = f'"{nombre_sala}" "{ciudad}" instagram OR facebook OR linktree "booking" OR "contacto" OR "@"'
        results_social = buscar_duckduckgo(query_social, max_results=12)
        if results_social:
            datos_social = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results_social, tipo=tipo)
            sugerencias_totales.extend(datos_social.get("_sugerencias") or [])
            _combinar(datos, datos_social, CAMPOS)
            emails_social_regex = _extraer_emails_con_regex(formatear_snippets(results_social))
            if emails_social_regex and not datos.get("email"):
                datos["email"] = emails_social_regex[0]

    # 5. Fallback dirigido: solo si sigue faltando el email (el único dato imprescindible).
    if not datos.get("email"):
        print(f"[scout.py] Fallback: buscando específicamente el email de contacto de '{nombre_sala}'...")
        if tipo == "ayuntamiento":
            query_fallback = f"{nombre_sala} concejalía cultura correo electrónico"
        elif tipo == "festival":
            query_fallback = f"{nombre_sala} enviar propuesta artistas mail"
        else:
            query_fallback = f"{nombre_sala} {ciudad} contacto email correo telefono"

        results_fallback = buscar_duckduckgo(query_fallback, max_results=15)
        if results_fallback:
            datos_fallback = extraer_datos_contacto_de_snippets(nombre_sala, ciudad, results_fallback, tipo=tipo)
            sugerencias_totales.extend(datos_fallback.get("_sugerencias") or [])
            _combinar(datos, datos_fallback, CAMPOS)
            emails_fb_regex = _extraer_emails_con_regex(formatear_snippets(results_fallback))
            if emails_fb_regex and not datos.get("email"):
                datos["email"] = emails_fb_regex[0]

    # 5. Formatear y guardar los resultados
    def _limpiar(v):
        return v.strip() if isinstance(v, str) else v

    email = _limpiar(datos.get("email"))
    telefono = _limpiar(datos.get("telefono"))
    instagram = _limpiar(datos.get("instagram"))
    web = _limpiar(datos.get("website"))
    genero = _limpiar(datos.get("genero"))
    aforo = datos.get("aforo")
    contacto_nombre = _limpiar(datos.get("contacto_nombre"))
    contexto_extra = _limpiar(datos.get("contexto_extra"))
    direccion = _limpiar(datos.get("direccion"))

    # Validar formato básico de email
    if email and "@" not in email:
        email = None

    if email or telefono or instagram or web or genero or aforo or contacto_nombre or contexto_extra or direccion:
        print(f"[scout.py] [SUCCESS] Datos encontrados - Email: {email or 'N/A'}, Teléfono: {telefono or 'N/A'}, Instagram: {instagram or 'N/A'}, Web: {web or 'N/A'}, Género: {genero or 'N/A'}, Aforo: {aforo or 'N/A'}, Contacto: {contacto_nombre or 'N/A'}, Dirección: {direccion or 'N/A'}")
        
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

        try:
            aforo_actual = int(lead.get("aforo") or 0)
        except (ValueError, TypeError):
            # Dato corrupto ya existente en la Sheet (p. ej. texto en vez de número) — no debe
            # tumbar todo el lote en paralelo por un solo lead con basura en esa celda.
            print(f"[scout.py] Aviso: 'aforo' de '{nombre_sala}' no es numérico ({lead.get('aforo')!r}), se ignora al comparar.")
            aforo_actual = 0

        if aforo and aforo_actual == 0:
            print(f"[scout.py] Aforo detectado: {aforo} personas.")
            datos_actualizar["aforo"] = aforo

        if contacto_nombre and not lead.get("contacto_nombre"):
            datos_actualizar["contacto_nombre"] = contacto_nombre
        if contexto_extra and not lead.get("contexto_extra"):
            datos_actualizar["contexto_extra"] = contexto_extra
        if direccion and not lead.get("direccion"):
            datos_actualizar["direccion"] = direccion

        res = sheets.actualizar_datos_lead(lead_id, datos_actualizar)

        # Coordinación de estados: si tras enriquecer sigue SIN email, el redactor no puede
        # trabajar el lead. Lo sacamos de 'nuevo' a 'sin_contacto' para que no se reintente
        # en cada ejecución del cron. (El teléfono/web encontrados se conservan.)
        email_final = lead.get("email_contacto") or email
        if not email_final:
            estados.transicionar(lead, estados.SIN_CONTACTO)
        elif lead.get("estado") == estados.SIN_CONTACTO:
            # Recuperado: antes no tenía contacto y ahora sí. El grafo permite SIN_CONTACTO ->
            # NUEVO explícitamente para este caso (ver comentario en lib/estados.py); sin esta
            # transición el lead se queda enterrado en 'sin_contacto' y el redactor nunca lo ve.
            print(f"[scout.py] Email recuperado para un lead en 'sin_contacto': reactivando a 'nuevo'.")
            estados.transicionar(lead, estados.NUEVO)
            
        if res:
            return {
                "id": lead_id,
                "nombre": nombre_sala,
                "ciudad": ciudad,
                "email": email or "",
                "telefono": telefono or "",
                "instagram": instagram or "",
                "web": web or "",
                "genero": genero or "",
                "aforo": aforo or "",
                "contacto_nombre": contacto_nombre or "",
                "contexto_extra": contexto_extra or "",
                "direccion": direccion or ""
            }
    else:
        print(f"[scout.py] [ERROR] No se logró extraer ningún dato de contacto para '{nombre_sala}'.")
        notas_previas = lead.get("notas") or ""

        # Guardar el tipo inferido/detectado aunque falle el enriquecimiento
        if not lead.get("tipo"):
            sheets.actualizar_datos_lead(lead_id, {"tipo": tipo})

        # No encontrar nada NUEVO esta vez no significa que el lead no tenga ya contacto: si
        # venía con email_contacto de una pasada anterior, no lo tiramos a 'sin_contacto' (eso
        # borraría progreso real, como pasó con un lead que ya tenía email y quedó degradado
        # solo porque este reintento concreto no encontró nada más).
        if lead.get("email_contacto"):
            print(f"[scout.py] '{nombre_sala}' ya tenía contacto guardado; se conserva el estado.")
        else:
            # Sin ningún contacto: a 'sin_contacto' (terminal), fuera del bucle de reintentos.
            estados.transicionar(
                lead, estados.SIN_CONTACTO,
                notas=f"{notas_previas} | Scout: búsqueda exhaustiva sin resultados de contacto.",
            )
    return None


def enriquecer_leads_sin_contacto(limite_leads=3, region=None, enviar_webhook=True):
    """
    Busca leads en la Google Sheet que tengan datos incompletos (especialmente email_contacto)
    y los enriquece de forma exhaustiva en paralelo.
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
        if enviar_webhook:
            from lib.webhooks import enviar_webhook_finalizacion
            enviar_webhook_finalizacion("scout", region or "Todas", creados=0, leads_enriquecidos=[])
        return []
        
    leads_a_procesar = leads_incompletos[:limite_leads]
    
    # Procesar concurrentemente utilizando ThreadPoolExecutor
    from concurrent.futures import ThreadPoolExecutor
    max_workers = min(3, len(leads_a_procesar)) # 3 trabajadores para cuidar cuota y límites
    
    print(f"[scout.py] Iniciando procesamiento en paralelo de {len(leads_a_procesar)} leads con {max_workers} hilos...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        resultados = list(executor.map(procesar_un_lead, leads_a_procesar))
        
    # Filtrar los leads que se enriquecieron correctamente
    leads_enriquecidos_detalles = [r for r in resultados if r is not None]
    
    print(f"\n[scout.py] Enriquecimiento finalizado. Leads completados con éxito: {len(leads_enriquecidos_detalles)}")
    
    # Enviar notificación webhook si se requiere
    if enviar_webhook:
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout", region or "Todas", creados=0, leads_enriquecidos=leads_enriquecidos_detalles)
        
    return leads_enriquecidos_detalles


def enriquecer_direcciones_faltantes(limite=30):
    """
    Backfill dirigido: busca la dirección postal de leads ACTIVOS que aún no la tienen, aunque
    ya estén enriquecidos en el resto de campos. `enriquecer_leads_sin_contacto` no los tocaría
    porque ya tienen email/teléfono — esta función filtra específicamente por 'direccion' vacía.

    Reutiliza procesar_un_lead tal cual: solo rellena huecos (nunca sobreescribe un dato ya
    verificado), así que es seguro reejecutar sobre leads que ya tienen otros campos completos.
    """
    leads = sheets.obtener_leads()
    activos = [l for l in leads if l.get("estado") not in (estados.DESCARTADO, estados.NO_INTERESADO)]
    sin_direccion = [l for l in activos if not (l.get("direccion") or "").strip()]
    print(f"[scout.py] {len(sin_direccion)} leads activos sin dirección postal.")

    if not sin_direccion:
        return []

    leads_a_procesar = sin_direccion[:limite]
    max_workers = min(3, len(leads_a_procesar))
    print(f"[scout.py] Buscando dirección para {len(leads_a_procesar)} leads con {max_workers} hilos...")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        resultados = list(executor.map(procesar_un_lead, leads_a_procesar))

    tocados = [r for r in resultados if r is not None]
    con_direccion = [r for r in tocados if r.get("direccion")]
    print(f"[scout.py] Backfill de direcciones finalizado. Leads procesados: {len(tocados)}, con dirección encontrada: {len(con_direccion)}.")
    return tocados


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agente Scout para enriquecer leads.")
    parser.add_argument("--limit", type=int, default=3, help="Límite de leads a procesar.")
    parser.add_argument("--all", action="store_true", help="Procesar todos los leads incompletos.")
    parser.add_argument("--region", type=str, default=None, help="Filtrar por región o provincia.")
    parser.add_argument("--direcciones", action="store_true", help="Backfill: buscar solo la dirección postal de leads que aún no la tienen.")
    args = parser.parse_args()

    limite = 99999 if args.all else args.limit
    if args.direcciones:
        enriquecer_direcciones_faltantes(limite=limite)
    else:
        enriquecer_leads_sin_contacto(limite_leads=limite, region=args.region)
