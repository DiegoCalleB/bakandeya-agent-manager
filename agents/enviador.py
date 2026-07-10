import sys
import os
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.sheets as sheets
import lib.gmail_client as gmail_client
import lib.telegram as telegram
import lib.estados as estados


def parsear_pitch(pitch, nombre_sala):
    """
    Separa el pitch generado por el redactor en (asunto, cuerpo).

    El redactor devuelve siempre el formato:  ``ASUNTO: <asunto>\\n\\n<cuerpo>``.
    Aquí extraemos ese asunto para usarlo como asunto REAL del email, en vez de tirarlo
    y dejar la línea 'ASUNTO: ...' colgando dentro del cuerpo (que era el bug).

    Degradación segura: si por lo que sea el pitch no trae el marcador ``ASUNTO:``, se usa
    un asunto genérico y el pitch completo como cuerpo. Nunca falla.
    """
    asunto_generico = f"Propuesta de concierto: Bakandeya en {nombre_sala}"
    if not pitch:
        return asunto_generico, ""

    texto = pitch.strip()
    # Separamos solo en la primera línea: el resto es el cuerpo tal cual.
    primera_linea, _, resto = texto.partition("\n")

    if primera_linea.strip().upper().startswith("ASUNTO:"):
        asunto = primera_linea.split(":", 1)[1].strip().strip('"').strip()
        cuerpo = resto.strip()
        return (asunto or asunto_generico), cuerpo

    # Sin marcador reconocible: no arriesgamos, mandamos todo como cuerpo.
    return asunto_generico, texto


def enviar_leads_aprobados():
    """
    Busca leads en estado 'aprobado'. Crea un borrador en Gmail con el pitch generado 
    y cambia el estado a 'esperando_respuesta'. Notifica por Telegram.
    """
    print("[enviador.py] Iniciando creación de borradores para leads aprobados...")
    leads = sheets.obtener_leads(estado=estados.APROBADO)
    enviados = 0
    
    for lead in leads:
        lead_id = lead.get("id")
        email = lead.get("email_contacto")
        nombre_sala = lead.get("nombre_sala")
        pitch = lead.get("pitch_generado")
        
        if not email or not pitch:
            print(f"[enviador.py] Lead {lead_id} ({nombre_sala}) no tiene email de contacto o pitch generado. Se omite.")
            continue
            
        asunto, cuerpo = parsear_pitch(pitch, nombre_sala)
        print(f"[enviador.py] Creando borrador en Gmail para {email} (asunto: {asunto})...")

        res = gmail_client.crear_borrador(email, asunto, cuerpo)
        if res:
            estados.transicionar(lead, estados.ESPERANDO)
            telegram.enviar_notificacion_telegram(f"📝 Borrador de email creado para *{nombre_sala}* ({email})")
            enviados += 1
            
    print(f"[enviador.py] Creación de borradores finalizada. Total borradores creados: {enviados}")
    return enviados

if __name__ == "__main__":
    enviar_leads_aprobados()
