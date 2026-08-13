import os
import base64
import json
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
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

# Banda original single-tenant: sigue usando el 'token.json' de siempre en la raíz del repo,
# para no requerir migración de lo que ya está funcionando en producción.
_BAND_ID_LEGACY = "band-bakandeya"

# Multi-tenant (decisión explícita de Diego, 2026-08-10): CADA BANDA ENVÍA DESDE SU PROPIO EMAIL
# OFICIAL — su propia cuenta de Gmail conectada por OAuth. NUNCA un buzón compartido entre
# bandas, y NUNCA el email personal de quien esté logueado en el CRM. El token de cada banda
# (salvo band-bakandeya, que usa el 'token.json' de siempre) vive en tokens/{band_id}.json,
# generado una vez conectando esa cuenta de Gmail localmente (login interactivo, igual que se
# hizo para Bakandeya) y desplegado como secreto en GitHub Actions.
TOKENS_DIR = os.getenv("GMAIL_TOKENS_DIR", "tokens")


def _ruta_token(band_id=None):
    """
    Ruta del token OAuth a usar para una banda. band_id=None o band-bakandeya -> el token.json
    de siempre (retrocompatibilidad). Cualquier otra banda -> tokens/{band_id}.json, o la ruta
    de la variable de entorno GMAIL_TOKEN_PATH_<BAND_ID> si se define (para inyectarla como
    secreto de GitHub Actions sin depender de un fichero ya presente en el repo).
    """
    if not band_id or band_id == _BAND_ID_LEGACY:
        return os.getenv("GMAIL_TOKEN_PATH", "token.json")
    env_key = f"GMAIL_TOKEN_PATH_{band_id.upper().replace('-', '_')}"
    override = os.getenv(env_key)
    if override:
        return override
    return os.path.join(TOKENS_DIR, f"{band_id}.json")


def es_modo_simulado():
    """
    Determina si se debe usar el modo simulado de email (si no existe credentials.json
    o si la variable de entorno EMAIL_MODE es 'simulado').
    """
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    return os.getenv("EMAIL_MODE") == "simulado" or not os.path.exists(credentials_path)

def obtener_servicio_gmail(band_id=None):
    """
    Autentica con OAuth y devuelve el servicio de la API de Gmail DE LA CUENTA CONECTADA PARA
    ESA BANDA (ver _ruta_token) — nunca una cuenta compartida entre bandas. Reutiliza el token
    guardado si ya existe para evitar abrir el navegador.

    Para band-bakandeya (o band_id=None) se mantiene el flujo interactivo de siempre si el token
    no existe o no se puede refrescar. Para el resto de bandas NO se abre un login interactivo
    aquí (reventaría en un cron/GitHub Actions sin navegador): si su token no existe o ha dejado
    de ser válido, se falla con un error claro — hay que conectar esa cuenta de Gmail a mano una
    vez, en local, y desplegar el token.json resultante como secreto para esa banda.
    """
    es_legacy = not band_id or band_id == _BAND_ID_LEGACY
    creds = None
    token_path = _ruta_token(band_id)

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        refrescado = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refrescado = True
            except Exception as e:
                # El refresh token puede quedar revocado/caducado (p. ej. apps en estado
                # "Testing" en Google Cloud Console expiran el refresh token a los 7 días).
                print(f"[gmail_client.py] No se pudo refrescar el token de '{band_id or _BAND_ID_LEGACY}' ({e}).")

        if not refrescado:
            if not es_legacy:
                raise FileNotFoundError(
                    f"La banda '{band_id}' todavía no tiene su propio email de Gmail conectado "
                    f"(no se encontró un token válido en {token_path}). Hay que conectarlo una vez "
                    "en local con el flujo OAuth de esta banda antes de que los agentes puedan "
                    "enviar en su nombre — no se usa ninguna otra cuenta como sustituta."
                )
            credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"No se encontró el archivo de credenciales de cliente OAuth de Gmail en {credentials_path}. "
                    "Por favor descárgalo de Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Guardar credenciales para la próxima ejecución
        os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def obtener_email_conectado(band_id=None):
    """
    Devuelve la dirección de la cuenta de Gmail realmente conectada para esa banda (llamando a
    users.getProfile), o None si no se pudo obtener. Lo usa enviador.py como comprobación de
    seguridad ANTES de enviar: si no coincide con el email oficial de la banda en su EPK, es
    señal de que se ha conectado la cuenta equivocada — mejor no enviar nada que enviar desde
    la mailbox de otra banda.
    """
    if es_modo_simulado():
        return None
    try:
        service = obtener_servicio_gmail(band_id)
        perfil = service.users().getProfile(userId='me').execute()
        return perfil.get('emailAddress')
    except Exception as e:
        print(f"[gmail_client.py] No se pudo verificar el email conectado para '{band_id or _BAND_ID_LEGACY}': {e}")
        return None

