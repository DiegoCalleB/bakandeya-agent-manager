import os
import base64
import json
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes requeridos para leer, enviar y crear borradores
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose'
]

def es_modo_simulado():
    """
    Determina si se debe usar el modo simulado de email (si no existe credentials.json
    o si la variable de entorno EMAIL_MODE es 'simulado').
    """
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    return os.getenv("EMAIL_MODE") == "simulado" or not os.path.exists(credentials_path)

def obtener_servicio_gmail():
    """
    Autentica al usuario usando OAuth y devuelve el servicio de la API de Gmail.
    Reutiliza el archivo 'token.json' si ya existe para evitar abrir el navegador.
    """
    creds = None
    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"No se encontró el archivo de credenciales de cliente OAuth de Gmail en {credentials_path}. "
                    "Por favor descárgalo de Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Guardar credenciales para la próxima ejecución
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)

def enviar_email(destinatario, asunto, cuerpo_texto):
    """
    Envía un email plano usando el servicio de Gmail o lo guarda localmente si está en modo simulado.
    """
    if es_modo_simulado():
        print(f"[gmail_client.py] MODO SIMULADO: Redirigiendo envío de email a creación de borrador local...")
        return crear_borrador(destinatario, asunto, cuerpo_texto)
        
    try:
        service = obtener_servicio_gmail()
        mensaje = MIMEText(cuerpo_texto)
        mensaje['to'] = destinatario
        mensaje['subject'] = asunto
        
        # Codificar el mensaje en base64url
        raw_message = base64.urlsafe_b64encode(mensaje.as_bytes()).decode('utf-8')
        body = {'raw': raw_message}
        
        envio = service.users().messages().send(userId='me', body=body).execute()
        print(f"Mensaje enviado con éxito. ID: {envio['id']}")
        return envio
    except Exception as e:
        print(f"Error al enviar el email a {destinatario}: {e}")
        return None

