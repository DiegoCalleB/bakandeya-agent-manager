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
    mocker.patch("agents.scout.obtener_resultados_busqueda", return_value=[
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