def enviar_email(destinatario, asunto, cuerpo_texto, ruta_adjunto=None, epk=None, band_id=None):
    """
    Envía un email (HTML con fallback en texto plano, firma con iconos, adjunto opcional)
    directamente vía la API de Gmail, sin pasar por un borrador. Útil para probar el
    renderizado real sin depender de que Gmail reconstruya el mensaje al reenviarlo desde
    la interfaz tras crear un borrador por API.

    `epk` (opcional): dict de EPK ya cargado por el llamador (p. ej. lib.bandas.cargar_epk_banda)
    para construir la firma con los enlaces de ESA banda. Si se omite, se usa el EPK estático de
    Bakandeya por compatibilidad.
    `band_id` (opcional, multi-tenant): determina de qué cuenta de Gmail se envía — ver
    obtener_servicio_gmail. Si se omite, se usa la cuenta de band-bakandeya (retrocompatibilidad).
    """
    if es_modo_simulado():
        print(f"[gmail_client.py] MODO SIMULADO: Redirigiendo envío de email a creación de borrador local...")
        return crear_borrador(destinatario, asunto, cuerpo_texto, ruta_adjunto=ruta_adjunto, epk=epk, band_id=band_id)

    try:
        service = obtener_servicio_gmail(band_id)
        mensaje = _construir_mensaje(destinatario, asunto, cuerpo_texto, ruta_adjunto=ruta_adjunto, epk=epk)

        # Codificar el mensaje en base64url
        raw_message = base64.urlsafe_b64encode(mensaje.as_bytes()).decode('utf-8')
        body = {'raw': raw_message}
        
        envio = service.users().messages().send(userId='me', body=body).execute()
        print(f"Mensaje enviado con éxito. ID: {envio['id']}")
        return envio
    except Exception as e:
        print(f"Error al enviar el email a {destinatario}: {e}")
        return None

def _cargar_epk_para_firma(band_id=None):
    """
    Obtiene el EPK desde Supabase (vía lib.bandas) para construir la firma con los enlaces y datos de la banda.
    """
    try:
        import lib.bandas as bandas
        return bandas.cargar_epk_banda(band_id or _BAND_ID_LEGACY)
    except Exception as e:
        print(f"[gmail_client.py] Error al cargar EPK para firma desde Supabase: {e}")
        return {}


def _adjuntar_archivo(mensaje, ruta_adjunto):
    tipo_mime, _ = mimetypes.guess_type(ruta_adjunto)
    tipo_mime = tipo_mime or "application/octet-stream"
    with open(ruta_adjunto, "rb") as f:
        adjunto = MIMEApplication(f.read(), _subtype=tipo_mime.split("/")[-1])
    adjunto.add_header("Content-Disposition", "attachment", filename=os.path.basename(ruta_adjunto))
    mensaje.attach(adjunto)


def _construir_mensaje(destinatario, asunto, cuerpo_texto, ruta_adjunto=None, epk=None):
    """
    Construye el mensaje MIME en HTML (con fallback en texto plano) + firma con iconos de
    redes sociales (imagen alojada en GitHub Pages, ver lib/email_html.py — las imágenes
    embebidas por Content-ID no sobreviven al reenvío de un borrador desde la interfaz de
    Gmail) + adjunto opcional (p. ej. el PDF del dossier real, en vez de depender de un link
    externo con permisos de Drive que puede no ser público). Estructura: multipart/mixed
    [ multipart/alternative (texto plano + HTML), adjunto ].

    `epk` (opcional, multi-tenant): dict de EPK de la banda concreta (ver lib.bandas), para que
    la firma enlace a SUS redes sociales. Si se omite, se cae al EPK estático de Bakandeya —
    mantiene el comportamiento antiguo para quien llame a esta función sin pasar banda.
    """
    from lib.email_html import texto_a_html, construir_firma_html

    epk = epk if epk is not None else _cargar_epk_para_firma()
    cuerpo_html = texto_a_html(cuerpo_texto) + construir_firma_html(epk)

    alternativa = MIMEMultipart("alternative")
    alternativa.attach(MIMEText(cuerpo_texto, "plain"))
    alternativa.attach(MIMEText(cuerpo_html, "html"))

    if ruta_adjunto and os.path.exists(ruta_adjunto):
        mensaje = MIMEMultipart("mixed")
        mensaje.attach(alternativa)
        _adjuntar_archivo(mensaje, ruta_adjunto)
    else:
        mensaje = alternativa

    mensaje['to'] = destinatario
    mensaje['subject'] = asunto
    return mensaje


