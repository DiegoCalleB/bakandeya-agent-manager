import sys
import os
import json
from datetime import datetime

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

import lib.sheets as sheets
import lib.telegram as telegram
from lib.gemini_client import generar_texto_gemini

def obtener_datos_viaje_ia(ciudad):
    """
    Usa Gemini Flash para estimar la distancia por carretera y si requiere noche de hotel.
    El origen siempre es Madrid, España.
    """
    # Si la ciudad de destino es Madrid, el viaje tiene coste 0
    ciudad_limpia = ciudad.strip().lower()
    if "madrid" in ciudad_limpia:
        return {
            "distancia_km": 0,
            "tiempo_horas": 0,
            "requiere_alojamiento": False
        }
        
    prompt = (
        f"Dada la ciudad de destino '{ciudad}' y sabiendo que el origen del viaje es Madrid, España, "
        "proporciona los siguientes datos estimados en un JSON con formato estructurado:\n"
        "1. 'distancia_km': la distancia aproximada por carretera (solo ida) en kilómetros (un número entero).\n"
        "2. 'tiempo_horas': el tiempo aproximado de viaje en coche en horas (un número decimal).\n"
        "3. 'requiere_alojamiento': true si la distancia es mayor a 200 km, false de lo contrario.\n\n"
        "Devuelve únicamente el objeto JSON, sin formato markdown ni explicaciones."
    )
    
    print(f"[finanzas] Consultando a Gemini sobre ruta: Madrid -> {ciudad}...")
    res_json = generar_texto_gemini(prompt, forzar_json=True, temperature=0.1)
    
    if res_json:
        try:
            return json.loads(res_json)
        except Exception as e:
            print(f"[finanzas] Error al decodificar JSON de Gemini para '{ciudad}': {e}. Usando valores por defecto.")
            
    # Estimación básica de fallback para España
    return {
        "distancia_km": 300,
        "tiempo_horas": 3.0,
        "requiere_alojamiento": True
    }

def es_concierto_registrado(concert_id, transacciones):
    """
    Verifica si un concierto ya tiene transacciones asociadas en la pestaña finanzas.
    Busca coincidencia en el ID o en el concepto (con el marcador [Ref: con-X]).
    """
    for tx in transacciones:
        tx_id = str(tx.get("id", ""))
        concepto = str(tx.get("concepto", ""))
        
        if tx_id.startswith(f"fin-{concert_id}-") or f"[Ref: {concert_id}]" in concepto:
            return True
    return False

