import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

def enviar_webhook_finalizacion(agente, region, creados=0, leads_enriquecidos=None):
    """
    Envía una notificación HTTP POST con formato JSON al webhook configurado
    en la variable de entorno CHATBOT_WEBHOOK_URL.
    """
    webhook_url = os.getenv("CHATBOT_WEBHOOK_URL")
    if not webhook_url:
        print("[webhooks.py] CHATBOT_WEBHOOK_URL no configurada, omitiendo notificación webhook.")
        return False

    payload = {
        "status": "success",
        "agent": agente,
        "region": region,
        "leads_descubiertos": creados,
        "leads_enriquecidos": leads_enriquecidos or []
    }

    try:
        print(f"[webhooks.py] Enviando webhook a: {webhook_url}...")
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code in [200, 201, 202, 204]:
            print(f"[webhooks.py] Webhook enviado con éxito (Status {response.status_code}).")
            return True
        else:
            print(f"[webhooks.py] Error al enviar Webhook (Status {response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"[webhooks.py] Excepción al enviar Webhook: {e}")
        return False
