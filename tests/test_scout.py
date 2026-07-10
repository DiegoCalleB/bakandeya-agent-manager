import json
import pytest
from agents.scout import enriquecer_leads_sin_contacto

def test_scout_enriquecimiento(mocker, mock_db):
    """
    Verifica que el agente Scout encuentre la web, descargue el contenido,
    extraiga el email usando Claude y actualice la hoja de cálculo con el email y notas.
    """
    # En mock_db de conftest.py, lead_003 (Sala Karma) está en estado 'nuevo' y no tiene email
    lead_003 = next(l for l in mock_db if l["id"] == "lead_003")
    assert lead_003["email_contacto"] == ""
    assert lead_003["estado"] == "nuevo"
    
    # Completar lead_001 para que el scout lo salte y procese directamente lead_003
    lead_001 = next(l for l in mock_db if l["id"] == "lead_001")
    lead_001["telefono"] = "913 65 24 15"
    lead_001["website"] = "https://salaelsol.com"
    lead_001["instagram"] = "@salaelsol"
    
    # Mockear la búsqueda y extracción por snippets
    mocker.patch("agents.scout.buscar_duckduckgo", return_value=[
        {"title": "Sala Karma Pontevedra", "href": "https://salakarma.es", "body": "Contacto info@salakarma.es +34 986 112233"}
    ])
    
    mocker.patch("agents.scout.extraer_datos_contacto_de_snippets", return_value={
        "email": "info@salakarma.es",
        "telefono": "+34 986 112233",
        "instagram": "@salakarma",
        "website": "https://salakarma.es"
    })
    
    # Mockear la descarga de páginas (home y contacto)
    def mock_descargar_texto_pagina(url):
        if "contacto" in url:
            return "Para contrataciones escribe a info@salakarma.es o llama al +34 986 112233.", []
        return "Bienvenidos a Sala Karma Pontevedra. Secciones: /contacto y /aviso-legal.", ["https://salakarma.es/contacto"]
        
    mocker.patch("agents.scout.descargar_texto_pagina", side_effect=mock_descargar_texto_pagina)
    
    # Mockear la respuesta de la API de Claude Haiku
    def mock_extraer_datos_contacto(texto, url_origen, tipo="sala"):
        if "info@salakarma.es" in texto:
            return {
                "email": "info@salakarma.es",
                "telefono": "+34 986 112233",
                "instagram": "@salakarma",
                "aforo": 250
            }
        return {
            "email": None,
            "telefono": None,
            "instagram": None,
            "aforo": None
        }
        
    mocker.patch("agents.scout.extraer_datos_contacto", side_effect=mock_extraer_datos_contacto)
    
    # Ejecutar enriquecimiento limitado a 1 lead
    enriquecidos = enriquecer_leads_sin_contacto(limite_leads=1)
    
    # Debería haber enriquecido con éxito a Sala Karma (1 lead)
    assert enriquecidos == 1
    
    # Comprobar que los datos en mock_db se actualizaron
    assert lead_003["email_contacto"] == "info@salakarma.es"
    assert lead_003["telefono"] == "+34 986 112233"
    assert "Teléfono: +34 986 112233" in lead_003["notas"]
    assert "Instagram: @salakarma" in lead_003["notas"]
    assert lead_003["aforo"] == 250
    assert lead_003["tipo"] == "sala"

def test_scout_mueve_a_sin_contacto_sin_email(mocker, mock_db):
    """
    Coordinación de estados: un lead 'nuevo' que tras búsqueda exhaustiva no consigue email
    debe salir de 'nuevo' a 'sin_contacto' (terminal), no quedarse atascado reintentándose.
    """
    import lib.estados as estados
    from agents.scout import enriquecer_leads_sin_contacto

    # Completar lead_001 para que el scout procese solo lead_003 (Sala Karma, sin email).
    lead_001 = next(l for l in mock_db if l["id"] == "lead_001")
    lead_001["telefono"] = "913 65 24 15"
    lead_001["website"] = "https://salaelsol.com"
    lead_001["instagram"] = "@salaelsol"
    lead_003 = next(l for l in mock_db if l["id"] == "lead_003")
    assert lead_003["estado"] == estados.NUEVO

    # Búsqueda devuelve algo, pero la IA no extrae ningún dato de contacto.
    mocker.patch("agents.scout.buscar_duckduckgo", return_value=[
        {"title": "t", "href": "https://x.es", "body": "b"}
    ])
    mocker.patch("agents.scout.extraer_datos_contacto_de_snippets", return_value={})
    mocker.patch("agents.scout.descargar_texto_pagina", return_value=("", []))

    enriquecer_leads_sin_contacto(limite_leads=1)

    assert lead_003["estado"] == estados.SIN_CONTACTO


