import sys
import os
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import lib.sheets as sheets
import lib.gemini_client as gemini_client
import lib.estados as estados
import lib.bandas as bandas

BAND_ID_DEFAULT = sheets.BAND_ID_DEFAULT

# Enfoques de estilo para el pitch. Se elige UNO al azar por lead en Python (no se le
# deja la decisión al LLM): dejarlo elegir "según convenga" hace que, sin memoria entre
# llamadas, tienda a converger siempre en el mismo enfoque "seguro". Forzar la elección
# aquí garantiza variedad real entre leads.
ENFOQUES_ESTILO = [
    ("Rítmico/Festivo", "Destaca el baile, la electrónica en vivo, el loop station y la fiesta."),
    ("Luthería/Eco-Luthier", "Pon el foco en el 'electrobasureo', la originalidad extrema de tocar música electrónica bailable usando percusión construida a partir de materiales 100% reciclados y basura recuperada."),
    ("Colaborativo/Cercano", "Enfatiza la coorganización, taquilla compartida y el apoyo a las salas."),
]

def cargar_epk(band_id=BAND_ID_DEFAULT):
    """
    Carga el EPK de una banda (multi-tenant): 'dossier_epk' en la Google Sheet, enriquecido con
    el JSON curado a mano para band-bakandeya. Ver lib/bandas.py para el detalle de la fusión.
    """
    return bandas.cargar_epk_banda(band_id)


