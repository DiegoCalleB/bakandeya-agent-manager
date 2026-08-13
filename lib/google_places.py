"""
Cliente ligero para Google Places API (New) — Text Search + Place Details + Photos.

Se usa como PRIMERA fuente de dirección/teléfono/web/imagen en scout.py::procesar_un_lead: al ser un
dato estructurado y verificado por Google (no texto libre interpretado por un LLM), se trata
como confianza 'alta' directamente.

Permite extraer imágenes/fotos reales del lugar desde Google Places y subirlas automáticamente
a Supabase Storage (bucket 'band-media') para vincular su URL verificada en 'imagen_url' e 'icono'.

Requiere GOOGLE_PLACES_API_KEY en el entorno (.env).
"""
import os
import time
import random
import difflib
import requests
from dotenv import load_dotenv
import lib.supabase_client as sb

load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

_URL_TEXT_SEARCH = "https://places.googleapis.com/v1/places:searchText"
_URL_PLACE_DETAILS = "https://places.googleapis.com/v1/places/{place_id}"

_UMBRAL_SIMILITUD_NOMBRE = 0.55


def esta_configurado():
    return bool(API_KEY)


def _normalizar(texto):
    return (texto or "").strip().lower()


def _similitud(a, b):
    return difflib.SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


def buscar_lugar(nombre, ciudad, lead_id=None):
    """
    Busca `nombre` en `ciudad` (España) en Google Places y devuelve un dict
    {"direccion": ..., "telefono": ..., "website": ..., "imagen_url": ..., "icono": ...}
    listo para combinar en scout.py. Si hay foto, la sube a Supabase Storage 'band-media'.
    """
    if not API_KEY:
        return None

    place_id, nombre_encontrado = _buscar_place_id(nombre, ciudad)
    if not place_id:
        return None

    if _similitud(nombre, nombre_encontrado) < _UMBRAL_SIMILITUD_NOMBRE:
        print(f"[google_places.py] Descartado: '{nombre_encontrado}' no se parece lo suficiente a '{nombre}' buscado.")
        return None

    detalles = _obtener_detalles(place_id)
    if not detalles:
        return None

    # Si Places devolvió foto y tenemos lead_id (o nombre normalizado), subimos a Supabase Storage
    photo_name = detalles.pop("photo_name", None)
    if photo_name:
        url_imagen = descargar_y_subir_foto_places(photo_name, lead_id=lead_id or nombre)
        if url_imagen:
            detalles["imagen_url"] = url_imagen
            detalles["icono"] = url_imagen

    return detalles


def _buscar_place_id(nombre, ciudad):
    try:
        resp = requests.post(
            _URL_TEXT_SEARCH,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": API_KEY,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
            },
            json={"textQuery": f"{nombre}, {ciudad}, España"},
            timeout=10,
        )
        resp.raise_for_status()
        lugares = (resp.json() or {}).get("places") or []
        if not lugares:
            return None, None
        primero = lugares[0]
        return primero.get("id"), (primero.get("displayName") or {}).get("text")
    except requests.RequestException as e:
        print(f"[google_places.py] Error en Text Search para '{nombre}': {e}")
        return None, None


def _obtener_detalles(place_id):
    try:
        time.sleep(random.uniform(0.2, 0.5))
        resp = requests.get(
            _URL_PLACE_DETAILS.format(place_id=place_id),
            headers={
                "X-Goog-Api-Key": API_KEY,
                "X-Goog-FieldMask": "formattedAddress,internationalPhoneNumber,nationalPhoneNumber,websiteUri,photos",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or {}

        photos = data.get("photos") or []
        photo_name = photos[0].get("name") if photos else None

        return {
            "direccion": data.get("formattedAddress"),
            "telefono": data.get("internationalPhoneNumber") or data.get("nationalPhoneNumber"),
            "website": data.get("websiteUri"),
            "photo_name": photo_name,
        }
    except requests.RequestException as e:
        print(f"[google_places.py] Error en Place Details para {place_id}: {e}")
        return None


def descargar_y_subir_foto_places(photo_name: str, lead_id: str) -> str | None:
    """
    Descarga la imagen del recurso de Google Places y la sube al bucket 'band-media' de Supabase Storage.
    Devuelve la URL pública y verificada en Supabase Storage.
    """
    if not API_KEY or not photo_name:
        return None

    try:
        media_url = f"https://places.googleapis.com/v1/{photo_name}/media?maxHeightPx=600&maxWidthPx=600&key={API_KEY}"
        res = requests.get(media_url, timeout=10)
        if res.status_code == 200:
            subpath = f"leads/places_{str(lead_id).replace('/', '_')}.jpg"
            url_publica = sb.subir_archivo_media(res.content, subpath, content_type="image/jpeg")
            return url_publica
    except Exception as e:
        print(f"[google_places.py] Error al descargar/subir foto de Places para lead {lead_id}: {e}")

    return None
