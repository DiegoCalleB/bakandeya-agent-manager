import sys
import os
import re
import requests
import gspread
from datetime import datetime

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

import lib.sheets as sheets
import lib.telegram as telegram
from lib.busqueda import buscar_duckduckgo

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'
}

def limpiar_numero_seguidores(texto_raw):
    """
    Limpia y convierte una cadena de texto (ej. "1,334", "1.5K", "35 suscriptores") en un entero.
    Soporta formatos en inglés y español.
    """
    if not texto_raw:
        return 0
    
    texto = texto_raw.strip().lower()
    
    # Extraer el bloque numérico principal y el posible sufijo (k o m)
    match = re.search(r'([\d.,]+)\s*([km]?)', texto)
    if not match:
        return 0
        
    num_str = match.group(1)
    sufijo = match.group(2)
    
    # Reemplazar comas por puntos si actúan como separador decimal
    if "," in num_str:
        if sufijo in ('k', 'm') or len(num_str.split(",")[-1]) != 3:
            num_str = num_str.replace(",", ".")
        else:
            num_str = num_str.replace(",", "")
            
    # Quitar puntos si actúan como separador de miles
    if "." in num_str:
        partes = num_str.split(".")
        if sufijo not in ('k', 'm') and len(partes[-1]) == 3:
            num_str = num_str.replace(".", "")
            
    try:
        valor = float(num_str)
        if sufijo == 'k':
            valor *= 1000
        elif sufijo == 'm':
            valor *= 1000000
        return int(valor)
    except ValueError:
        return 0

def obtener_seguidores_instagram():
    """
    Obtiene los seguidores de Instagram buscando el perfil en DuckDuckGo.
    """
    query = "site:instagram.com/bakandeya"
    print(f"[monitor_redes] Buscando seguidores de Instagram vía DDG...")
    try:
        resultados = buscar_duckduckgo(query, max_results=3)
        for r in resultados:
            snippet = r.get("body", "")
            title = r.get("title", "")
            
            # Buscar patrones como "1,334 Followers" o "1.334 seguidores" o "813 Followers"
            match = re.search(r'([\d.,]+K?)\s*(?:Followers|seguidores)', snippet, re.IGNORECASE)
            if not match:
                match = re.search(r'([\d.,]+K?)\s*(?:Followers|seguidores)', title, re.IGNORECASE)
                
            if match:
                raw_followers = match.group(1)
                followers = limpiar_numero_seguidores(raw_followers)
                print(f"[monitor_redes] Seguidores Instagram extraídos: {followers} (de '{raw_followers}')")
                return followers
        print("[monitor_redes] Advertencia: No se encontró el conteo de seguidores en los resultados de Instagram.")
        return 0
    except Exception as e:
        print(f"[monitor_redes] Error al obtener Instagram: {e}")
        return 0

def obtener_seguidores_tiktok():
    """
    Obtiene los seguidores de TikTok descargando la página pública y buscando el JSON interno.
    """
    url = "https://www.tiktok.com/@bakandeya"
    print(f"[monitor_redes] Buscando seguidores de TikTok vía petición web...")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            match = re.search(r'"followerCount":\s*(\d+)', r.text)
            if match:
                followers = int(match.group(1))
                print(f"[monitor_redes] Seguidores TikTok extraídos: {followers}")
                return followers
        print(f"[monitor_redes] Advertencia: No se pudo extraer followerCount de TikTok. Status: {r.status_code}")
        return 0
    except Exception as e:
        print(f"[monitor_redes] Error al obtener TikTok: {e}")
        return 0

def obtener_suscriptores_youtube():
    """
    Obtiene los suscriptores de YouTube descargando la página con cookie de consentimiento.
    """
    url = "https://www.youtube.com/@Bakandeya"
    print(f"[monitor_redes] Buscando suscriptores de YouTube vía petición web...")
    try:
        cookies = {'SOCS': 'CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg'}
        r = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if r.status_code == 200:
            match = re.search(r'"subscriberCountText":\s*\{\s*"simpleText":\s*"([^"]+)"', r.text)
            if match:
                raw_subs = match.group(1)
                subs = limpiar_numero_seguidores(raw_subs)
                print(f"[monitor_redes] Suscriptores YouTube extraídos: {subs} (de '{raw_subs}')")
                return subs
            else:
                match_alt = re.search(r'"([^"]+)\s+(?:suscriptores|subscribers)"', r.text, re.IGNORECASE)
                if match_alt:
                    raw_subs = match_alt.group(1)
                    subs = limpiar_numero_seguidores(raw_subs)
                    print(f"[monitor_redes] Suscriptores YouTube extraídos (alternativo): {subs} (de '{raw_subs}')")
                    return subs
        print(f"[monitor_redes] Advertencia: No se pudo extraer suscriptores de YouTube. Status: {r.status_code}")
        return 0
    except Exception as e:
        print(f"[monitor_redes] Error al obtener YouTube: {e}")
        return 0

def ejecutar_monitor():
    """
    Ejecuta la extracción de todas las plataformas, las registra en Sheets y notifica por Telegram.
    """
    print("[monitor_redes] Iniciando recopilación de métricas de redes sociales...")
    
    instagram = obtener_seguidores_instagram()
    tiktok = obtener_seguidores_tiktok()
    youtube = obtener_suscriptores_youtube()
    
    print(f"[monitor_redes] Resultados recopilados -> IG: {instagram} | TikTok: {tiktok} | YT: {youtube}")
    
    if instagram == 0 and tiktok == 0 and youtube == 0:
        print("[monitor_redes] Error: Todas las métricas retornaron 0. Abortando escritura en Google Sheets.")
        telegram.enviar_notificacion_telegram("⚠️ *Alerta del Monitor de Redes*:\nNo se pudo extraer información de ninguna red social. Revisa los logs de ejecución.")
        return False
        
    # Registrar en Google Sheets
    try:
        client = sheets.obtener_cliente_sheets()
        spreadsheet = client.open(sheets.DOCUMENTO_SHEETS)
        
        try:
            worksheet = spreadsheet.worksheet("metricas")
        except gspread.exceptions.WorksheetNotFound:
            print("[monitor_redes] Pestaña 'metricas' no encontrada. Creándola automáticamente...")
            worksheet = spreadsheet.add_worksheet(title="metricas", rows="100", cols="5")
            worksheet.append_row(["fecha", "instagram", "tiktok", "youtube", "notas"])
            
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        row = [fecha_hoy, instagram, tiktok, youtube, "Registro automático"]
        worksheet.append_row(row)
        print(f"[monitor_redes] Fila guardada correctamente en Sheets: {row}")
        
        # Enviar notificación por Telegram
        msg = (
            "📊 *Métricas de Redes Sociales Actualizadas*:\n"
            f"• *Instagram*: {instagram:,} seguidores\n"
            f"• *TikTok*: {tiktok:,} seguidores\n"
            f"• *YouTube*: {youtube:,} suscriptores"
        ).replace(",", ".") # Formatear miles con punto
        
        telegram.enviar_notificacion_telegram(msg)
        return True
    except Exception as e:
        print(f"[monitor_redes] Error al guardar en Sheets o notificar: {e}")
        return False

if __name__ == "__main__":
    ejecutar_monitor()