def _detectar_idioma(ciudad, region):
    """
    Detección programática del idioma de destino a partir de ciudad/región del lead.
    Compartida entre pitches de booking (salas/festivales/ayuntamientos) y de medios.
    """
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
    return idioma


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

    # Nombre con el que firma el email: el de gestión definido en el EPK de la banda (multi-tenant).
    nombre_firma = (epk.get("contacto") or {}).get("nombre") or "el equipo de management"
    nombre_banda = epk.get("nombre") or nombre_firma

    idioma = _detectar_idioma(ciudad, region)

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
        "5. ENLACES DEL EMAIL:\n"
        "   - OBLIGATORIO YOUTUBE: Debes incluir SIEMPRE en el texto del email el enlace al vídeo en directo/teaser de YouTube en formato Markdown: "
        "[ver vídeo en directo](https://www.youtube.com/watch?v=y94Noc2qaSM) (o frase equivalente integrada de forma fluida en el cuerpo).\n"
        "   - PROHIBIDO ENLACE AL DOSSIER: El dossier completo en PDF va FÍSICAMENTE ADJUNTO al correo. Menciónalo de forma natural una vez "
        "(ej: 'te adjunto nuestro dossier en PDF con más info'), pero queda TOTALMENTE PROHIBIDO incluir cualquier enlace URL o link al dossier dentro del texto.\n"
        f"6. SALUDO: {instruccion_saludo} Prohibido cualquier placeholder o corchete como '[Nombre del programador]', '[Fecha]', '[Responsable]', etc. "
        f"Esto también aplica a la FIRMA final: firma siempre al final del email con '{nombre_firma}', nunca con un placeholder como '[Tu Nombre]' ni con firmas personales sueltas.\n"
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
        f"10. PRECISIÓN SOBRE DATOS DE LA BANDA: No inventes ni generalices datos que no estén en la información "
        f"del EPK de arriba (integrantes, instrumentos, trayectoria). Si un dato concreto no aparece ahí, no lo "
        f"menciones — mejor omitirlo que inventarlo.{(' ' + epk.get('nota_precision_instrumentos', '')) if epk.get('nota_precision_instrumentos') else ''}\n"
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
            f"[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces y la firma '{nombre_firma}']"
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
            f"[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces y la firma '{nombre_firma}']"
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
            f"[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces y la firma '{nombre_firma}']"
        )

        reglas_redaccion = (
            f"{reglas_calidad}\n"
            "13. Dirígete al programador o responsable de booking de la sala.\n"
            "14. No hables de precios ni de rider técnico. Busca proponer una fecha, ver disponibilidad o proponer un formato de taquilla compartida / coorganización."
        )

    system_prompt = (
        f"Eres {nombre_firma}, el sistema de booking y gestión inteligente de la banda de música {nombre_banda}.\n"
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


# Ángulos de prensa para el pitch a medios. Igual que ENFOQUES_ESTILO, se elige UNO al azar en
# Python (no se le deja al LLM) para garantizar variedad real entre medios distintos.
ENFOQUES_PRENSA = [
    ("Sostenibilidad", "El ángulo de la 'luthería urbana': percusión construida con materiales 100% reciclados como historia de concienciación ambiental, no solo como curiosidad."),
    ("Trayectoria internacional", "El aval profesional de la trayectoria de los integrantes: colaboraciones con Cirque du Soleil, la compañía internacional Stomp y la compañía Toompak."),
    ("Fusión cultural", "La rareza de la mezcla: reggae, música balcánica, klezmer y electrónica conviviendo en un mismo directo — una historia de mestizaje poco habitual en la escena."),
]


def generar_pitch_medio(lead, epk):
    """
    Genera el texto del pitch (ASUNTO + cuerpo) para un contacto de medios (radio, TV, prensa,
    blog musical, canal de redes) usando Gemini y el EPK. A diferencia de generar_pitch_para_lead,
    el objetivo NO es que nos contraten para un concierto — es conseguir cobertura (entrevista,
    reseña, mención, feature). No toca la Google Sheet ni el estado del lead.
    """
    nombre_medio = lead.get("nombre_medio")
    tipo_medio = (lead.get("tipo_medio") or "medio de comunicación").strip().lower()
    ciudad = lead.get("ciudad") or ""
    alcance = lead.get("alcance") or ""
    enfoque_editorial = (lead.get("enfoque_editorial") or "").strip()

    nombre_firma = (epk.get("contacto") or {}).get("nombre") or "el equipo de management"
    nombre_banda = epk.get("nombre") or nombre_firma

    idioma = _detectar_idioma(ciudad, "")
    nombre_enfoque, descripcion_enfoque = random.choice(ENFOQUES_PRENSA)

    if enfoque_editorial:
        instruccion_personalizacion = (
            f"Tienes este dato real sobre su línea editorial, obtenido de su propia web: \"{enfoque_editorial}\". "
            "Úsalo para demostrar que conocéis de verdad lo que cubren (con vuestras propias palabras, no lo copies "
            "literal) — esto pesa más que un ángulo genérico."
        )
    else:
        instruccion_personalizacion = (
            f"No tienes datos específicos de su línea editorial: apóyate en que es un/a {tipo_medio} y adapta el "
            "ángulo a lo que ese tipo de medio suele cubrir (música en directo, cultura, novedades locales...)."
        )

    reglas_prensa = (
        f"1. IDIOMA DE DESTINO OBLIGATORIO: Escribe el email COMPLETO (ASUNTO y Cuerpo) en {idioma}, con tono "
        f"nativo y natural.\n"
        "2. PROHIBIDO BOILERPLATES: nada de 'Espero que estés bien' ni 'Me pongo en contacto con vosotros'. "
        "Empieza con una frase original y directa.\n"
        f"3. ÁNGULO DE PRENSA OBLIGATORIO ({nombre_enfoque}): {descripcion_enfoque}\n"
        f"4. PERSONALIZACIÓN: {instruccion_personalizacion}\n"
        "5. ESTO NO ES UNA PROPUESTA DE CONCIERTO: prohibido hablar de aforo, caché, taquilla, coorganización "
        "o proponer fechas de actuación. El objetivo es conseguir cobertura editorial (entrevista, reseña, "
        "mención, feature), no que os contraten para tocar.\n"
        "6. ENLACES INTEGRADOS: inserta de forma fluida los enlaces del EPK dentro del texto, sin listas al "
        "final. El dossier/press kit en PDF va ADJUNTO (no como link) — menciónalo de forma natural una vez.\n"
        f"7. SALUDO: si no conoces el nombre de una persona concreta de la redacción, saluda de forma cercana y "
        "natural sin placeholders (ej: 'Hola equipo de {nombre_medio},', 'Buenas,'). Firma siempre al final con "
        f"'{nombre_firma}', nunca con un placeholder.\n"
        "8. LONGITUD BREVE: máximo 100-130 palabras en el cuerpo. Frases cortas, una idea por frase.\n"
        "9. LLAMADA A LA ACCIÓN DE PRENSA: ofrece explícitamente algo concreto y fácil de aceptar — una "
        "entrevista breve, fotos/vídeo en alta calidad, o el dossier de prensa adjunto. Nunca un tono de "
        "negociación ('discutir', 'acordar'); sí un tono cercano ('nos encantaría contaros más', 'estamos a "
        "vuestra disposición para lo que necesitéis').\n"
        f"10. PRECISIÓN SOBRE DATOS DE LA BANDA: no inventes ni generalices datos que no estén en el EPK de arriba "
        f"(integrantes, instrumentos, trayectoria). Mejor omitir un dato que inventarlo."
        f"{(' ' + epk.get('nota_precision_instrumentos', '')) if epk.get('nota_precision_instrumentos') else ''}\n"
        "11. PUNTUACIÓN NATURAL: como escribiría una persona real, no una carta formal. Nada de 'Hola, "
        "[nombre],' con coma justo tras 'Hola'."
    )

    prompt = (
        f"Redacta un email de contacto de prensa personalizado para el siguiente medio. "
        f"Escribe todo el texto (asunto y cuerpo) en {idioma}.\n"
        f"- Medio: {nombre_medio}\n"
        f"- Tipo: {tipo_medio}\n"
        f"- Ciudad/Alcance: {ciudad} / {alcance}\n\n"
        "Devuelve la respuesta en el formato exacto:\n"
        "ASUNTO: [Asunto en el idioma correspondiente, llamativo y sin repetir patrones]\n\n"
        f"[Cuerpo del email, 2-3 párrafos CORTOS y directos, incluyendo enlaces y la firma '{nombre_firma}']"
    )

    system_prompt = (
        f"Eres {nombre_firma}, el sistema de comunicación y prensa de la banda de música {nombre_banda}.\n"
        "Tu objetivo es escribir emails de contacto de prensa profesionales, cercanos y persuasivos que "
        "consigan cobertura editorial — NO propuestas de contratación de conciertos.\n\n"
        f"Información de la banda (EPK):\n"
        f"- Nombre: {epk.get('nombre')}\n"
        f"- Estilo: {epk.get('estilo')}\n"
        f"- Integrantes: {', '.join(epk.get('integrantes', []))}\n"
        f"- Influencias: {', '.join(epk.get('influencias', []))}\n"
        f"- Descripción corta: {epk.get('descripcion_corta')}\n"
        f"- Trayectoria destacada: {epk.get('trayectoria_destacada')}\n"
        f"- Enlaces para incluir (teaser, instagram):\n"
        f"  * Teaser en directo (YouTube): {epk.get('enlaces', {}).get('youtube_teaser_aca2026')}\n"
        f"  * Instagram: {epk.get('enlaces', {}).get('instagram')}\n\n"
        "Reglas de Redacción:\n"
        f"{reglas_prensa}"
    )

    return gemini_client.generar_texto_gemini(
        prompt,
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        temperature=0.85
    )


def procesar_nuevos_leads(limite_leads=9999, lead_id_especifico=None, regenerar=False, band_id=BAND_ID_DEFAULT):
    """
    Busca leads en estado 'nuevo' (o cualquiera si se especifica id o regenerar) DE UNA BANDA
    concreta (multi-tenant: filtra por 'band_id', usando band-bakandeya si el lead es de antes de
    multi-tenant y no tiene ese campo). Si tienen email, les genera un pitch usando Gemini y el
    EPK/firma de esa banda, y actualiza su estado a 'pendiente_aprobacion'.
    """
    print(f"[redactor.py] Iniciando procesamiento de nuevos leads (banda: {band_id})...")
    if lead_id_especifico:
        leads = sheets.obtener_leads()
        leads = [l for l in leads if l.get("id") == lead_id_especifico]
        print(f"[redactor.py] Filtrando por ID de lead específico: '{lead_id_especifico}'. Encontrados: {len(leads)}")
    else:
        if regenerar:
            leads_nuevos = sheets.obtener_leads(estado=estados.NUEVO)
            leads_pendientes = sheets.obtener_leads(estado=estados.PENDIENTE)
            leads = leads_nuevos + leads_pendientes
            print(f"[redactor.py] Regenerando pitches. Leads en 'nuevo': {len(leads_nuevos)}, en 'pendiente_aprobacion': {len(leads_pendientes)}")
        else:
            leads = sheets.obtener_leads(estado=estados.NUEVO)
        leads = [l for l in leads if (l.get("band_id") or BAND_ID_DEFAULT) == band_id]

    epk = cargar_epk(band_id)

    if not epk.get("nombre") and not epk.get("descripcion_corta"):
        print(f"[redactor.py] La banda '{band_id}' todavía no ha rellenado su EPK en la app (dossier_epk vacío). Abortando generación para no mandar pitches sin contenido real.")
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


def procesar_nuevos_medios(limite_leads=9999, lead_id_especifico=None, regenerar=False, band_id=BAND_ID_DEFAULT):
    """
    Igual que procesar_nuevos_leads, pero sobre la hoja 'medios_scout' (radio/TV/prensa/canales) y
    usando generar_pitch_medio en vez de generar_pitch_para_lead. También filtra por 'band_id'.
    """
    print(f"[redactor.py] Iniciando procesamiento de nuevos contactos de medios (banda: {band_id})...")
    if lead_id_especifico:
        medios = sheets.obtener_leads(nombre_hoja="medios_scout")
        medios = [m for m in medios if m.get("id") == lead_id_especifico]
        print(f"[redactor.py] Filtrando por ID de medio específico: '{lead_id_especifico}'. Encontrados: {len(medios)}")
    else:
        if regenerar:
            medios_nuevos = sheets.obtener_leads(estado=estados.NUEVO, nombre_hoja="medios_scout")
            medios_pendientes = sheets.obtener_leads(estado=estados.PENDIENTE, nombre_hoja="medios_scout")
            medios = medios_nuevos + medios_pendientes
            print(f"[redactor.py] Regenerando pitches de medios. En 'nuevo': {len(medios_nuevos)}, en 'pendiente_aprobacion': {len(medios_pendientes)}")
        else:
            medios = sheets.obtener_leads(estado=estados.NUEVO, nombre_hoja="medios_scout")
        medios = [m for m in medios if (m.get("band_id") or BAND_ID_DEFAULT) == band_id]

    epk = cargar_epk(band_id)
    if not epk.get("nombre") and not epk.get("descripcion_corta"):
        print(f"[redactor.py] La banda '{band_id}' todavía no ha rellenado su EPK en la app (dossier_epk vacío). Abortando generación para no mandar pitches sin contenido real.")
        return 0

    procesados = 0
    medios_a_procesar = [m for m in medios if m.get("email_contacto")]
    medios_a_procesar = medios_a_procesar[:limite_leads]

    for medio in medios_a_procesar:
        medio_id = medio.get("id")
        email = medio.get("email_contacto")
        nombre_medio = medio.get("nombre_medio")

        pitch = generar_pitch_medio(medio, epk)
        if pitch:
            estados.transicionar(medio, estados.PENDIENTE, pitch=pitch, nombre_hoja="medios_scout")
            procesados += 1
        else:
            print(f"[redactor.py] No se pudo generar pitch para el medio {medio_id} ({nombre_medio}).")

    print(f"[redactor.py] Procesamiento finalizado. Medios redactados y listos para aprobación: {procesados}")
    return procesados


def procesar_todas_las_bandas(limite_leads=9999, regenerar=False, medios=False):
    """
    Punto de entrada multi-tenant por defecto: recorre 'registro_bandas' (solo cuentas activas)
    y ejecuta procesar_nuevos_leads/procesar_nuevos_medios para cada una. Si 'registro_bandas'
    todavía no existe o está vacía, sheets.obtener_bandas_activas() devuelve solo band-bakandeya
    — así el comportamiento single-tenant original no cambia hasta que haya más bandas de verdad.
    """
    total = 0
    for banda in bandas.listar_bandas_activas():
        band_id = banda.get("band_id") or BAND_ID_DEFAULT
        nombre_banda = banda.get("nombre_banda") or band_id
        print(f"[redactor.py] === Banda: {nombre_banda} ({band_id}) ===")
        if medios:
            total += procesar_nuevos_medios(limite_leads=limite_leads, regenerar=regenerar, band_id=band_id)
        else:
            total += procesar_nuevos_leads(limite_leads=limite_leads, regenerar=regenerar, band_id=band_id)
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agente Redactor para generar pitches de leads o de medios.")
    parser.add_argument("--limit", type=int, default=3, help="Límite de filas a redactar.")
    parser.add_argument("--all", action="store_true", help="Procesar todas las filas en estado 'nuevo' que tengan email.")
    parser.add_argument("--id", type=str, default=None, help="ID de una fila específica a redactar (ignora --banda).")
    parser.add_argument("--regenerate", action="store_true", help="Regenerar pitches ya en 'pendiente_aprobacion' además de los nuevos.")
    parser.add_argument("--medios", action="store_true", help="Procesar la hoja 'medios_scout' (prensa/radio/TV/canales) en vez de 'leads'.")
    parser.add_argument("--banda", type=str, default=None, help="band_id concreto a procesar. Si se omite, procesa todas las bandas activas de 'registro_bandas'.")
    args = parser.parse_args()

    limite = 99999 if args.all else args.limit
    if args.id:
        if args.medios:
            procesar_nuevos_medios(limite_leads=limite, lead_id_especifico=args.id, regenerar=args.regenerate)
        else:
            procesar_nuevos_leads(limite_leads=limite, lead_id_especifico=args.id, regenerar=args.regenerate)
    elif args.banda:
        if args.medios:
            procesar_nuevos_medios(limite_leads=limite, regenerar=args.regenerate, band_id=args.banda)
        else:
            procesar_nuevos_leads(limite_leads=limite, regenerar=args.regenerate, band_id=args.banda)
    else:
        procesar_todas_las_bandas(limite_leads=limite, regenerar=args.regenerate, medios=args.medios)