def crear_borrador(destinatario, asunto, cuerpo_texto):
    """
    Crea un borrador (draft) en Gmail o lo guarda localmente en un archivo HTML en modo simulado.
    """
    if es_modo_simulado():
        print(f"[gmail_client.py] MODO SIMULADO: Guardando borrador local para {destinatario}...")
        try:
            ruta_drafts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "drafts")
            os.makedirs(ruta_drafts, exist_ok=True)
            
            # Limpiar nombre de archivo
            nombre_limpio = "".join(c for c in destinatario if c.isalnum() or c in "@.-_").rstrip()
            ruta_archivo = os.path.join(ruta_drafts, f"borrador_{nombre_limpio}.html")
            
            cuerpo_html = cuerpo_texto.replace("\n", "<br>")
            contenido_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Borrador para {destinatario}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f4f5f7;
            padding: 20px;
            color: #333;
        }}
        .email-container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #fff;
            border: 1px solid #e1e4e8;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            overflow: hidden;
        }}
        .email-header {{
            background-color: #f6f8fa;
            padding: 15px 20px;
            border-bottom: 1px solid #e1e4e8;
        }}
        .header-line {{
            margin-bottom: 8px;
            font-size: 14px;
        }}
        .header-line strong {{
            color: #586069;
        }}
        .email-body {{
            padding: 25px 20px;
            font-size: 15px;
            line-height: 1.6;
            color: #24292e;
        }}
        .sim-badge {{
            display: inline-block;
            background-color: #dbedff;
            color: #0366d6;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 10px;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="email-header">
            <span class="sim-badge">Borrador Simulado Local</span>
            <div class="header-line"><strong>Para:</strong> {destinatario}</div>
            <div class="header-line"><strong>Asunto:</strong> {asunto}</div>
        </div>
        <div class="email-body">{cuerpo_html}</div>
    </div>
</body>
</html>
"""
            with open(ruta_archivo, "w", encoding="utf-8") as f:
                f.write(contenido_html)
                
            print(f"[gmail_client.py] Borrador guardado localmente en: {ruta_archivo}")
            return {"id": f"sim_draft_{nombre_limpio}", "local_path": ruta_archivo}
        except Exception as e:
            print(f"Error al guardar borrador simulado para {destinatario}: {e}")
            return None
            
    try:
        service = obtener_servicio_gmail()
        mensaje = MIMEText(cuerpo_texto)
        mensaje['to'] = destinatario
        mensaje['subject'] = asunto
        
        # Codificar el mensaje en base64url
        raw_message = base64.urlsafe_b64encode(mensaje.as_bytes()).decode('utf-8')
        body = {'message': {'raw': raw_message}}
        
        borrador = service.users().drafts().create(userId='me', body=body).execute()
        print(f"Borrador creado con éxito. ID: {borrador['id']}")
        return borrador
    except Exception as e:
        print(f"Error al crear el borrador para {destinatario}: {e}")
        return None

def leer_respuestas(query="is:unread"):
    """
    Busca emails entrantes y sin leer en Gmail o lee respuestas simuladas locales.
    """
    if es_modo_simulado():
        print("[gmail_client.py] MODO SIMULADO: Buscando respuestas en archivo local...")
        ruta_drafts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "drafts")
        ruta_respuestas = os.path.join(ruta_drafts, "respuestas_simuladas.json")
        
        if not os.path.exists(ruta_respuestas):
            plantilla = [
                {
                    "id": "reply_sim_001",
                    "remitente": "comercial@aliatar.es",
                    "asunto": "Re: Propuesta de concierto: Bakandeya en Sala Aliatar",
                    "fecha": "Fri, 10 Jul 2026 12:00:00 +0200",
                    "cuerpo": "Hola. Nos parece muy interesante vuestra propuesta. ¿Qué caché manejáis para salas y qué disponibilidad tenéis en septiembre?"
                }
            ]
            try:
                os.makedirs(ruta_drafts, exist_ok=True)
                with open(ruta_respuestas, "w", encoding="utf-8") as f:
                    json.dump(plantilla, f, indent=4, ensure_ascii=False)
                print(f"[gmail_client.py] Se ha creado una plantilla de respuestas simuladas en: {ruta_respuestas}")
            except Exception as e:
                print(f"Error al crear plantilla de respuestas: {e}")
            return []
            
        try:
            with open(ruta_respuestas, "r", encoding="utf-8") as f:
                respuestas = json.load(f)
            print(f"[gmail_client.py] Cargadas {len(respuestas)} respuestas simuladas.")
            return respuestas
        except Exception as e:
            print(f"Error al leer respuestas simuladas de {ruta_respuestas}: {e}")
            return []
            
    try:
        service = obtener_servicio_gmail()
        resultado = service.users().messages().list(userId='me', q=query).execute()
        mensajes = resultado.get('messages', [])
        
        respuestas = []
        for msg in mensajes:
            # Obtener detalle del mensaje
            m_det = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            headers = m_det.get('payload', {}).get('headers', [])
            
            remitente = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Desconocido")
            asunto = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "Sin Asunto")
            fecha = next((h['value'] for h in headers if h['name'].lower() == 'date'), "Sin Fecha")
            
            # Obtener cuerpo del mensaje
            parts = m_det.get('payload', {}).get('parts', [])
            cuerpo = ""
            if not parts:
                cuerpo_data = m_det.get('payload', {}).get('body', {}).get('data', '')
                if cuerpo_data:
                    cuerpo = base64.urlsafe_b64decode(cuerpo_data).decode('utf-8', errors='ignore')
            else:
                for part in parts:
                    if part.get('mimeType') == 'text/plain':
                        cuerpo_data = part.get('body', {}).get('data', '')
                        if cuerpo_data:
                            cuerpo = base64.urlsafe_b64decode(cuerpo_data).decode('utf-8', errors='ignore')
                            break
                            
            respuestas.append({
                "id": msg['id'],
                "remitente": remitente,
                "asunto": asunto,
                "fecha": fecha,
                "cuerpo": cuerpo
            })
            
        return respuestas
    except Exception as e:
        print(f"Error al leer respuestas de Gmail: {e}")
        return []
