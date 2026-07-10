import pytest
from agents.scout_descubridor import normalizar_nombre, descubrir_y_añadir_leads

def test_normalizar_nombre():
    """
    Verifica que la normalización de nombres para deduplicación funcione correctamente.
    """
    assert normalizar_nombre("Ayuntamiento de Vigo") == "vigo"
    assert normalizar_nombre("Concello de Lalín") == "lalin"
    assert normalizar_nombre("Sala El Sol") == "elsol"
    assert normalizar_nombre("Festival PortAmérica") == "portamerica"
    assert normalizar_nombre("O Son do Camiño Fest") == "osondocamino"
    assert normalizar_nombre(" La - Riviera ") == "lariviera"

def test_descubrir_y_añadir_leads(mocker, mock_db):
    """
    Verifica que el descubridor busque, filtre duplicados usando la normalización
    e inserte los nuevos leads de forma masiva en la hoja simulada.
    """
    # mock_db contiene inicialmente:
    # lead_001 (Sala El Sol), lead_002 (Apolo), lead_003 (Sala Karma)
    assert len(mock_db) == 3
    
    # Mockear búsqueda en DuckDuckGo
    mocker.patch("agents.scout_descubridor.buscar_duckduckgo", return_value=[
        {"title": "Ayuntamiento de Vigo", "href": "https://vigo.org", "body": "Ayuntamiento de Vigo contacto y concejalías."},
        {"title": "Sala El Sol Madrid", "href": "https://salaelsol.com", "body": "Sala El Sol conciertos en Madrid."}
    ])
    
    # Mockear la IA de Gemini para devolver candidatos estructurados
    mocker.patch("agents.scout_descubridor.extraer_candidatos_con_ia", return_value=[
        {"nombre": "Ayuntamiento de Vigo", "ciudad": "Vigo", "fuente": "[1]"},
        {"nombre": "Sala El Sol", "ciudad": "Madrid", "fuente": "[2]"} # Duplicado de lead_001
    ])
    
    # Ejecutar el descubridor de ayuntamientos en Pontevedra
    añadidos = descubrir_y_añadir_leads(region="Pontevedra", tipo="ayuntamiento", limite=5)
    
    # Debería haber añadido solo 1 lead (Ayuntamiento de Vigo), porque Sala El Sol es un duplicado
    assert añadidos == 1
    assert len(mock_db) == 4
    
    # Verificar los datos del lead añadido
    nuevo_lead = next(l for l in mock_db if l["nombre_sala"] == "Ayuntamiento de Vigo")
    assert nuevo_lead["tipo"] == "ayuntamiento"
    assert nuevo_lead["estado"] == "nuevo"
    assert nuevo_lead["ciudad"] == "Vigo"
    assert nuevo_lead["region"] == "España"  # En la Sheet, la región representa el país (España)
    assert nuevo_lead["fuente"] == "Scout Descubridor: Pontevedra"
    assert "Descubierto automáticamente" in nuevo_lead["notas"]
    assert "SIN verificar" in nuevo_lead["notas"]
