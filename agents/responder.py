import sys
import os
import json
from datetime import datetime

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

import lib.sheets as sheets
import lib.estados as estados
import lib.telegram as telegram
import lib.gmail_client as gmail_client
from lib.gemini_client import generar_texto_gemini

def cargar_epk():
    ruta_epk = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "epk_bakandeya.json")
    try:
        with open(ruta_epk, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[responder.py] Error al cargar el EPK: {e}")
        return {}

def obtener_ultimo_email_de_contacto(email_contacto):
    """
    Busca en Gmail la última interacción con el destinatario para extraer el cuerpo
    y el threadId para la respuesta.
    """
    if gmail_client.es_modo_simulado():
        print(f"[responder.py] MODO SIMULADO: Buscando última interacción simulada...")
        respuestas = gmail_client.leer_respuestas()
        for r in respuestas:
            if email_contacto.lower() in r.get("remitente", "").lower():
                return r
        return None

    try:
        service = gmail_client.obtener_servicio_gmail()
        # Buscamos correos relacionados con el contacto
        query = email_contacto
        resultado = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        mensajes = resultado.get('messages', [])
        if not mensajes:
            return None
            
        # El primero de la lista devuelta es el más reciente
        ultimo_msg_id = mensajes[0]['id']
        m_det = service.users().messages().get(userId='me', id=ultimo_msg_id, format='full').execute()
        
        headers = m_det.get('payload', {}).get('headers', [])
        remitente = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Desconocido")
        asunto = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "Sin Asunto")
        fecha = next((h['value'] for h in headers if h['name'].lower() == 'date'), "Sin Fecha")
        message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
        
        # Obtener cuerpo del correo
        parts = m_det.get('payload', {}).get('parts', [])
        cuerpo = ""
        if not parts:
            cuerpo_data = m_det.get('payload', {}).get('body', {}).get('data', '')
            if cuerpo_data:
                import base64
                cuerpo = base64.urlsafe_b64decode(cuerpo_data).decode('utf-8', errors='ignore')
        else:
            for part in parts:
                if part.get('mimeType') == 'text/plain':
                    cuerpo_data = part.get('body', {}).get('data', '')
                    if cuerpo_data:
                        import base64
                        cuerpo = base64.urlsafe_b64decode(cuerpo_data).decode('utf-8', errors='ignore')
                        break
                        
        return {
            "id": ultimo_msg_id,
            "threadId": m_det.get("threadId"),
            "messageId": message_id,
            "remitente": remitente,
            "asunto": asunto,
            "fecha": fecha,
            "cuerpo": cuerpo
        }
    except Exception as e:
        print(f"[responder.py] Error al obtener el último email de {email_contacto}: {e}")
        return None

