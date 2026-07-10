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

def procesar_nuevos_leads(limite_leads=9999, lead_id_especifico=None):
    """
    Busca leads en estado 'nuevo'. Si tienen email, les genera un pitch 
    usando Gemini y la información del EPK, y actualiza su estado a 'pendiente_aprobacion'.
    """
    print("[redactor.py] Iniciando procesamiento de nuevos leads...")
    leads = sheets.obtener_leads(estado=estados.NUEVO)
    
    if lead_id_especifico:
        leads = [l for l in leads if l.get("id") == lead_id_especifico]
        print(f"[redactor.py] Filtrando por ID de lead específico: '{lead_id_especifico}'. Encontrados: {len(leads)}")
        
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
        
        if tipo == "ayuntamiento":
            print(f"[redactor.py] Generando pitch para Ayuntamiento: {nombre_sala} ({lead.get('ciudad')})...")
            prompt = (
                f"Redacta una propuesta artística para las programaciones culturales o festejos del siguiente ayuntamiento:\n"
                f"- Ayuntamiento: {nombre_sala}\n"
                f"- Ciudad/Región: {lead.get('ciudad')} / {lead.get('region') or ''}\n\n"
                "Devuelve la respuesta en texto plano con el siguiente formato exacto:\n"
                "ASUNTO: [Asunto llamativo y profesional, ej. Propuesta artística: Bakandeya - Fusión festiva y percusión reciclada para las fiestas]\n\n"
                "[Cuerpo del email, máximo 3 párrafos, incluyendo enlaces]"
            )
            
            reglas_redaccion = (
                "1. Tono profesional, cercano, dinámico y con energía festiva. Dirígete a la concejalía de festejos o de cultura.\n"
                "2. Sé conciso: 3 párrafos máximo. Presenta a la banda como una opción ideal para fiestas patronales, festivales municipales, plazas y eventos al aire libre por su formato vibrante y apto para todos los públicos.\n"
                "3. Propón una contratación artística directa por caché (menciona que nos adaptamos al presupuesto y al formato del festejo, pero sin dar cifras exactas en este primer contacto).\n"
                "4. Asegúrate de incluir los enlaces de manera natural en el cuerpo."
            )
        elif tipo == "festival":
            print(f"[redactor.py] Generando pitch para Festival: {nombre_sala}... ")
            prompt = (
                f"Redacta una propuesta artística para el siguiente festival:\n"
                f"- Festival: {nombre_sala}\n"
                f"- Ciudad/Región: {lead.get('ciudad')} / {lead.get('region') or ''}\n"
                f"- Estilo habitual/Género: {lead.get('genero')}\n\n"
                "Devuelve la respuesta en texto plano con el siguiente formato exacto:\n"
                "ASUNTO: [Asunto llamativo y profesional, ej. Propuesta Artística: Bakandeya en [Nombre Festival]]\n\n"
                "[Cuerpo del email, máximo 3 párrafos, incluyendo enlaces]"
            )
            
            reglas_redaccion = (
                "1. Tono cercano, profesional y de gran energía festivalera. Dirígete al equipo de programación/booking.\n"
                "2. Sé conciso: 3 párrafos máximo. Explica brevemente por qué Bakandeya y su 'electrobasureo' (percusión reciclada + electrónica) encajarían a la perfección en la programación y harían vibrar al público del festival.\n"
                "3. Menciona que buscas hueco en el cartel y que estás disponible para contratación directa por caché / condiciones habituales de festival.\n"
                "4. Asegúrate de incluir los enlaces de manera natural en el cuerpo."
            )
        else:
            print(f"[redactor.py] Generando pitch para la sala: {nombre_sala} ({lead.get('ciudad')})...")
            prompt = (
                f"Redacta una propuesta de concierto personalizada para la siguiente sala:\n"
                f"- Nombre de la sala: {nombre_sala}\n"
                f"- Ciudad: {lead.get('ciudad')}\n"
                f"- Aforo estimado: {lead.get('aforo')} personas\n"
                f"- Estilo habitual de la sala: {lead.get('genero')}\n\n"
                "Devuelve la respuesta en texto plano con el siguiente formato exacto:\n"
                "ASUNTO: [Asunto llamativo y profesional]\n\n"
                "[Cuerpo del email, máximo 3 párrafos, incluyendo enlaces]"
            )
            
            reglas_redaccion = (
                "1. Tono cercano, profesional y con energía festivalera. Evita el tono corporativo o robótico.\n"
                "2. Sé conciso: 3 párrafos máximo. Explica por qué Bakandeya encaja en su programación habitual de conciertos de sala.\n"
                "3. No hables de precios ni de rider técnico en este primer contacto, solo busca proponer una fecha o ver disponibilidad (taquilla compartida/coorganización).\n"
                "4. Asegúrate de incluir los enlaces de manera natural en el cuerpo."
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
    args = parser.parse_args()
    
    limite = 99999 if args.all else args.limit
    procesar_nuevos_leads(limite_leads=limite, lead_id_especifico=args.id)
