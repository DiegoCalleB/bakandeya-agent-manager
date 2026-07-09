import sys
import os
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.sheets as sheets
import lib.gmail_client as gmail_client
import lib.telegram as telegram

def enviar_leads_aprobados():
    """
    Busca leads en estado 'aprobado'. Envía el email con el pitch generado 
    y cambia el estado a 'esperando_respuesta'. Notifica por Telegram.
    """
    print("[enviador.py] Iniciando envío de leads aprobados...")
    leads = sheets.obtener_leads(estado="aprobado")
    enviados = 0
    
    for lead in leads:
        lead_id = lead.get("id")
        email = lead.get("email_contacto")
        nombre_sala = lead.get("nombre_sala")
        pitch = lead.get("pitch_generado")
        
        if not email or not pitch:
            print(f"[enviador.py] Lead {lead_id} ({nombre_sala}) no tiene email de contacto o pitch generado. Se omite.")
            continue
            
        asunto = f"Propuesta de concierto: Bakandeya en {nombre_sala}"
        print(f"[enviador.py] Enviando propuesta a {email}...")
        
        res = gmail_client.enviar_email(email, asunto, pitch)
        if res:
            sheets.actualizar_estado_lead(lead_id, "esperando_respuesta")
            telegram.enviar_notificacion_telegram(f"📧 Email enviado a *{nombre_sala}* ({email})")
            enviados += 1
            
    print(f"[enviador.py] Envíos finalizados. Total emails enviados: {enviados}")
    return enviados

if __name__ == "__main__":
    enviar_leads_aprobados()
