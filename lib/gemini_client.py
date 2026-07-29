import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Obtener la API key de las variables de entorno.
# transport="rest": el SDK usa gRPC por defecto, que tiene su propio motor TLS y no pasa por
# el módulo `ssl` de Python — por eso el bootstrap de `truststore` (ver lib/__init__.py) no lo
# cubre y falla tras el proxy de inspección corporativo. Con REST, las llamadas van por
# `requests`/urllib3, que sí usan `ssl` y por tanto sí quedan arregladas por truststore.
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key, transport="rest")

import time

def generar_texto_gemini(prompt, model_name="gemini-2.5-flash", system_instruction=None, temperature=0.7, forzar_json=False, max_retries=3, delay_segundos=30):
    """
    Realiza una consulta a la API de Gemini de Google AI Studio y devuelve el texto de respuesta.
    Soporta instrucciones del sistema (system prompts) y temperatura.
    Implementa reintentos automáticos para errores de cuota (429) con backoff exponencial.

    Si `forzar_json=True` se activa el "JSON mode" de Gemini (response_mime_type =
    application/json): el modelo queda OBLIGADO a devolver un JSON sintácticamente válido,
    así que quien llame puede hacer `json.loads(...)` directo sin limpiar bloques ```json.
    Es la forma robusta de pedir salida estructurada y evita una clase entera de bugs de parseo.
    """
    if not os.getenv("GEMINI_API_KEY"):
        print("[gemini_client.py] ERROR: La variable de entorno GEMINI_API_KEY no está configurada.")
        return None

    intentos = 0
    delay = delay_segundos

    while intentos <= max_retries:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_instruction
            )

            config_kwargs = {"temperature": temperature}
            if forzar_json:
                config_kwargs["response_mime_type"] = "application/json"
            config = genai.types.GenerationConfig(**config_kwargs)
            
            respuesta = model.generate_content(
                prompt,
                generation_config=config
            )
            
            return respuesta.text
        except Exception as e:
            error_msg = str(e)
            # Detectar error 429 (ResourceExhausted / QuotaExceeded)
            if "429" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                intentos += 1
                if intentos > max_retries:
                    print(f"[gemini_client.py] ERROR: Se superó el límite de reintentos ({max_retries}) debido a límites de cuota (429).")
                    return None
                print(f"[gemini_client.py] Límite de cuota alcanzado (429). Esperando {delay} segundos para reintentar... (Intento {intentos}/{max_retries})")
                time.sleep(delay)
                delay *= 2  # Backoff exponencial
            else:
                print(f"Error al llamar a la API de Gemini: {e}")
                return None
    return None
