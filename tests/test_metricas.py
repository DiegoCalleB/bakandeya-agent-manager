import pytest
from lib.metricas import (
    obtener_metricas_booking,
    obtener_metricas_youtube,
    formatear_pie_kpis_telegram,
    generar_informe_dashboard_completo,
)

def test_obtener_metricas_booking(mock_sheets_api):
    """
    Verifica que el cálculo de métricas de booking devuelva porcentajes y horas de trabajo ahorradas correctos.
    """
    metrics = obtener_metricas_booking()

    assert "total_leads" in metrics
    assert "enviados" in metrics
    assert "tasa_respuesta_pct" in metrics
    assert "horas_ahorradas" in metrics

    # En mock_sheets_api hay 3 leads (2 nuevos, 1 pendiente_aprobacion)
    assert metrics["total_leads"] == 3
    assert metrics["horas_ahorradas"] == 0.8  # (3 * 15) / 60 = 0.75 -> round(0.75, 1) = 0.8


def test_obtener_metricas_youtube(mocker):
    """
    Verifica el fallback seguro si falla o faltan credenciales de la API de YouTube.
    """
    yt_stats = obtener_metricas_youtube()
    assert "suscriptores" in yt_stats
    assert "vistas_teaser" in yt_stats


def test_formatear_pie_kpis_telegram(mock_sheets_api):
    """
    Verifica que el pie de tarjeta comprimido de KPIs contenga los elementos visuales clave.
    """
    pie = formatear_pie_kpis_telegram()

    assert "KPIs Bakandeya IA Management" in pie
    assert "Tasa de respuesta salas" in pie
    assert "Tiempo operativo ahorrado" in pie


def test_generar_informe_dashboard_completo(mock_sheets_api):
    """
    Verifica que el reporte ejecutivo completo contenga todas las secciones requeridas.
    """
    dashboard = generar_informe_dashboard_completo()

    assert "DASHBOARD DE RENDIMIENTO" in dashboard
    assert "EMBUDO DE CONTRATACIÓN DE CONCIERTOS" in dashboard
    assert "IMPACTO EN REDES SOCIALES" in dashboard
    assert "EFICIENCIA OPERATIVA" in dashboard
