import sys
import os
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import lib.sheets as sheets
import lib.gemini_client as gemini_client
import lib.estados as estados

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
            
        tipo = lead.get("tipo")
        tipo = tipo.strip().lower() if (tipo and isinstance(tipo, str)) else "sala"
        
        ciudad = lead.get("ciudad") or ""
        region = lead.get("region") or ""
        aforo = lead.get("aforo") or 0
        genero = lead.get("genero") or "Varios"
        
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

        # Reglas base comunes de alta calidad
        reglas_calidad = (
            f"1. IDIOMA DE DESTINO OBLIGATORIO: Escribe el email COMPLETO (tanto el ASUNTO como el Cuerpo) en {idioma}. "
            f"Usa un tono nativo, natural y fluido en {idioma}, adaptando los modismos de forma idiomática.\n"
            "2. PROHIBIDO BOILERPLATES Y REPETICIONES: No uses introducciones aburridas como 'Espero que estés bien', 'Espero que todo vaya genial', 'Me pongo en contacto', etc. "
            "Empieza cada email con una frase o saludo original y directo. Varía las palabras en cada propuesta.\n"
            "3. ENFOQUES ROTATIVOS DE ESTILO: Elige uno de estos tres enfoques para redactar esta propuesta (elije según convenga y varíalo): \n"
            "   - Enfoque Rítmico/Festivo: Destaca el baile, la electrónica en vivo, el loop station y la fiesta.\n"
            "   - Enfoque Luthería/Eco-Luthier: Pon el foco en el 'electrobasureo', la originalidad extrema de tocar música electrónica bailable usando percusión construida a partir de materiales 100% reciclados y basura recuperada.\n"
            "   - Enfoque Colaborativo/Cercano: Enfatiza la coorganización, taquilla compartida y el apoyo a las salas.\n"
            "4. GANCHO DE AFORO Y GÉNERO: Incorpora el género del local y adapta el discurso al aforo: \n"
            f"   - Si el aforo es pequeño (< 300 personas, aforo actual del local: {aforo}), enfócalo como un show íntimo de alta energía, interacción cara a cara y conexión directa con el público.\n"
            f"   - Si el aforo es mediano/grande (>= 300 personas, aforo actual del local: {aforo}), enfócalo como una noche de clubbing, fiesta explosiva y baile masivo idóneo para llenar su espacio.\n"
            "5. ENLACES INTEGRADOS: Inserta de manera fluida y dentro del texto los enlaces del EPK (sin listas feas al final).\n"
            f"6. PROHIBIDO PLACEHOLDERS O CORCHETES: Está estrictamente prohibido incluir marcadores de posición o textos entre corchetes como '[Nombre del programador]', '[Fecha]', '[Responsable]', etc. Si no conoces el nombre de la persona, saluda siempre de forma cercana y natural (ej: 'Hola al equipo de {nombre_sala},', 'Hola gente de {nombre_sala},', 'Buenas,')."
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
                "[Cuerpo del email, máximo 3 párrafos, incluyendo enlaces]"
            )
            
            reglas_redaccion = (
                f"{reglas_calidad}\n"
                "6. Dirígete de manera profesional y cercana a la concejalía de festejos, cultura o juventud.\n"
                "7. Presenta el proyecto como una opción perfecta para plazas, festivales municipales y eventos al aire libre por su carácter festivo, familiar y ecológico (concienciación ambiental por percusión reciclada).\n"
                "8. Propón contratación por caché o convenios culturales."
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
                "[Cuerpo del email, máximo 3 párrafos, incluyendo enlaces]"
            )
            
            reglas_redaccion = (
                f"{reglas_calidad}\n"
                "6. Dirígete al equipo de programación, dirección artística o booking del festival.\n"
                "7. Explica cómo la mezcla de electrónica bailable, beatbox en vivo y percusión reciclada (luthería urbana) encaja perfectamente en su cartel y sorprenderá a su público.\n"
                "8. Busca proponer contratación directa por caché o condiciones de festival."
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
                "[Cuerpo del email, máximo 3 párrafos, incluyendo enlaces]"
            )
            
            reglas_redaccion = (
                f"{reglas_calidad}\n"
                "6. Dirígete al programador o responsable de booking de la sala.\n"
                "7. No hables de precios ni de rider técnico. Busca proponer una fecha, ver disponibilidad o proponer un formato de taquilla compartida / coorganización."
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
            f"- Enlaces para incluir (Spotify, directo, dossier, instagram):\n"
            f"  * Spotify: {epk.get('enlaces', {}).get('spotify')}\n"
            f"  * Vídeo Directo (YouTube): {epk.get('enlaces', {}).get('youtube_directo')}\n"
            f"  * Dossier / Rider PDF: {epk.get('enlaces', {}).get('dossier_epk')}\n"
            f"  * Instagram: {epk.get('enlaces', {}).get('instagram')}\n\n"
            "Reglas de Redacción:\n"
            f"{reglas_redaccion}"
        )
        
        pitch = gemini_client.generar_texto_gemini(
            prompt, 
            model_name="gemini-2.5-flash", 
            system_instruction=system_prompt,
            temperature=0.7
        )
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
