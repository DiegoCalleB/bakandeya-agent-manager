import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

def obtener_cliente_claude():
    """
    Inicializa el cliente de la SDK de Anthropic usando la API Key de entorno.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("La variable de entorno ANTHROPIC_API_KEY no está configurada")
    return Anthropic(api_key=api_key)

def generar_texto(prompt, model="claude-3-5-sonnet-20241022", system_prompt=None, max_tokens=2000):
    """
    Envía un mensaje a la API de Claude y devuelve la respuesta textual.
    Permite configurar un system prompt y el modelo a utilizar.
    """
    try:
        client = obtener_cliente_claude()
        
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        if system_prompt:
            kwargs["system"] = system_prompt
            
        respuesta = client.messages.create(**kwargs)
        return respuesta.content[0].text
    except Exception as e:
        print(f"Error al llamar a la API de Claude: {e}")
        return None
