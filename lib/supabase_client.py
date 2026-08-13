"""
Cliente unificado de Supabase para Bakandeya Agent Manager.

Sustituye completamente la dependencia de Google Sheets para almacenamiento de leads,
mensajes de correo, bandas registradas y archivos multimedia en Supabase Storage (bucket 'band-media').
"""

import os
import json
import threading
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

BAND_ID_DEFAULT = "band-bakandeya"
BUCKET_MEDIA_DEFAULT = "band-media"

_supabase_client = None
_client_lock = threading.Lock()


def get_supabase_client() -> Client:
    """
    Devuelve la instancia singleton del cliente de Supabase.
    Utiliza SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY (o SUPABASE_ANON_KEY como fallback).
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    with _client_lock:
        if _supabase_client is None:
            url = os.getenv("SUPABASE_URL", "").strip('"').strip("'")
            key = (
                os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                or os.getenv("SUPABASE_ANON_KEY")
                or ""
            ).strip('"').strip("'")

            if not url or not key:
                raise ValueError("SUPABASE_URL y SUPABASE_ANON_KEY/SERVICE_ROLE_KEY deben estar configuradas en .env")

            _supabase_client = create_client(url, key)

    return _supabase_client


def _determinar_tabla(nombre_hoja: str) -> str:
    """Mapea los nombres históricos de las hojas de Google Sheets a las tablas de Supabase."""
    nombre = (nombre_hoja or "leads").strip().lower()
    if nombre in ("leads", "hoja_leads"):
        return "leads"
    elif nombre in ("hilos_emails", "hilos", "messages", "mensajes"):
        return "messages"
    elif nombre in ("registro_bandas", "registered_bands", "bandas"):
        return "registered_bands"
    elif nombre in ("medios_scout", "medios"):
        return "medios_scout"
    elif nombre in ("dossier_epk", "epk"):
        return "dossier_epk"
    elif nombre in ("config_autonomia", "autonomia"):
        return "config_autonomia"
    return nombre


def obtener_leads(estado: str = None, nombre_hoja: str = "leads", band_id: str = None) -> list[dict]:
    """
    Lee todas las filas de la tabla correspondiente en Supabase.
    Si se especifica `estado` o `band_id`, filtra las filas correspondientes.
    """
    try:
        supabase = get_supabase_client()
        tabla = _determinar_tabla(nombre_hoja)

        query = supabase.table(tabla).select("*")

        if estado:
            query = query.eq("estado", estado)
        if band_id:
            query = query.eq("band_id", band_id)

        res = query.execute()
        return res.data or []
    except Exception as e:
        # Fallback para 'medios_scout' si no existe la tabla dedicada: filtrar en 'leads' por tipo='medio'
        if nombre_hoja == "medios_scout":
            try:
                supabase = get_supabase_client()
                query = supabase.table("leads").select("*").eq("tipo", "medio")
                if estado:
                    query = query.eq("estado", estado)
                if band_id:
                    query = query.eq("band_id", band_id)
                res = query.execute()
                return res.data or []
            except Exception as ex2:
                print(f"[supabase_client.py] Error al obtener medios en fallback: {ex2}")
                return []

        print(f"[supabase_client.py] Error al obtener leads de Supabase ({nombre_hoja}): {e}")
        return []


def actualizar_datos_lead(lead_id: str, datos_dict: dict, nombre_hoja: str = "leads") -> bool:
    """
    Actualiza campos específicos de un lead en Supabase según su `id`.
    """
    if not lead_id or not datos_dict:
        return False

    try:
        supabase = get_supabase_client()
        tabla = _determinar_tabla(nombre_hoja)

        payload = dict(datos_dict)
        payload["updated_at"] = datetime.utcnow().isoformat() + "Z"

        res = supabase.table(tabla).update(payload).eq("id", str(lead_id)).execute()
        if res.data:
            return True

        if tabla == "medios_scout":
            res_fb = supabase.table("leads").update(payload).eq("id", str(lead_id)).execute()
            return bool(res_fb.data)

        return True
    except Exception as e:
        print(f"[supabase_client.py] Error al actualizar datos del lead {lead_id}: {e}")
        return False


def actualizar_estado_lead(lead_id: str, nuevo_estado: str, pitch: str = None, notas: str = None, nombre_hoja: str = "leads") -> bool:
    """
    Actualiza el estado de un lead y opcionalmente su pitch_generado y notas.
    """
    datos = {"estado": nuevo_estado}
    if pitch is not None:
        datos["pitch_generado"] = pitch
    if notas is not None:
        datos["notas"] = notas

    return actualizar_datos_lead(lead_id, datos, nombre_hoja=nombre_hoja)


def crear_leads(lista_datos_dict: list[dict], nombre_hoja: str = "leads") -> bool:
    """
    Inserta múltiples filas en la tabla correspondiente de Supabase en una sola operación.
    """
    if not lista_datos_dict:
        return True

    try:
        supabase = get_supabase_client()
        tabla = _determinar_tabla(nombre_hoja)

        filas_limpias = []
        for datos in lista_datos_dict:
            item = dict(datos)
            if "band_id" not in item or not item["band_id"]:
                item["band_id"] = BAND_ID_DEFAULT
            if "created_at" not in item:
                item["created_at"] = datetime.utcnow().isoformat() + "Z"
            if "updated_at" not in item:
                item["updated_at"] = datetime.utcnow().isoformat() + "Z"
            filas_limpias.append(item)

        res = supabase.table(tabla).insert(filas_limpias).execute()
        print(f"[supabase_client.py] Creados {len(res.data or [])} registros con éxito en '{tabla}'.")
        return True
    except Exception as e:
        if nombre_hoja == "medios_scout":
            try:
                supabase = get_supabase_client()
                for d in lista_datos_dict:
                    d["tipo"] = "medio"
                    if "band_id" not in d or not d["band_id"]:
                        d["band_id"] = BAND_ID_DEFAULT
                res_fb = supabase.table("leads").insert(lista_datos_dict).execute()
                print(f"[supabase_client.py] Creados {len(res_fb.data or [])} medios en la tabla 'leads'.")
                return True
            except Exception as ex2:
                print(f"[supabase_client.py] Error al crear medios en fallback: {ex2}")
                return False

        print(f"[supabase_client.py] Error al crear leads en Supabase: {e}")
        return False


def registrar_mensaje_hilo(
    lead_id: str,
    nombre_sala: str,
    fecha: str,
    remitente: str,
    remitente_nombre: str,
    asunto: str,
    mensaje: str,
    mensaje_id: str = None,
) -> bool:
    """
    Registra un mensaje de conversación en Supabase (tabla `messages` e `historial_contacto` del lead).
    """
    try:
        supabase = get_supabase_client()

        fila_id = mensaje_id or f"em-{lead_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 1. Verificar si ya se registró
        check = supabase.table("messages").select("id").eq("id", fila_id).execute()
        if check.data:
            return True

        # Formatear el contenido completo con asunto y remitente
        texto_completo = f"[{remitente_nombre or remitente}] Asunto: {asunto or ''}\n\n{mensaje or ''}"

        registro = {
            "id": fila_id,
            "band_id": BAND_ID_DEFAULT,
            "remitente": remitente or "banda",
            "mensaje": texto_completo,
            "fecha": fecha or datetime.utcnow().isoformat() + "Z",
            "leido": True if remitente == "banda" else False,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

        supabase.table("messages").insert(registro).execute()

        # 2. También registrar en el lead (historial_contacto) si existe el lead
        try:
            lead_res = supabase.table("leads").select("historial_contacto").eq("id", str(lead_id)).execute()
            if lead_res.data:
                historial_actual = lead_res.data[0].get("historial_contacto") or []
                if isinstance(historial_actual, str):
                    try:
                        historial_actual = json.loads(historial_actual)
                    except Exception:
                        historial_actual = [historial_actual]
                if not isinstance(historial_actual, list):
                    historial_actual = []

                nuevo_evento = {
                    "id": fila_id,
                    "fecha": fecha or datetime.utcnow().isoformat() + "Z",
                    "remitente": remitente,
                    "remitente_nombre": remitente_nombre,
                    "asunto": asunto,
                    "mensaje": mensaje,
                }
                historial_actual.append(nuevo_evento)
                supabase.table("leads").update({
                    "historial_contacto": historial_actual,
                    "fecha_ultima_respuesta": fecha or datetime.utcnow().strftime("%Y-%m-%d")
                }).eq("id", str(lead_id)).execute()
        except Exception as ex_lead:
            print(f"[supabase_client.py] Aviso actualizando historial_contacto en lead {lead_id}: {ex_lead}")

        return True
    except Exception as e:
        print(f"[supabase_client.py] Error al registrar mensaje de hilo para lead {lead_id}: {e}")
        return False


def obtener_bandas_activas() -> list[dict]:
    """
    Devuelve las bandas registradas activas desde la tabla `registered_bands`.
    Si la tabla no tiene datos, devuelve por defecto 'band-bakandeya'.
    """
    try:
        supabase = get_supabase_client()
        res = supabase.table("registered_bands").select("*").execute()
        filas = res.data or []

        activas = [
            f for f in filas
            if str(f.get("band_id") or "").strip()
            and str(f.get("estado_cuenta") or "activo").strip().lower() in ("activo", "active", "")
        ]
        if not activas:
            return [{"band_id": BAND_ID_DEFAULT, "nombre_banda": "Bakandeya", "estado_cuenta": "activo"}]
        return activas
    except Exception as e:
        print(f"[supabase_client.py] Error al obtener bandas activas: {e}")
        return [{"band_id": BAND_ID_DEFAULT, "nombre_banda": "Bakandeya", "estado_cuenta": "activo"}]


def obtener_epk_banda(band_id: str) -> dict:
    """Devuelve el EPK de la banda desde Supabase (dossier_epk o registered_bands)."""
    try:
        supabase = get_supabase_client()
        try:
            res = supabase.table("dossier_epk").select("*").eq("band_id", band_id).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass

        res_rb = supabase.table("registered_bands").select("*").eq("band_id", band_id).execute()
        if res_rb.data:
            row = res_rb.data[0]
            return {
                "band_id": band_id,
                "nombre_banda": row.get("nombre_banda") or "Bakandeya",
                "contacto_nombre": row.get("contacto_nombre") or "",
                "contacto_email": row.get("email") or "",
                "contacto_telefono": row.get("telefono") or "",
                "instagram_url": row.get("instagram") or "",
                "youtube_url": row.get("spotify_youtube") or "",
            }

        return {}
    except Exception as e:
        print(f"[supabase_client.py] Error al obtener EPK de la banda {band_id}: {e}")
        return {}


def obtener_autonomia_banda(band_id: str) -> dict:
    """Devuelve la configuración de autonomía de la banda desde Supabase."""
    try:
        supabase = get_supabase_client()
        try:
            res = supabase.table("config_autonomia").select("*").eq("band_id", band_id).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass

        return {
            "band_id": band_id,
            "modo_envio": "draft_only",
            "profundidad_negociacion": "filter_conditions",
            "cache_minimo": 300,
            "cache_objetivo": 800,
            "auto_rechazar_bajo_minimo": False,
            "notificar_propuestas": True,
            "requiere_firma_humana": True,
        }
    except Exception as e:
        print(f"[supabase_client.py] Error al obtener autonomía para {band_id}: {e}")
        return {
            "band_id": band_id,
            "modo_envio": "draft_only",
            "profundidad_negociacion": "filter_conditions",
            "cache_minimo": 300,
            "cache_objetivo": 800,
            "auto_rechazar_bajo_minimo": False,
            "notificar_propuestas": True,
            "requiere_firma_humana": True,
        }


# --- Funciones de Supabase Storage (Bucket 'band-media') ---------------------

def subir_archivo_media(
    origen_local_o_bytes: str | bytes,
    path_destino: str,
    bucket_name: str = BUCKET_MEDIA_DEFAULT,
    content_type: str = None,
) -> str | None:
    """
    Suba un archivo local o bytes al bucket 'band-media' de Supabase Storage.
    Devuelve la URL pública del archivo subido o None si falla.
    """
    try:
        supabase = get_supabase_client()
        storage = supabase.storage.from_(bucket_name)

        if isinstance(origen_local_o_bytes, str):
            with open(origen_local_o_bytes, "rb") as f:
                contenido = f.read()
        else:
            contenido = origen_local_o_bytes

        file_options = {}
        if content_type:
            file_options["content-type"] = content_type

        storage.upload(path_destino, contenido, file_options)
        url_publica = obtener_url_publica_media(path_destino, bucket_name=bucket_name)
        print(f"[supabase_client.py] Archivo subido con éxito a '{bucket_name}/{path_destino}': {url_publica}")
        return url_publica
    except Exception as e:
        print(f"[supabase_client.py] Error al subir archivo a Supabase Storage ({path_destino}): {e}")
        return None


def obtener_url_publica_media(path_destino: str, bucket_name: str = BUCKET_MEDIA_DEFAULT) -> str:
    """
    Devuelve la URL pública para un recurso almacenado en Supabase Storage.
    """
    try:
        supabase = get_supabase_client()
        return supabase.storage.from_(bucket_name).get_public_url(path_destino)
    except Exception as e:
        print(f"[supabase_client.py] Error al obtener URL pública de Storage ({path_destino}): {e}")
        url_base = os.getenv("SUPABASE_URL", "").rstrip("/")
        return f"{url_base}/storage/v1/object/public/{bucket_name}/{path_destino}"