def crear_borrador(destinatario, asunto, cuerpo_texto, thread_id=None, in_reply_to=None, ruta_adjunto=None, epk=None, band_id=None):
    """
    Crea un borrador (draft) en Gmail o lo guarda localmente en un archivo HTML en modo simulado.
    `ruta_adjunto` (opcional): ruta a un archivo local a adjuntar (p. ej. el dossier en PDF).
    `epk` (opcional, multi-tenant): ver _construir_mensaje — firma con las redes de esa banda.

    IMPORTANTE (arquitectura multi-tenant, decisión explícita de Diego, 2026-08-10): el borrador
    se crea en LA CUENTA DE GMAIL PROPIA DE ESA BANDA (su email oficial, conectado por OAuth) —
    nunca en un buzón compartido entre bandas, ni en el email personal de quien esté logueado en
    el CRM. `band_id` selecciona qué cuenta usar (ver obtener_servicio_gmail/_ruta_token); si se
    omite, se usa la cuenta de band-bakandeya (retrocompatibilidad con el flujo original).
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
            {f'<div class="header-line"><strong>Thread ID:</strong> {thread_id}</div>' if thread_id else ''}
            {f'<div class="header-line"><strong>In-Reply-To:</strong> {in_reply_to}</div>' if in_reply_to else ''}
            {f'<div class="header-line"><strong>Adjunto:</strong> {os.path.basename(ruta_adjunto)}</div>' if ruta_adjunto else ''}
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
        service = obtener_servicio_gmail(band_id)
        mensaje = _construir_mensaje(destinatario, asunto, cuerpo_texto, ruta_adjunto=ruta_adjunto, epk=epk)
        if in_reply_to:
            mensaje['In-Reply-To'] = in_reply_to
            mensaje['References'] = in_reply_to

        # Codificar el mensaje en base64url
        raw_message = base64.urlsafe_b64encode(mensaje.as_bytes()).decode('utf-8')
        message_body = {'raw': raw_message}
        if thread_id:
            message_body['threadId'] = thread_id
            
        body = {'message': message_body}
        
        borrador = service.users().drafts().create(userId='me', body=body).execute()
        print(f"Borrador creado con éxito. ID: {borrador['id']}")
        return borrador
    except Exception as e:
        print(f"Error al crear el borrador para {destinatario}: {e}")
        return None

def marcar_como_leido(mensaje_id, band_id=None):
    """
    Quita la etiqueta UNREAD de un mensaje ya procesado por lector_bandeja.py, EN LA BANDEJA DE
    ESA BANDA (multi-tenant: cada banda tiene su propia bandeja, ver leer_respuestas). Sin esto,
    `leer_respuestas(query="is:unread")` volvería a devolver el mismo email en cada ejecución
    del cron (cada 2h) hasta que alguien lo abriera manualmente en Gmail.
    """
    if es_modo_simulado():
        return True
    try:
        service = obtener_servicio_gmail(band_id)
        service.users().messages().modify(userId='me', id=mensaje_id, body={'removeLabelIds': ['UNREAD']}).execute()
        return True
    except Exception as e:
        print(f"Error al marcar como leído el mensaje {mensaje_id}: {e}")
        return False


def leer_respuestas(query="is:unread", band_id=None):
    """
    Busca emails entrantes y sin leer en la bandeja de Gmail DE ESA BANDA (multi-tenant: cada
    banda tiene su propio email conectado, así que también su propia bandeja de entrada — no
    existe ya una única bandeja compartida), o lee respuestas simuladas locales en modo
    simulado. `band_id=None` usa la bandeja de band-bakandeya (retrocompatibilidad).
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
        service = obtener_servicio_gmail(band_id)
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
                "threadId": m_det.get("threadId"),
                "remitente": remitente,
                "asunto": asunto,
                "fecha": fecha,
                "cuerpo": cuerpo
            })
            
        return respuestas
    except Exception as e:
        print(f"Error al leer respuestas de Gmail: {e}")
        return []
