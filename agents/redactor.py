import sys
import os
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import random
import lib.sheets as sheets
import lib.gemini_client as gemini_client
import lib.estados as estados

# Enfoques de estilo para el pitch. Se elige UNO al azar por lead en Python (no se le
# deja la decisión al LLM): dejarlo elegir "según convenga" hace que, sin memoria entre
# llamadas, tienda a converger siempre en el mismo enfoque "seguro". Forzar la elección
# aquí garantiza variedad real entre leads.
ENFOQUES_ESTILO = [
    ("Rítmico/Festivo", "Destaca el baile, la electrónica en vivo, el loop station y la fiesta."),
    ("Luthería/Eco-Luthier", "Pon el foco en el 'electrobasureo', la originalidad extrema de tocar música electrónica bailable usando percusión construida a partir de materiales 100% reciclados y basura recuperada."),
    ("Colaborativo/Cercano", "Enfatiza la coorganización, taquilla compartida y el apoyo a las salas."),
]

def cargar_epk():
    """
    Carga los datos del EPK de la banda desde el archivo JSON de datos.
    """
    ruta_epk = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "epk_bakandeya.json")
    try:
        with open(ruta_epk, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[redactor.py] Error al cargar el EPK: {e}")
        return {}

def generar_pitch_para_lead(lead, epk):
    """
    Genera el texto del pitch (ASUNTO + cuerpo) para un único lead usando Gemini y el EPK.
    No toca la Google Sheet ni el estado del lead — solo devuelve el texto (o None si falla).
    Extraído de `procesar_nuevos_leads` para poder reutilizarlo (p. ej. pruebas puntuales de
    un lead concreto) sin arrastrar la transición de estado del flujo normal.
    """
    nombre_sala = lead.get("nombre_sala")
    tipo = lead.get("tipo")
    tipo = tipo.strip().lower() if (tipo and isinstance(tipo, str)) else "sala"

    ciudad = lead.get("ciudad") or ""
    region = lead.get("region") or ""
    aforo = lead.get("aforo") or 0
    genero = lead.get("genero") or "Varios"
    contacto_nombre = (lead.get("contacto_nombre") or "").strip()
    contexto_extra = (lead.get("contexto_extra") or "").strip()

    # Detección programática del idioma de destino
    idioma = "español"
    ciudad_low = ciudad.lower() if isinstance(ciudad, str) else ""
    region_low = region.lower() if isinstance(region, str) else ""

    if any(p in ciudad_low or p in region_low for p in ["portugal", "lisboa", "lisbon", "porto", "oporto"]):
        idioma = "portugués"
    elif any(f in ciudad_low or f in region_low for f in ["francia", "france", "toulouse", "bordeaux", "burdeos", "paris", "bikini"]):
        idioma = "francés"
    elif ciudad_low or region_low:
        if not any(e in ciudad_low or e in region_low for e in ["españa", "spain", "granada", "madrid", "barcelona", "sevilla", "valencia", "galicia", "bilbao"]):
            idioma = "inglés"

    # Enfoque de estilo: elegido al azar en Python (ver ENFOQUES_ESTILO), no por el LLM.
    nombre_enfoque, descripcion_enfoque = random.choice(ENFOQUES_ESTILO)

    # Saludo: si el Scout encontró el nombre de la persona de contacto, se usa de verdad.
    if contacto_nombre:
        primer_nombre = contacto_nombre.split()[0]
        instruccion_saludo = (
            f"Dirígete a la persona por su nombre de pila de forma natural y cercana "
            f"(ej: 'Hola {primer_nombre},'). No inventes cargo ni apellido."
        )
    else:
        instruccion_saludo = (
            f"No conoces el nombre de la persona. Saluda de forma cercana y natural sin placeholders "
            f"(ej: 'Hola al equipo de {nombre_sala},', 'Hola gente de {nombre_sala},', 'Buenas,')."
        )

    # Personalización: si el Scout capturó un dato real sobre el local/evento, se usa como
    # gancho concreto en vez de la frase genérica de siempre sobre el género musical.
    if contexto_extra:
        instruccion_personalizacion = (
            f"Tienes este dato real y específico sobre ellos, obtenido de su propia web: \"{contexto_extra}\". "
            "Úsalo para demostrar que conoces su programación de verdad (con tus propias palabras, no lo copies "
            "literal) — esto pesa más que hablar en genérico del género musical."
        )
    else:
        instruccion_personalizacion = (
            f"No tienes datos específicos de su programación: apóyate en el género musical habitual del local "
            f"({genero}) para justificar por qué Bakandeya encaja."
        )

    # Reglas base comunes de alta calidad
    reglas_calidad = (
        f"1. IDIOMA DE DESTINO OBLIGATORIO: Escribe el email COMPLETO (tanto el ASUNTO como el Cuerpo) en {idioma}. "
        f"Usa un tono nativo, natural y fluido en {idioma}, adaptando los modismos de forma idiomática.\n"
        "2. PROHIBIDO BOILERPLATES Y REPETICIONES: No uses introducciones aburridas como 'Espero que estés bien', 'Espero que todo vaya genial', 'Me pongo en contacto', etc. "
        "Empieza cada email con una frase o saludo original y directo. Varía las palabras en cada propuesta.\n"
        f"3. ENFOQUE OBLIGATORIO PARA ESTA PROPUESTA ({nombre_enfoque}): {descripcion_enfoque}\n"
        "4. GANCHO DE AFORO: Adapta el discurso al aforo, SIN usar lenguaje de discoteca/clubbing "
        "(prohibidas expresiones como 'noche de clubbing', 'pista de baile' — no encajan en salas de concierto, "
        "festivales ni ayuntamientos, sea cual sea el aforo): \n"
        f"   - Si el aforo es pequeño (< 300 personas, aforo actual del local: {aforo}), enfócalo como un show íntimo de alta energía, interacción cara a cara y conexión directa con el público.\n"
        f"   - Si el aforo es mediano/grande (>= 300 personas, aforo actual del local: {aforo}), enfócalo como un directo arrollador, con energía colectiva capaz de llenar el espacio.\n"
        "5. ENLACES INTEGRADOS: Inserta de manera fluida y dentro del texto los enlaces del EPK (sin listas feas al final). "
        "El dossier completo en PDF va ADJUNTO al email (no como link) — menciónalo de forma natural una vez "
        "(ej: 'te adjunto nuestro dossier completo con más info') sin inventar ningún link para él. El dossier "
        "actual NO incluye el rider técnico todavía — no lo menciones como parte de lo adjunto ni en general.\n"
        f"6. SALUDO: {instruccion_saludo} Prohibido cualquier placeholder o corchete como '[Nombre del programador]', '[Fecha]', '[Responsable]', etc. "
        "Esto también aplica a la FIRMA final: firma siempre con 'Jon Quel' (voz de la banda) o 'Bakandeya', nunca con un placeholder como '[Tu Nombre]'.\n"
        f"7. PERSONALIZACIÓN REAL: {instruccion_personalizacion}\n"
        "8. LONGITUD BREVE: Máximo 120-140 palabras en el cuerpo (sin contar asunto ni firma). Un programador "
        "recibe decenas de emails al día y no va a leer un muro de texto. Máximo 2-3 párrafos CORTOS. "
        "FRASES CORTAS: cada frase debe expresar UNA sola idea — prohibido encadenar varias ideas en una misma "
        "frase con comas y gerundios (ej: nada de 'X, que hace Y, podría Z, conectando con W'). Si una frase "
        "tiene más de ~20 palabras, divídela en dos. Ve directo al grano: quién sois, por qué encajáis con ellos, "
        "y la llamada a la acción — nada más.\n"
        "9. TONO DE LA LLAMADA A LA ACCIÓN: Nunca uses verbos que suenen a negociación formal o exigente ('discutir', "
        "'negociar', 'acordar condiciones'). Usa un tono cercano e invitador: 'nos encantaría explorar...', "
        "'quedamos a vuestra disposición para...', 'nos encantaría hablar de fechas y detalles'.\n"
        "10. PRECISIÓN SOBRE LOS INSTRUMENTOS: Solo la percusión de José Filgueira está construida con materiales "
        "reciclados (luthería urbana). Elyar Pashang toca handpan y percusión étnica (darbuka, daf) — instrumentos "
        "originales, NO reciclados. No atribuyas 'reciclado' a los instrumentos de Elyar ni generalices diciendo "
        "que 'las percusiones de José y Elyar' son recicladas.\n"
        "11. 'ELECTROBASUREO' NO ES UN GANCHO: es un término descriptivo del estilo, no un titular. PROHIBIDO "
        "usarlo en el ASUNTO o como primera frase/gancho de apertura del email. Si aparece, que sea de pasada y "
        "más adelante en el cuerpo (ej: 'una fusión que llamamos electrobasureo'), nunca como lo primero que se lee. "
        "Como 'electrobasureo' ya no lleva el peso del gancho, asegúrate de que la palabra 'electrónica' (o "
        "'electrónica bailable') sí aparezca de forma clara en algún punto del email — es la referencia de género "
        "más reconocible y no debe perderse.\n"
        "12. PUNTUACIÓN NATURAL: Usa comas, guiones y demás signos como los usaría una persona real escribiendo, "
        "no como una carta formal. Evita en concreto el patrón rígido 'Hola, [destinatario],' con coma justo tras "
        "'Hola' — suena impostado. Puntúa solo donde de verdad ayuda a leer, no por convención de carta formal."
    )

    if tipo == "ayuntamiento":
        print(f"[redactor.py] Generando pitch para Ayuntamiento: {nombre_sala} ({ciudad})...")
        prompt = (
            f"Redacta una propuesta artística para las programaciones culturales o festejos del siguiente ayuntamiento. "
            f"Escribe todo el texto (asunto y cuerpo) en {idioma}.\n"
            f"- Ayuntamiento: {nombre_sala}\n"
            f"- Ciudad/Región: {ciudad} / {region}\n\n"
            "Devuelve la respuesta en el formato exacto:\n"
            "ASUNTO: [Asunto en el idioma correspondiente, llamativo y sin repetir patrones]\n\n"
            "[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces]"
        )

        reglas_redaccion = (
            f"{reglas_calidad}\n"
            "13. Dirígete de manera profesional y cercana a la concejalía de festejos, cultura o juventud.\n"
            "14. Presenta el proyecto como una opción perfecta para plazas, festivales municipales y eventos al aire libre por su carácter festivo, familiar y ecológico (concienciación ambiental por percusión reciclada).\n"
            "15. Propón contratación por caché o convenios culturales."
        )
    elif tipo == "festival":
        print(f"[redactor.py] Generando pitch para Festival: {nombre_sala}... ")
        prompt = (
            f"Redacta una propuesta artística para el siguiente festival. "
            f"Escribe todo el texto (asunto y cuerpo) en {idioma}.\n"
            f"- Festival: {nombre_sala}\n"
            f"- Ciudad/Región: {ciudad} / {region}\n"
            f"- Estilo habitual/Género del festival: {genero}\n\n"
            "Devuelve la respuesta en el formato exacto:\n"
            "ASUNTO: [Asunto en el idioma correspondiente, llamativo y sin repetir patrones]\n\n"
            "[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces]"
        )

        reglas_redaccion = (
            f"{reglas_calidad}\n"
            "13. Dirígete al equipo de programación, dirección artística o booking del festival.\n"
            "14. Explica cómo la mezcla de electrónica bailable, beatbox en vivo y percusión reciclada (luthería urbana) encaja perfectamente en su cartel y sorprenderá a su público.\n"
            "15. Busca proponer contratación directa por caché o condiciones de festival.\n"
            "16. MÚLTIPLES ESCENARIOS: los festivales suelen tener varios escenarios/carpas. Si mencionas dónde tocaría "
            "la banda, di 'alguno de vuestros escenarios' o 'uno de vuestros escenarios' en vez de 'vuestro escenario' "
            "en singular, salvo que sepas con certeza que el festival tiene uno solo."
        )
    else:
        print(f"[redactor.py] Generando pitch para la sala: {nombre_sala} ({ciudad})...")
        prompt = (
            f"Redacta una propuesta de concierto personalizada para la siguiente sala. "
            f"Escribe todo el texto (asunto y cuerpo) en {idioma}.\n"
            f"- Nombre de la sala: {nombre_sala}\n"
            f"- Ciudad/Región: {ciudad} / {region}\n"
            f"- Aforo estimado: {aforo} personas\n"
            f"- Estilo habitual de la sala: {genero}\n\n"
            "Devuelve la respuesta en el formato exacto:\n"
            "ASUNTO: [Asunto en el idioma correspondiente, llamativo y sin repetir patrones]\n\n"
            "[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces]"
        )

        reglas_redaccion = (
            f"{reglas_calidad}\n"
            "13. Dirígete al programador o responsable de booking de la sala.\n"
            "14. No hables de precios ni de rider técnico. Busca proponer una fecha, ver disponibilidad o proponer un formato de taquilla compartida / coorganización."
        )

    system_prompt = (
        "Eres el redactor y manager de la banda de música Bakandeya.\n"
        "Tu objetivo es escribir propuestas de contratación de conciertos (pitches) profesionales, "
        "cercanas y persuasivas.\n\n"
        f"Información de la banda (EPK):\n"
        f"- Nombre: {epk.get('nombre')}\n"
        f"- Estilo: {epk.get('estilo')}\n"
        f"- Integrantes: {', '.join(epk.get('integrantes', []))}\n"
        f"- Influencias: {', '.join(epk.get('influencias', []))}\n"
        f"- Descripción corta: {epk.get('descripcion_corta')}\n"
        f"- Enlaces para incluir (teaser, instagram):\n"
        f"  * Teaser en directo (YouTube): {epk.get('enlaces', {}).get('youtube_teaser_aca2026')}\n"
        f"  * Instagram: {epk.get('enlaces', {}).get('instagram')}\n\n"
        "Reglas de Redacción:\n"
        f"{reglas_redaccion}"
    )

    return gemini_client.generar_texto_gemini(
        prompt,
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        temperature=0.85
    )


def procesar_nuevos_leads(limite_leads=9999, lead_id_especifico=None, regenerar=False):
    """
    Busca leads en estado 'nuevo' (o cualquiera si se especifica id o regenerar). Si tienen email, les genera un pitch
    usando Gemini y la información del EPK, y actualiza su estado a 'pendiente_aprobacion'.
    """
    print("[redactor.py] Iniciando procesamiento de nuevos leads...")
    if lead_id_especifico:
        leads = sheets.obtener_leads()
        leads = [l for l in leads if l.get("id") == lead_id_especifico]
        print(f"[redactor.py] Filtrando por ID de lead específico: '{lead_id_especifico}'. Encontrados: {len(leads)}")
    elif regenerar:
        leads_nuevos = sheets.obtener_leads(estado=estados.NUEVO)
        leads_pendientes = sheets.obtener_leads(estado=estados.PENDIENTE)
        leads = leads_nuevos + leads_pendientes
        print(f"[redactor.py] Regenerando pitches. Leads en 'nuevo': {len(leads_nuevos)}, en 'pendiente_aprobacion': {len(leads_pendientes)}")
    else:
        leads = sheets.obtener_leads(estado=estados.NUEVO)

    epk = cargar_epk()

    if not epk:
        print("[redactor.py] EPK no encontrado o vacío. Abortando generación.")
        return 0

    procesados = 0
    leads_a_procesar = [l for l in leads if l.get("email_contacto")]
    leads_a_procesar = leads_a_procesar[:limite_leads]

    for lead in leads_a_procesar:
        lead_id = lead.get("id")
        email = lead.get("email_contacto")
        nombre_sala = lead.get("nombre_sala")

        if not email:
            print(f"[redactor.py] Lead {lead_id} ({nombre_sala}) no tiene email de contacto. Se omite para enriquecimiento manual.")
            continue

        pitch = generar_pitch_para_lead(lead, epk)
        if pitch:
            estados.transicionar(lead, estados.PENDIENTE, pitch=pitch)
            procesados += 1

    print(f"[redactor.py] Procesamiento finalizado. Leads redactados y listos para aprobación: {procesados}")
    return procesados

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agente Redactor para generar pitches de leads.")
    parser.add_argument("--limit", type=int, default=3, help="Límite de leads a redactar.")
    parser.add_argument("--all", action="store_true", help="Procesar todos los leads en estado 'nuevo' que tengan email.")
    parser.add_argument("--id", type=str, default=None, help="ID de un lead específico a redactar.")
    parser.add_argument("--regenerate", action="store_true", help="Regenerar pitches de leads ya en 'pendiente_aprobacion' además de los nuevos.")
    args = parser.parse_args()

    limite = 99999 if args.all else args.limit
    procesar_nuevos_leads(limite_leads=limite, lead_id_especifico=args.id, regenerar=args.regenerate)
