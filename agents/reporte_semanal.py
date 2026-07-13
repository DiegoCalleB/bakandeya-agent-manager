import sys
import os
from collections import Counter

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

import lib.sheets as sheets
import lib.estados as estados
import lib.telegram as telegram

def obtener_resumen_leads():
    """
    Lee la Google Sheet y cuenta cuántos leads hay en cada estado del pipeline.
    """
    print("[reporte_semanal] Leyendo leads de Google Sheets...")
    try:
        leads = sheets.obtener_leads()
        
        # Contar leads por estado
        estados_leads = [lead.get("estado", "").strip() for lead in leads]
        contador = Counter(estados_leads)
        
        # Mapear estados para el reporte
        resumen = {
            "nuevo": contador.get(estados.NUEVO, 0),
            "pendiente_aprobacion": contador.get(estados.PENDIENTE, 0),
            "aprobado": contador.get(estados.APROBADO, 0),
            "esperando_respuesta": contador.get(estados.ESPERANDO, 0),
            "interesado": contador.get(estados.INTERESADO, 0),
            "negociando": contador.get(estados.NEGOCIANDO, 0),
            "no_interesado": contador.get(estados.NO_INTERESADO, 0),
            "descartado": contador.get(estados.DESCARTADO, 0),
            "total": len(leads)
        }
        return resumen
    except Exception as e:
        print(f"[reporte_semanal] Error al obtener resumen de leads: {e}")
        return None

def obtener_metricas_redes():
    """
    Lee la pestaña 'metricas' para obtener los últimos datos y calcular la diferencia.
    """
    print("[reporte_semanal] Leyendo métricas de redes sociales...")
    try:
        client = sheets.obtener_cliente_sheets()
        spreadsheet = client.open(sheets.DOCUMENTO_SHEETS)
        
        try:
            worksheet = spreadsheet.worksheet("metricas")
            records = worksheet.get_all_records()
        except Exception:
            print("[reporte_semanal] No se encontró la pestaña 'metricas' o está vacía.")
            return None
            
        if not records:
            return None
            
        ultimo = records[-1]
        penultimo = records[-2] if len(records) >= 2 else None
        
        def formatear_diferencia(actual, anterior):
            if anterior is None:
                return ""
            try:
                diff = int(actual) - int(anterior)
                if diff > 0:
                    return f" (+{diff:,})".replace(",", ".")
                elif diff < 0:
                    return f" ({diff:,})".replace(",", ".")
                else:
                    return " (=)"
            except (ValueError, TypeError):
                return ""
                
        resultado = {
            "fecha": ultimo.get("fecha", ""),
            "instagram": {
                "actual": ultimo.get("instagram", 0),
                "diff": formatear_diferencia(ultimo.get("instagram"), penultimo.get("instagram") if penultimo else None)
            },
            "tiktok": {
                "actual": ultimo.get("tiktok", 0),
                "diff": formatear_diferencia(ultimo.get("tiktok"), penultimo.get("tiktok") if penultimo else None)
            },
            "youtube": {
                "actual": ultimo.get("youtube", 0),
                "diff": formatear_diferencia(ultimo.get("youtube"), penultimo.get("youtube") if penultimo else None)
            }
        }
        return resultado
    except Exception as e:
        print(f"[reporte_semanal] Error al obtener métricas de redes: {e}")
        return None

def generar_reporte():
    """
    Genera el reporte, construye el mensaje y lo envía a Telegram.
    """
    print("[reporte_semanal] Generando reporte semanal...")
    
    resumen_leads = obtener_resumen_leads()
    metricas = obtener_metricas_redes()
    
    if resumen_leads is None:
        print("[reporte_semanal] Error: No se pudo generar el resumen de leads. Cancelando envío.")
        return False
        
    # Construcción de mensaje
    lineas = [
        "📅 *Reporte Semanal — Bakandeya* 📅\n",
        "💼 *Pipeline de Leads (Conciertos)*:",
        f"• 🆕 *Nuevos (Scout)*: {resumen_leads['nuevo']}",
        f"• 📝 *Pitches para revisar*: {resumen_leads['pendiente_aprobacion']}",
        f"• ✅ *Listos para enviar*: {resumen_leads['aprobado']}",
        f"• 📨 *Esperando Respuesta*: {resumen_leads['esperando_respuesta']}",
        f"• 🔥 *Interesados*: {resumen_leads['interesado']}",
        f"• 🤝 *En Negociación*: {resumen_leads['negociando']}",
        f"• ❌ *Descartados / No interesados*: {resumen_leads['no_interesado'] + resumen_leads['descartado']}",
        f"  _Total leads en base de datos: {resumen_leads['total']}_\n"
    ]
    
    if metricas:
        lineas.extend([
            "📊 *Seguidores en Redes Sociales*:",
            f"• *Instagram*: {metricas['instagram']['actual']:,}{metricas['instagram']['diff']} seg.",
            f"• *TikTok*: {metricas['tiktok']['actual']:,}{metricas['tiktok']['diff']} seg.",
            f"• *YouTube*: {metricas['youtube']['actual']:,}{metricas['youtube']['diff']} suscr.",
            f"  _(Última medición: {metricas['fecha']})_"
        ])
    else:
        lineas.extend([
            "📊 *Seguidores en Redes Sociales*:",
            "• Sin datos históricos suficientes registrados aún."
        ])
        
    mensaje = "\n".join(lineas).replace(",", ".")  # Reemplazar comas por puntos en miles
    
    # Enviar a Telegram
    print("[reporte_semanal] Enviando reporte a Telegram...")
    res = telegram.enviar_notificacion_telegram(mensaje)
    
    if res:
        print("[reporte_semanal] Reporte enviado con éxito.")
        return True
    else:
        print("[reporte_semanal] ERROR al enviar el reporte por Telegram.")
        return False

if __name__ == "__main__":
    generar_reporte()
