import sys
import os
import re
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

# Días a esperar antes de enviar un seguimiento
DIAS_ESPERA_SEGUIMIENTO = 10

def parsear_pitch(pitch, nombre_sala):
    """
    Parsea el pitch generado para extraer el asunto y el cuerpo.
    Formato esperado:
    ASUNTO: <asunto>

    <cuerpo>
    """
    lineas = (pitch or "").strip().split("\n")
    if not lineas:
        return "Propuesta de concierto: Bakandeya", pitch
        
    primera_linea = lineas[0]
    resto = "\n".join(lineas[1:])
    asunto_generico = f"Propuesta de concierto: Bakandeya en {nombre_sala}"
    
    if primera_linea.strip().upper().startswith("ASUNTO:"):
        asunto = primera_linea.split(":", 1)[1].strip().strip('"').strip()
        cuerpo = resto.strip()
        return (asunto or asunto_generico), cuerpo
        
    return asunto_generico, pitch

def obtener_num_seguimiento(notas):
    """
    Determina si toca enviar el Seguimiento 1, el 2, o ninguno.
    """
    notas_str = (notas or "").lower()
    if "seguimiento 2" in notas_str:
        return None  # Ya se enviaron los 2 seguimientos
    if "seguimiento 1" in notas_str:
        return 2  # Toca el segundo seguimiento
    return 1  # Toca el primer seguimiento

def redactar_seguimiento_ia(nombre_sala, original_pitch, num_seguimiento):
    """
    Usa Gemini para redactar un correo de seguimiento contextualizado.
    """
    asunto_original, cuerpo_original = parsear_pitch(original_pitch, nombre_sala)
    
    instruccion_sistema = (
        "Eres el manager de la banda Bakandeya, un proyecto de Electrobasura / Reggae / Balkan Punk de Madrid. "
        "Tu tono es fresco, enérgico, cercano, pero profesional y educado. "
        "Vas a redactar un correo corto de seguimiento (follow-up) para el programador de una sala o festival."
    )
    
    prompt = (
        f"Redacta el correo de seguimiento número {num_seguimiento} para la sala o festival '{nombre_sala}'.\n\n"
        f"El pitch original que enviamos hace unos días fue:\n"
        f"\"\"\"\n{cuerpo_original}\n\"\"\"\n\n"
        f"Instrucciones clave:\n"
        f"1. Debe ser un correo corto (2-3 párrafos máximo, muy rápido de leer).\n"
        f"2. Recuerda de forma educada que les enviamos una propuesta de concierto hace unos días y pregunta si han tenido ocasión de revisarla.\n"
        f"3. Mantén el estilo fresco y directo de la banda, pero sin sonar pesado, insistente o de reproche.\n"
        f"4. No inventes detalles o condiciones financieras nuevas que no estén en el correo original.\n"
        f"5. Termina invitándoles a responder por email o por WhatsApp si les viene mejor.\n"
        f"6. Devuelve ÚNICAMENTE el cuerpo del mensaje redactado, sin líneas de asunto y sin comentarios introductorios."
    )
    
    print(f"[seguimiento] Consultando a Gemini para redactar seguimiento {num_seguimiento} para '{nombre_sala}'...")
    respuesta = generar_texto_gemini(prompt, system_instruction=instruccion_sistema, temperature=0.7)
    return respuesta.strip() if respuesta else None

def ejecutar_seguimiento():
    """
    Busca leads en 'esperando_respuesta', comprueba fechas y crea borradores de seguimiento.
    """
    print("[seguimiento] Iniciando análisis de leads para seguimiento...")
    leads = sheets.obtener_leads(estado=estados.ESPERANDO)
    
    fecha_hoy = datetime.now()
    fecha_hoy_str = fecha_hoy.strftime("%Y-%m-%d")
    borradores_creados = 0
    
    for lead in leads:
        lead_id = lead.get("id")
        nombre_sala = lead.get("nombre_sala")
        email = lead.get("email_contacto")
        fecha_envio_str = lead.get("fecha_envio")
        notas = lead.get("notas") or ""
        original_pitch = lead.get("pitch_generado")
        
        if not email:
            print(f"[seguimiento] Lead {lead_id} ({nombre_sala}) no tiene email de contacto. Se omite.")
            continue
            
        if not fecha_envio_str:
            print(f"[seguimiento] Lead {lead_id} ({nombre_sala}) está en 'esperando_respuesta' pero no tiene fecha_envio registrada. Se omite.")
            continue
            
        try:
            fecha_envio = datetime.strptime(fecha_envio_str.strip(), "%Y-%m-%d")
        except ValueError:
            print(f"[seguimiento] Lead {lead_id} ({nombre_sala}) tiene una fecha_envio inválida: '{fecha_envio_str}'. Se omite.")
            continue
            
        dias_transcurridos = (fecha_hoy - fecha_envio).days
        print(f"[seguimiento] Lead {lead_id} ({nombre_sala}): {dias_transcurridos} días esperando respuesta (fecha_envio: {fecha_envio_str}).")
        
        if dias_transcurridos >= DIAS_ESPERA_SEGUIMIENTO:
            num_seguimiento = obtener_num_seguimiento(notas)
            if num_seguimiento is None:
                print(f"[seguimiento] Lead {lead_id} ({nombre_sala}) ya ha recibido los 2 seguimientos correspondientes. No se hace nada.")
                continue
                
            print(f"[seguimiento] ¡Alerta! Lead {lead_id} ({nombre_sala}) requiere Seguimiento {num_seguimiento}.")
            
            # Redactar con IA
            cuerpo_seguimiento = redactar_seguimiento_ia(nombre_sala, original_pitch, num_seguimiento)
            if not cuerpo_seguimiento:
                print(f"[seguimiento] ERROR: No se pudo generar el cuerpo del seguimiento con Gemini para '{nombre_sala}'.")
                continue
                
            # Extraer asunto original para usarlo como hilo de conversación
            asunto_original, _ = parsear_pitch(original_pitch, nombre_sala)
            asunto_seguimiento = f"Re: {asunto_original}"
            
            # Crear borrador en Gmail
            print(f"[seguimiento] Creando borrador en Gmail para {email} (Asunto: {asunto_seguimiento})...")
            draft = gmail_client.crear_borrador(email, asunto_seguimiento, cuerpo_seguimiento)
            
            if draft:
                borradores_creados += 1
                # Actualizar notas y fecha_envio en Sheets
                nueva_nota = f"Seguimiento {num_seguimiento} redactado en borrador el {fecha_hoy_str}."
                notas_actualizadas = (notas.strip() + "\n" + nueva_nota) if notas.strip() else nueva_nota
                
                # Actualizamos datos del lead
                sheets.actualizar_datos_lead(lead_id, {
                    "notas": notas_actualizadas,
                    "fecha_envio": fecha_hoy_str  # Reiniciar el contador de días para el siguiente seguimiento
                })
                print(f"[seguimiento] Lead {lead_id} actualizado en Sheets con fecha_envio a hoy ({fecha_hoy_str}) y nota registrada.")
                
                # Telegram
                telegram.enviar_notificacion_telegram(
                    f"📨 *Borrador de Seguimiento {num_seguimiento} creado*:\n"
                    f"• *Destinatario*: {nombre_sala} ({email})\n"
                    f"• *Asunto*: {asunto_seguimiento}"
                )
            else:
                print(f"[seguimiento] ERROR: No se pudo crear el borrador en Gmail para {email}.")
                
    print(f"[seguimiento] Análisis finalizado. Total de borradores creados: {borradores_creados}")
    return borradores_creados

if __name__ == "__main__":
    ejecutar_seguimiento()
