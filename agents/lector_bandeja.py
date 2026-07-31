import sys
import os
import re
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.sheets as sheets
import lib.gmail_client as gmail_client
import lib.gemini_client as gemini_client
import lib.telegram as telegram
import lib.estados as estados
import lib.metricas as metricas

_RE_NOMBRE_REMITENTE = re.compile(r'^"?([^"<]+?)"?\s*<[^>]+>$')


def _extraer_nombre_remitente(remitente):
    """
    Extrae el nombre visible de una cabecera 'From' tipo 'Nombre Apellido <email@dominio.com>'.
    Si no hay nombre (solo la dirección), devuelve el email tal cual.
    """
    if not remitente:
        return ""
    m = _RE_NOMBRE_REMITENTE.match(remitente.strip())
    return m.group(1).strip() if m else remitente.strip()


def procesar_bandeja_entrada():
    """
    Busca respuestas sin leer en Gmail, identifica el lead que estaba esperando
    respuesta, las clasifica con Claude y actualiza la hoja de cálculo.
    """
    print("[lector_bandeja.py] Iniciando lectura de respuestas...")
    respuestas = gmail_client.leer_respuestas()
    leads_esperando = (
        sheets.obtener_leads(estado=estados.ESPERANDO) +
        sheets.obtener_leads(estado=estados.INTERESADO) +
        sheets.obtener_leads(estado=estados.NEGOCIANDO)
    )
    
    if not respuestas:
        print("[lector_bandeja.py] No hay nuevas respuestas en la bandeja.")
        return 0
        
    clasificados = 0
    
    for respuesta in respuestas:
        remitente = respuesta.get("remitente")
        cuerpo = respuesta.get("cuerpo")
        
        # Intentar emparejar la respuesta con un lead esperando respuesta por email
        lead_asociado = None
        for lead in leads_esperando:
            email_lead = lead.get("email_contacto")
            if email_lead and email_lead.lower() in remitente.lower():
                lead_asociado = lead
                break
                
        if not lead_asociado:
            # Si el email no coincide con ningún lead esperando, se omite
            continue
            
        lead_id = lead_asociado.get("id")
        nombre_sala = lead_asociado.get("nombre_sala")
        
        print(f"[lector_bandeja.py] Nueva respuesta de '{nombre_sala}' ({remitente}). Clasificando...")
        
        prompt = (
            f"Analiza la siguiente respuesta recibida de un local/festival a nuestra propuesta de concierto:\n\n"
            f"Asunto: {respuesta.get('asunto')}\n"
            f"Cuerpo:\n{cuerpo}\n\n"
            "Devuelve un objeto JSON estructurado con las siguientes claves:\n"
            "1. 'categoria': una de estas tres opciones estrictas: 'interesado', 'no_interesado', 'negociando'.\n"
            "2. 'fecha_propuesta': fecha o rango de fechas sugerido por el recinto si lo mencionan (ej. '15 de noviembre', 'fines de semana de octubre'), o null si no proponen fechas.\n"
            "3. 'oferta_economica': condiciones de caché, taquilla o entrada mencionadas (ej. '80% taquilla (10€ entrada)', 'caché fijo 500€', 'entrada libre'), o null si no especifican dinero.\n"
            "4. 'resumen': síntesis de 1-2 frases del mensaje en tono claro y directo.\n"
        )
        
        system_prompt = (
            "Eres un analista experto de respuestas de booking para la banda de música Bakandeya. "
            "Devuelve únicamente un objeto JSON válido con el esquema exacto solicitado."
        )
        
        # Gemini 2.5 Flash en modo JSON para análisis rápido y estructurado
        json_str = gemini_client.generar_texto_gemini(
            prompt, 
            model_name="gemini-2.5-flash", 
            system_instruction=system_prompt,
            temperature=0.1,
            forzar_json=True
        )
        
        datos_analizados = {}
        if json_str:
            try:
                datos_analizados = json.loads(json_str)
            except Exception as e:
                print(f"[lector_bandeja.py] Error al parsear JSON de Gemini: {e}. Respuesta: {json_str}")
        
        categoria = (datos_analizados.get("categoria") or "").strip().lower()
        if categoria not in ["interesado", "no_interesado", "negociando"]:
            if "no" in categoria or "descart" in categoria:
                categoria = "no_interesado"
            elif "nego" in categoria:
                categoria = "negociando"
            else:
                categoria = "interesado"

        fecha_propuesta = datos_analizados.get("fecha_propuesta")
        oferta_economica = datos_analizados.get("oferta_economica")
        resumen = datos_analizados.get("resumen") or cuerpo[:200].replace("\n", " ")
        
        detalles_extra = []
        if fecha_propuesta:
            detalles_extra.append(f"Fecha: {fecha_propuesta}")
        if oferta_economica:
            detalles_extra.append(f"Oferta: {oferta_economica}")
        str_extra = f" [{', '.join(detalles_extra)}]" if detalles_extra else ""

        notas = f"Respuesta recibida ({respuesta.get('fecha')}){str_extra}: {resumen}"
        
        estados.transicionar(lead_asociado, categoria, notas=notas)

        sheets.registrar_mensaje_hilo(
            lead_id, nombre_sala, respuesta.get("fecha"),
            remitente="sala", remitente_nombre=_extraer_nombre_remitente(remitente),
            asunto=respuesta.get("asunto"), mensaje=cuerpo, mensaje_id=respuesta.get("id")
        )
        gmail_client.marcar_como_leido(respuesta.get("id"))

        ciudad_lead = lead_asociado.get("ciudad") or lead_asociado.get("region") or ""
        ciudad_str = f" ({ciudad_lead})" if ciudad_lead else ""

        if categoria in ["interesado", "negociando"]:
            msg_telegram = (
                f"🎉 *¡NUEVO INTERÉS / NEGOCIACIÓN DE BOLO!*\n\n"
                f"🏛️ *Recinto:* {nombre_sala}{ciudad_str}\n"
                f"📊 *Estado:* {categoria.upper()}\n"
            )
            if fecha_propuesta:
                msg_telegram += f"📅 *Fecha propuesta:* {fecha_propuesta}\n"
            if oferta_economica:
                msg_telegram += f"💰 *Oferta / Condiciones:* {oferta_economica}\n"
            msg_telegram += f"📝 *Resumen:* {resumen}\n\n"
            msg_telegram += f"💡 *El asistente creará un borrador de respuesta contextualizado.*\n\n"
            msg_telegram += metricas.formatear_pie_kpis_telegram()
        else:
            msg_telegram = (
                f"❌ *Respuesta de {nombre_sala}{ciudad_str}*\n"
                f"📊 *Estado:* NO INTERESADO / DESCARTADO\n"
                f"📝 *Resumen:* {resumen}"
            )

        telegram.enviar_notificacion_telegram(msg_telegram)
        clasificados += 1
            
    print(f"[lector_bandeja.py] Lectura finalizada. Respuestas clasificadas: {clasificados}")
    return clasificados

if __name__ == "__main__":
    procesar_bandeja_entrada()