def responder_leads_interesados():
    """
    Escanea leads en 'interesado' o 'negociando' (que no tengan respuesta de seguimiento ya en borrador),
    lee la última respuesta recibida y redacta una contestación inteligente en borrador de Gmail.
    """
    print("[responder.py] Iniciando generación de borradores de respuestas...")
    leads_interesados = sheets.obtener_leads(estado="interesado")
    leads_negociando = sheets.obtener_leads(estado="negociando")
    leads = leads_interesados + leads_negociando
    
    if not leads:
        print("[responder.py] No hay leads en estado 'interesado' o 'negociando' para responder.")
        return 0
        
    epk = cargar_epk()
    borradores_creados = 0
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    
    for lead in leads:
        lead_id = lead.get("id")
        nombre_sala = lead.get("nombre_sala")
        email = lead.get("email_contacto")
        notas = lead.get("notas") or ""
        
        # Evitar re-redactar si ya respondimos a la última respuesta del lead.
        # Si la última entrada en notas es un borrador de respuesta hoy, y NO hay un email recibido posterior, saltamos.
        pos_recibido = notas.rfind("Respuesta recibida")
        pos_redactado = notas.rfind("Respuesta redactada en borrador")
        if pos_redactado != -1 and pos_redactado > pos_recibido and fecha_hoy in notas[pos_redactado:]:
            print(f"[responder.py] Lead {lead_id} ({nombre_sala}) ya tiene un borrador de respuesta redactado para el mensaje más reciente hoy. Saltando.")
            continue
            
        if not email:
            print(f"[responder.py] Lead {lead_id} ({nombre_sala}) no tiene email. Saltando.")
            continue
            
        print(f"[responder.py] Buscando última respuesta de '{nombre_sala}' ({email})...")
        ultimo_email = obtener_ultimo_email_de_contacto(email)
        
        if not ultimo_email:
            print(f"[responder.py] No se encontró ninguna conversación previa con {email} en Gmail. Saltando.")
            continue
            
        cuerpo_respuesta = ultimo_email.get("cuerpo", "").strip()
        asunto_original = ultimo_email.get("asunto", "")
        thread_id = ultimo_email.get("threadId")
        
        print(f"[responder.py] Redactando respuesta contextualizada para '{nombre_sala}'...")
        
        # Obtener datos de contacto dinámicos del EPK
        contacto_info = epk.get("contacto", {})
        c_nombre = contacto_info.get("nombre", "Jose (Filgue)")
        c_telefono = contacto_info.get("telefono", "+34 660107178")
        c_rol = contacto_info.get("rol", "Manager de la banda")

        instruccion_sistema = (
            "Eres el manager virtual de la banda Bakandeya, un proyecto de Electrobasura / Reggae / Balkan Punk de Madrid.\n"
            "Tu tono es enérgico, fresco, profesional, cercano y asertivo.\n"
            "Debes redactar una respuesta al email que nos envió la sala, usando la información del EPK de la banda.\n\n"
            f"Información de la banda (EPK):\n"
            f"- Nombre: {epk.get('nombre')}\n"
            f"- Estilo: {epk.get('estilo')}\n"
            f"- Caché objetivo: {epk.get('cache_objetivo')}\n"
            f"- Disponibilidad: {epk.get('disponibilidad')}\n"
            f"- Integrantes: {', '.join(epk.get('integrantes', []))}\n"
            f"- Rider Técnico: {epk.get('rider_tecnico', {}).get('descripcion')}\n"
            f"- Contacto oficial de la banda para cerrar bolos: {c_nombre} ({c_rol}) - Teléfono/WhatsApp: {c_telefono}\n"
            f"- Enlaces:\n"
            f"  * Spotify: {epk.get('enlaces', {}).get('spotify')}\n"
            f"  * YouTube: {epk.get('enlaces', {}).get('youtube_directo')}\n"
            f"  * Dossier / Rider PDF: {epk.get('enlaces', {}).get('dossier_epk')}\n\n"
            "REGLAS OBLIGATORIAS DE NEGOCIACIÓN:\n"
            "1. DISCLOSURE E IDENTIDAD: Debes firmar siempre y únicamente como 'Bakandeya Virtual Manager' (o indicar de forma natural al final que eres el asistente de inteligencia artificial de la banda).\n"
            f"2. INTERVENCIÓN HUMANA OBLIGATORIA: Nunca aceptes formalmente una oferta final, un caché definitivo o un contrato de forma vinculante por ti mismo. Deja siempre claro que los detalles finales del acuerdo deben ser confirmados de forma directa y humana por {c_nombre}, {c_rol}.\n"
            f"3. PROPUESTA DE CONTACTO TELEFÓNICO EXCLUSIVO: Ofrece siempre de manera proactiva al programador del local la posibilidad de llamar o escribir por teléfono/WhatsApp exclusivamente a {c_nombre} ({c_telefono}) para concretar y cerrar los detalles. NO utilices el nombre de Jose (Filgue) para las llamadas o contacto, dirígelos únicamente a {c_nombre}."
        )
        
        prompt = (
            f"La sala o festival '{nombre_sala}' nos ha respondido el siguiente email:\n"
            f"\"\"\"\n{cuerpo_respuesta}\n\"\"\"\n\n"
            f"Escribe un email de respuesta adaptado:\n"
            f"1. Agradece su interés y responde a sus dudas o propuestas de manera clara y profesional.\n"
            f"2. Si preguntan por caché o dinero, mantén la postura del EPK de negociar según aforo y condiciones, pero propón un rango razonable o pregunta qué condiciones de taquilla/caché manejan normalmente, recordando que {c_nombre} validará la oferta definitiva.\n"
            f"3. Si proponen fecha o disponibilidad, confirma que tenemos flexibilidad en los fines de semana y propón evaluar fechas concretas, indicando que pueden hablar con {c_nombre} directamente.\n"
            f"4. Mantén la propuesta corta (máximo 3 párrafos), profesional, animada y orientada a cerrar el bolo.\n"
            f"5. Invítales obligatoriamente a contactar por teléfono o escribir por WhatsApp a {c_nombre} al número literal {c_telefono} para concretar detalles.\n"
            f"6. Firma obligatoriamente como 'Bakandeya Virtual Manager'. Devuelve ÚNICAMENTE el cuerpo del email redactado, sin asunto y sin comentarios adicionales."
        )
        
        cuerpo_respuesta_ia = generar_texto_gemini(prompt, system_instruction=instruccion_sistema, temperature=0.7)
        if not cuerpo_respuesta_ia:
            print(f"[responder.py] Error al generar respuesta con IA para {nombre_sala}.")
            continue
            
        asunto_respuesta = asunto_original
        if not asunto_respuesta.lower().startswith("re:"):
            asunto_respuesta = f"Re: {asunto_respuesta}"
            
        print(f"[responder.py] Creando borrador de respuesta para {email} (Asunto: {asunto_respuesta})...")
        res_draft = gmail_client.crear_borrador(
            email, asunto_respuesta, cuerpo_respuesta_ia, 
            thread_id=thread_id, in_reply_to=ultimo_email.get("messageId")
        )
        
        if res_draft:
            borradores_creados += 1
            nueva_nota = f"Respuesta redactada en borrador el {fecha_hoy}."
            notas_actualizadas = (notas.strip() + "\n" + nueva_nota) if notas.strip() else nueva_nota
            
            # Cambiar estado a 'negociando'
            estados.transicionar(lead, estados.NEGOCIANDO, notas=notas_actualizadas)
            telegram.enviar_notificacion_telegram(
                f"📝 *Borrador de Respuesta Creado* para *{nombre_sala}* ({email})\n"
                f"• Estado actualizado a: *NEGOCIANDO*"
            )
            print(f"[responder.py] Borrador creado con éxito para {nombre_sala}. Lead actualizado a 'negociando'.")
        else:
            print(f"[responder.py] Error al crear borrador para {nombre_sala}.")
            
    print(f"[responder.py] Proceso finalizado. Total borradores de respuesta creados: {borradores_creados}")
    return borradores_creados

if __name__ == "__main__":
    responder_leads_interesados()
