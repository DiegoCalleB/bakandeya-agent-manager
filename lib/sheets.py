"""
Módulo de compatibilidad para lib/sheets.py -> Supabase.

Reorienta todas las operaciones históricas de Google Sheets hacia Supabase
utilizando lib/supabase_client.py. Mantiene la misma firma de funciones
para asegurar compatibilidad completa con los agentes existentes.
"""

import os
from dotenv import load_dotenv
import lib.supabase_client as sb

load_dotenv()

# Nombres y constantes históricas mantenidas por compatibilidad
DOCUMENTO_SHEETS = os.getenv("GOOGLE_SHEETS_DOCUMENT", "Bakandeya Supabase DB")
BAND_ID_DEFAULT = sb.BAND_ID_DEFAULT
NOMBRE_HOJA_HILOS = "hilos_emails"
NOMBRE_HOJA_MEDIOS = "medios_scout"
NOMBRE_HOJA_BANDAS = "registro_bandas"
NOMBRE_HOJA_EPK = "dossier_epk"
NOMBRE_HOJA_AUTONOMIA = "config_autonomia"

CABECERAS_HILOS = ["id", "lead_id", "nombre_sala", "fecha", "remitente", "remitente_nombre", "asunto", "mensaje"]
CABECERAS_MEDIOS = [
    "id", "nombre_medio", "tipo_medio", "ciudad", "alcance", "direccion", "email_contacto",
    "enfoque_editorial", "fuente", "estado", "pitch_generado", "fecha_envio",
    "fecha_ultima_respuesta", "notas", "band_id"
]


def obtener_cliente_sheets():
    """Devuelve la instancia del cliente de Supabase (reemplaza a gspread)."""
    return sb.get_supabase_client()


def obtener_leads(estado=None, nombre_hoja="leads", band_id=None):
    """Obtiene leads desde Supabase."""
    return sb.obtener_leads(estado=estado, nombre_hoja=nombre_hoja, band_id=band_id)


def actualizar_datos_lead(lead_id, datos_dict, nombre_hoja="leads"):
    """Actualiza campos de un lead en Supabase."""
    return sb.actualizar_datos_lead(lead_id, datos_dict, nombre_hoja=nombre_hoja)


def actualizar_estado_lead(lead_id, nuevo_estado, pitch=None, notas=None, nombre_hoja="leads"):
    """Actualiza estado y notas de un lead en Supabase."""
    return sb.actualizar_estado_lead(lead_id, nuevo_estado, pitch=pitch, notas=notas, nombre_hoja=nombre_hoja)


def crear_leads(lista_datos_dict, nombre_hoja="leads"):
    """Crea múltiples leads en Supabase."""
    return sb.crear_leads(lista_datos_dict, nombre_hoja=nombre_hoja)


def registrar_mensaje_hilo(lead_id, nombre_sala, fecha, remitente, remitente_nombre, asunto, mensaje, mensaje_id=None):
    """Registra un mensaje de conversación en Supabase."""
    return sb.registrar_mensaje_hilo(lead_id, nombre_sala, fecha, remitente, remitente_nombre, asunto, mensaje, mensaje_id=mensaje_id)


def _leer_filas_hoja_externa(nombre_hoja):
    """Lee filas de hojas auxiliares/externas desde Supabase."""
    return sb.obtener_leads(nombre_hoja=nombre_hoja)


def obtener_bandas_activas():
    """Obtiene bandas activas desde Supabase."""
    return sb.obtener_bandas_activas()


def obtener_epk_banda(band_id=BAND_ID_DEFAULT):
    """Obtiene EPK de la banda desde Supabase."""
    return sb.obtener_epk_banda(band_id)


def obtener_autonomia_banda(band_id=BAND_ID_DEFAULT):
    """Obtiene configuración de autonomía desde Supabase."""
    return sb.obtener_autonomia_banda(band_id)


def subir_archivo_media(origen_local_o_bytes, path_destino, bucket_name=sb.BUCKET_MEDIA_DEFAULT, content_type=None):
    """Suba un archivo multimedia a Supabase Storage (bucket 'band-media')."""
    return sb.subir_archivo_media(origen_local_o_bytes, path_destino, bucket_name=bucket_name, content_type=content_type)


def obtener_url_publica_media(path_destino, bucket_name=sb.BUCKET_MEDIA_DEFAULT):
    """Obtiene la URL pública de un archivo en Supabase Storage."""
    return sb.obtener_url_publica_media(path_destino, bucket_name=bucket_name)
