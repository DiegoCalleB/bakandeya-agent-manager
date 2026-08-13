"""
Registro de bandas multi-tenant e integración con Supabase.

Bakandeya_AIStudio_Application gestiona el registro de bandas, su EPK (dossier, rider,
enlaces, contacto) y su nivel de autonomía en Supabase (`registered_bands`, `dossier_epk`, `config_autonomia`).
Este módulo las lee y las adapta a la forma que esperan agents/redactor.py y lib/gmail_client.py.

Además, resuelve automáticamente las URLs públicas de los archivos PDF del Dossier y Logo
almacenados en Supabase Storage (bucket 'band-media').
"""
import os
import json
import lib.supabase_client as sb

BAND_ID_DEFAULT = sb.BAND_ID_DEFAULT

_RUTA_EPK_BAKANDEYA_ESTATICO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "epk_bakandeya.json"
)


def _cargar_json_bakandeya_estatico():
    try:
        with open(_RUTA_EPK_BAKANDEYA_ESTATICO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[bandas.py] Error al cargar el EPK estático de Bakandeya: {e}")
        return {}


def listar_bandas_activas():
    """Devuelve la lista de bandas activas desde Supabase ('registered_bands')."""
    return sb.obtener_bandas_activas()


def _resolver_archivos_storage_supabase(band_id):
    """
    Busca los archivos de Dossier y Logo almacenados en el bucket 'band-media' de Supabase Storage
    para la carpeta 'bandas/<band_id>/' y devuelve un diccionario con sus URLs públicas.
    """
    res = {"dossier_pdf_url": "", "logo_url": ""}
    try:
        supabase = sb.get_supabase_client()
        storage = supabase.storage.from_(sb.BUCKET_MEDIA_DEFAULT)

        # 1. Buscar Dossier PDF
        try:
            archivos_dossier = storage.list(f"bandas/{band_id}/dossier") or []
            pdfs = [f for f in archivos_dossier if f.get("name", "").lower().endswith(".pdf")]
            if pdfs:
                nombre_pdf = pdfs[-1]["name"]
                res["dossier_pdf_url"] = storage.get_public_url(f"bandas/{band_id}/dossier/{nombre_pdf}")
        except Exception:
            pass

        # 2. Buscar Logo
        try:
            archivos_logo = storage.list(f"bandas/{band_id}/logo") or []
            imgs = [f for f in archivos_logo if any(f.get("name", "").lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp"))]
            if imgs:
                nombre_img = imgs[-1]["name"]
                res["logo_url"] = storage.get_public_url(f"bandas/{band_id}/logo/{nombre_img}")
        except Exception:
            pass
    except Exception as e:
        print(f"[bandas.py] Aviso resolviendo archivos de Storage para {band_id}: {e}")

    return res


def cargar_epk_banda(band_id=BAND_ID_DEFAULT):
    """
    Devuelve el EPK completo de una banda adaptado para redactor.py y gmail_client.py,
    incluyendo enlaces, dossier PDF adjunto en Supabase Storage, rider técnico y datos de firma.
    """
    fila = sb.obtener_epk_banda(band_id)
    archivos_supabase = _resolver_archivos_storage_supabase(band_id)

    dossier_url = (
        fila.get("dossier_pdf_url")
        or archivos_supabase.get("dossier_pdf_url")
        or ""
    )
    logo_url = (
        fila.get("logo_url")
        or archivos_supabase.get("logo_url")
        or ""
    )

    enlaces = {
        "youtube_teaser_aca2026": fila.get("youtube_url") or "",
        "youtube_perfil": fila.get("youtube_url") or "",
        "instagram": fila.get("instagram_url") or "",
        "tik_tok": fila.get("tiktok_url") or "",
        "dossier_epk": dossier_url,
    }
    contacto = {
        "nombre": fila.get("contacto_nombre") or "Bakandeya IA Management",
        "email": fila.get("contacto_email") or "diego.delacalleb@gmail.com",
        "telefono": fila.get("contacto_telefono") or "+34 652938521",
    }
    epk = {
        "nombre": fila.get("nombre_banda") or "Bakandeya",
        "estilo": "",
        "integrantes": [],
        "influencias": [],
        "descripcion_corta": fila.get("biografia") or "",
        "biografia_completa": fila.get("biografia") or "",
        "trayectoria_destacada": "",
        "enlaces": enlaces,
        "rider_tecnico": fila.get("rider_tecnico") or "",
        "dossier_pdf_url": dossier_url,
        "rider_pdf_url": fila.get("rider_pdf_url") or "",
        "logo_url": logo_url,
        "contacto": contacto,
    }

    if band_id == BAND_ID_DEFAULT:
        # Enriquecer con el JSON curado a mano de Bakandeya
        estatico = _cargar_json_bakandeya_estatico()
        for clave, valor in estatico.items():
            if clave == "enlaces":
                fusion = dict(valor)
                if dossier_url:
                    fusion["dossier_epk"] = dossier_url
                epk["enlaces"] = fusion
            elif clave == "contacto":
                fusion = dict(valor)
                fusion.update({k: v for k, v in contacto.items() if v})
                epk["contacto"] = fusion
            elif not epk.get(clave):
                epk[clave] = valor

        if dossier_url:
            epk["dossier_pdf_url"] = dossier_url
        if logo_url:
            epk["logo_url"] = logo_url

    return epk


def cargar_autonomia_banda(band_id=BAND_ID_DEFAULT):
    """
    Devuelve la configuración de autonomía de la banda desde Supabase.
    """
    fila = sb.obtener_autonomia_banda(band_id)

    def _bool(v):
        return str(v).strip().lower() in ("true", "1", "si", "sí", "yes")

    def _int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        "band_id": band_id,
        "modo_envio": fila.get("modo_envio") or "draft_only",
        "profundidad_negociacion": fila.get("profundidad_negociacion") or "filter_conditions",
        "cache_minimo": _int(fila.get("cache_minimo"), 300),
        "cache_objetivo": _int(fila.get("cache_objetivo"), 800),
        "auto_rechazar_bajo_minimo": _bool(fila.get("auto_rechazar_bajo_minimo")),
        "notificar_propuestas": _bool(fila.get("notificar_propuestas", "true")),
        "requiere_firma_humana": _bool(fila.get("requiere_firma_humana", "true")),
    }
