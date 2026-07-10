import sys
import os
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.sheets as sheets
import lib.gmail_client as gmail_client
import lib.gemini_client as gemini_client
import lib.telegram as telegram

def procesar_bandeja_entrada():
    """
    Busca respuestas sin leer en Gmail, identifica el lead que estaba esperando
    respuesta, las clasifica con Claude y actualiza la hoja de cálculo.
    """
    print("[lector_bandeja.py] Iniciando lectura de respuestas...")
    respuestas = gmail_client.leer_respuestas()
    leads_esperando = sheets.obtener_leads(estado="esperando_respuesta")
    
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
            f"Clasifica la siguiente respuesta de una sala de conciertos a nuestra propuesta de contratación:\n\n"
            f"Asunto: {respuesta.get('asunto')}\n"
            f"Cuerpo: {cuerpo}\n\n"
            "Elige exclusivamente una de estas tres categorías: 'interesado', 'no_interesado', 'negociando'."
        )
        
        system_prompt = (
            "Eres un clasificador de emails de respuesta para Bakandeya. "
            "Debes responder estrictamente con una de las tres palabras: 'interesado', 'no_interesado' o 'negociando'."
        )
        
        # Gemini 2.5 Flash es rápido y eficiente para clasificar
        clasificacion = gemini_client.generar_texto_gemini(
            prompt, 
            model_name="gemini-2.5-flash", 
            system_instruction=system_prompt,
            temperature=0.1
        )
        
        if clasificacion:
            categoria = clasificacion.strip().lower()
            # Validar que la salida sea uno de los estados correctos
            if categoria not in ["interesado", "no_interesado", "negociando"]:
                # Por si acaso la IA devuelve texto adicional, buscar coincidencia
                if "no" in categoria:
                    categoria = "no_interesado"
                elif "nego" in categoria:
                    categoria = "negociando"
                else:
                    categoria = "interesado"
            
            # Limitar notas para evitar saturar la celda
            extracto_respuesta = cuerpo[:200].replace("\n", " ")
            notas = f"Respuesta recibida ({respuesta.get('fecha')}): {extracto_respuesta}..."
            
            sheets.actualizar_estado_lead(lead_id, categoria, notas=notas)
            telegram.enviar_notificacion_telegram(
                f"🔔 Respuesta de *{nombre_sala}* clasificada como *{categoria.upper()}*\n"
                f"📝 Resumen: {extracto_respuesta}..."
            )
            clasificados += 1
            
    print(f"[lector_bandeja.py] Lectura finalizada. Respuestas clasificadas: {clasificados}")
    return clasificados

if __name__ == "__main__":
    procesar_bandeja_entrada()
