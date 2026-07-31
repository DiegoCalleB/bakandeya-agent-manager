import sys
import os

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

import lib.metricas as metricas
import lib.telegram as telegram

def ejecutar_dashboard_metricas():
    """
    Genera el informe completo de rendimiento y lo envía por Telegram.
    """
    print("[agente_metricas.py] Calculando métricas y estadísticas del sistema...")
    informe = metricas.generar_informe_dashboard_completo()
    print("\n" + informe + "\n")

    enviado = telegram.enviar_notificacion_telegram(informe)
    if enviado:
        print("[agente_metricas.py] Dashboard enviado con éxito a Telegram.")
    else:
        print("[agente_metricas.py] No se pudo enviar el dashboard a Telegram (revisa credenciales TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID).")

if __name__ == "__main__":
    ejecutar_dashboard_metricas()