def test_procesar_campos_extraidos():
    """
    El helper anti-alucinación: solo los datos de confianza 'alta' se aceptan; los de
    confianza media/baja se devuelven como sugerencias y los nulos se descartan.
    """
    from agents.scout import _procesar_campos_extraidos

    data = {
        "email": {"valor": "a@b.com", "confianza": "alta", "fuente": "[1]"},
        "telefono": {"valor": "123", "confianza": "media", "fuente": "[2]"},
        "instagram": "@plano",  # valor plano (retrocompatibilidad) → se asume fiable
        "website": {"valor": "null", "confianza": "alta", "fuente": None},  # null textual → descartado
    }
    aceptados, sugerencias = _procesar_campos_extraidos(
        data, ["email", "telefono", "instagram", "website"]
    )

    assert aceptados == {"email": "a@b.com", "instagram": "@plano"}
    assert "website" not in aceptados
    assert any("telefono" in s for s in sugerencias)


def test_scout_extraccion_confianza(mocker):
    """
    Verifica que extraer_datos_contacto_de_snippets, sobre una respuesta JSON con distintos
    niveles de confianza, escriba SOLO los datos de confianza alta y deje el resto como
    sugerencias a verificar (regla anti-alucinación).
    """
    from agents.scout import extraer_datos_contacto_de_snippets

    respuesta_json = json.dumps({
        "email": {"valor": "info@sala.com", "confianza": "alta", "fuente": "[1]"},
        "telefono": {"valor": "986111222", "confianza": "baja", "fuente": None},
        "instagram": {"valor": None, "confianza": "baja", "fuente": None},
        "website": {"valor": "https://sala.com", "confianza": "media", "fuente": "[2]"},
        "genero": {"valor": "Rock / Indie", "confianza": "alta", "fuente": "[1]"},
    })
    # Sobrescribe el mock autouse de conftest para esta llamada concreta.
    mocker.patch("agents.scout.gemini_client.generar_texto_gemini", return_value=respuesta_json)

    datos = extraer_datos_contacto_de_snippets(
        "Sala X", "Vigo", [{"title": "t", "href": "h", "body": "b"}], tipo="sala"
    )

    # Confianza alta → se aceptan como datos verificados
    assert datos["email"] == "info@sala.com"
    assert datos["genero"] == "Rock / Indie"
    # Confianza media/baja → NO se escriben
    assert "telefono" not in datos
    assert "website" not in datos
    assert "instagram" not in datos
    # Los de confianza insuficiente (no nulos) quedan como sugerencias
    sugerencias = " ".join(datos.get("_sugerencias", []))
    assert "telefono" in sugerencias
    assert "website" in sugerencias
    assert "instagram" not in sugerencias  # el valor null no genera sugerencia


def test_scout_inferir_tipo():
    from agents.scout import inferir_tipo_lead
    
    assert inferir_tipo_lead("Ayuntamiento de Vigo") == "ayuntamiento"
    assert inferir_tipo_lead("Concello de Lalín") == "ayuntamiento"
    assert inferir_tipo_lead("Ayto de Madrid") == "ayuntamiento"
    
    assert inferir_tipo_lead("Festival PortAmérica") == "festival"
    assert inferir_tipo_lead("O Son do Camiño Fest") == "festival"
    assert inferir_tipo_lead("FestiBal") == "festival"
    
    assert inferir_tipo_lead("Sala El Sol") == "sala"
    assert inferir_tipo_lead("La Riviera") == "sala"
