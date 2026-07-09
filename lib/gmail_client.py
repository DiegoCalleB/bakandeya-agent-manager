import os
import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes requeridos para leer y enviar emails
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly'
]

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
    Envía un email plano usando el servicio de Gmail.
    """
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

def leer_respuestas(query="is:unread"):
    """
    Busca emails entrantes y sin leer. Devuelve una lista de diccionarios
    con el remitente, asunto, fecha y cuerpo del mensaje.
    """
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
