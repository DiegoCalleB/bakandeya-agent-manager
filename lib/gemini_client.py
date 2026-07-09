import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Obtener la API key de las variables de entorno
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

import time

def generar_texto_gemini(prompt, model_name="gemini-2.5-flash", system_instruction=None, temperature=0.7, max_retries=3, delay_segundos=30):
    """
    Realiza una consulta a la API de Gemini de Google AI Studio y devuelve el texto de respuesta.
    Soporta instrucciones del sistema (system prompts) y temperatura.
    Implementa reintentos automáticos para errores de cuota (429) con backoff exponencial.
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
            
            config = genai.types.GenerationConfig(
                temperature=temperature
            )
            
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