def ejecutar_agente_finanzas():
    """
    Sincroniza conciertos con finanzas registrando ingresos y gastos de desplazamiento.
    """
    print("[finanzas] Iniciando sincronización de finanzas...")
    
    try:
        client = sheets.obtener_cliente_sheets()
        spreadsheet = client.open(sheets.DOCUMENTO_SHEETS)
        
        # Cargar hojas de conciertos y finanzas
        conciertos_ws = spreadsheet.worksheet("conciertos")
        finanzas_ws = spreadsheet.worksheet("finanzas")
        
        conciertos = conciertos_ws.get_all_records()
        finanzas = finanzas_ws.get_all_records()
    except Exception as e:
        print(f"[finanzas] ERROR al abrir las pestañas de Google Sheets: {e}")
        return False
        
    print(f"[finanzas] Cargados {len(conciertos)} conciertos y {len(finanzas)} transacciones.")
    nuevas_filas = []
    conciertos_procesados = 0
    
    for con in conciertos:
        concert_id = str(con.get("id", "")).strip()
        sala = str(con.get("sala", "")).strip()
        ciudad = str(con.get("ciudad", "")).strip()
        cache_raw = con.get("cache", 0)
        fecha = str(con.get("fecha", "")).strip()
        
        if not concert_id or not sala or not ciudad:
            continue
            
        # Solo procesar conciertos activos/confirmados/pendientes
        # Omitimos si no hay un caché válido o fecha registrada
        try:
            cache = float(cache_raw)
        except (ValueError, TypeError):
            print(f"[finanzas] Concierto {concert_id} ({sala}) no tiene un caché válido: '{cache_raw}'. Se omite.")
            continue
            
        if not fecha:
            print(f"[finanzas] Concierto {concert_id} ({sala}) no tiene fecha registrada. Se omite.")
            continue
            
        # Comprobar si ya está registrado en finanzas
        if es_concierto_registrado(concert_id, finanzas):
            print(f"[finanzas] Concierto {concert_id} ({sala}) ya se encuentra registrado en finanzas. Se omite.")
            continue
            
        print(f"[finanzas] ¡Nuevo concierto detectado sin registrar! {concert_id}: {sala} en {ciudad} ({fecha}) por {cache}€.")
        
        # Obtener datos de viaje por carretera
        datos_viaje = obtener_datos_viaje_ia(ciudad)
        distancia_ida = datos_viaje.get("distancia_km", 0)
        requiere_hotel = datos_viaje.get("requiere_alojamiento", False)
        distancia_total = distancia_ida * 2
        
        # Calcular costes estimados (Banda de 4 personas)
        coste_transporte = int(distancia_total * 0.40) # Furgoneta o 2 coches
        coste_dietas = 4 * 25 if distancia_ida > 50 else 0 # 100€ dietas si está fuera
        coste_alojamiento = 4 * 40 if requiere_hotel else 0 # 160€ hotel si requiere noche
        
        total_gastos = coste_transporte + coste_alojamiento + coste_dietas
        beneficio_neto = cache - total_gastos
        
        # 1. Ingreso: Caché
        nuevas_filas.append([
            f"fin-{concert_id}-ingreso",
            "ingreso",
            "concierto",
            f"Caché concierto: {sala} ({ciudad}) [Ref: {concert_id}]",
            cache,
            fecha,
            "pendiente"
        ])
        
        # 2. Gasto: Desplazamiento
        if coste_transporte > 0:
            nuevas_filas.append([
                f"fin-{concert_id}-transporte",
                "gasto",
                "transporte",
                f"Gastos de viaje estimados ({distancia_total} km): {sala} ({ciudad}) [Ref: {concert_id}]",
                coste_transporte,
                fecha,
                "pendiente"
            ])
            
        # 3. Gasto: Alojamiento
        if coste_alojamiento > 0:
            nuevas_filas.append([
                f"fin-{concert_id}-alojamiento",
                "gasto",
                "alojamiento",
                f"Alojamiento estimado (4 personas): {sala} ({ciudad}) [Ref: {concert_id}]",
                coste_alojamiento,
                fecha,
                "pendiente"
            ])
            
        # 4. Gasto: Dietas
        if coste_dietas > 0:
            nuevas_filas.append([
                f"fin-{concert_id}-dietas",
                "gasto",
                "dietas",
                f"Dietas estimadas (4 personas): {sala} ({ciudad}) [Ref: {concert_id}]",
                coste_dietas,
                fecha,
                "pendiente"
            ])
            
        # Formatear reporte de Telegram
        msg = (
            f"💰 *Nuevo Concierto Sincronizado en Finanzas*:\n"
            f"• *Sala*: {sala} ({ciudad})\n"
            f"• *Fecha*: {fecha}\n"
            f"• *Caché (Ingreso)*: {cache:,.0f}€\n"
            f"• *Desplazamiento*: {distancia_ida} km (ida) | {distancia_total} km (total)\n"
            f"• *Gastos Estimados*: {total_gastos:,.0f}€\n"
            f"  - _Viaje/Combustible_: {coste_transporte:,.0f}€\n"
            f"  - _Hotel (4 personas)_: {coste_alojamiento:,.0f}€\n"
            f"  - _Dietas (4 personas)_: {coste_dietas:,.0f}€\n"
            f"• 📈 *Beneficio Neto Estimado*: {beneficio_neto:,.0f}€"
        ).replace(",", ".")
        
        telegram.enviar_notificacion_telegram(msg)
        conciertos_procesados += 1
        
    if nuevas_filas:
        # Añadir de golpe todas las filas para optimizar llamadas a Sheets
        print(f"[finanzas] Escribiendo {len(nuevas_filas)} transacciones en Sheets...")
        finanzas_ws.append_rows(nuevas_filas)
        print("[finanzas] Escritura en Sheets completada.")
        
    print(f"[finanzas] Sincronización finalizada. Conciertos procesados: {conciertos_procesados} | Transacciones añadidas: {len(nuevas_filas)}")
    return True

if __name__ == "__main__":
    ejecutar_agente_finanzas()
