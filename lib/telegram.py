import os
import requests
from dotenv import load_dotenv

load_dotenv()

def enviar_notificacion_telegram(mensaje):
    """
    Envía un mensaje de texto con formato Markdown al chat de Telegram configurado.
    Si faltan credenciales, lo imprime por pantalla para no bloquear el desarrollo.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        try:
            print(f"[Telegram Mock] {mensaje}")
        except UnicodeEncodeError:
            # Fallback seguro para consolas de Windows que no soportan emojis UTF-8 por defecto
            mensaje_seguro = mensaje.encode('ascii', errors='replace').decode('ascii')
            print(f"[Telegram Mock] {mensaje_seguro}")
        return False
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Notificación de Telegram enviada correctamente.")
            return True
        else:
            print(f"Error al enviar Telegram (Status {response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"Excepción al enviar notificación de Telegram: {e}")
        return False
