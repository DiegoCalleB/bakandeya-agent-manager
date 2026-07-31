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
    assert normalizar_nombre("Discoteca Mae West") == "maewest"


def test_normalizar_tipo():
    """
    Verifica que las variaciones de tipos (plurales, sinónimos) se mapeen correctamente.
    """
    from agents.scout_descubridor import normalizar_tipo, obtener_queries_busqueda
    assert normalizar_tipo("discotecas") == "discoteca"
    assert normalizar_tipo("festivales") == "festival"
    assert normalizar_tipo("ayuntamientos") == "ayuntamiento"
    assert normalizar_tipo("salas") == "sala"
    assert normalizar_tipo("clubes") == "discoteca"
    assert normalizar_tipo("pubs") == "pub"

    queries = obtener_queries_busqueda("discoteca", "Granada")
    assert any("discotecas" in q for q in queries)
    assert any("España" in q for q in queries)


def test_es_duplicado_difuso():
    """
    Verifica que la deduplicación difusa (fuzzy matching y subcadenas) detecte nombres casi idénticos.
    """
    from agents.scout_descubridor import normalizar_nombre, es_duplicado_difuso
    existentes = {
        normalizar_nombre("Sala El Sol"),
        normalizar_nombre("Apolo Barcelona"),
        normalizar_nombre("Sala Karma Pontevedra")
    }

    # Coincidencia exacta
    es_dup, _ = es_duplicado_difuso("Sala El Sol", existentes)
    assert es_dup is True

    # Coincidencia difusa / subcadena ("Sala El Sol de Madrid" vs "Sala El Sol")
    es_dup, _ = es_duplicado_difuso("Sala El Sol de Madrid", existentes)
    assert es_dup is True

    # Recinto distinto -> no duplicado
    es_dup, _ = es_duplicado_difuso("Discoteca Mae West", existentes)
    assert es_dup is False


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
    assert nuevo_lead["region"] == "Pontevedra"  # En la Sheet, la región almacena la provincia solicitada
    assert nuevo_lead["fuente"] == "Scout Descubridor: Pontevedra"
    assert "Descubierto automáticamente" in nuevo_lead["notas"]
    assert "SIN verificar" in nuevo_lead["notas"]


def test_descubrir_multitipo(mocker, mock_db):
    """
    Verifica que se puedan solicitar múltiples tipos (ej. discotecas y festivales)
    y se busque para cada uno de ellos de forma independiente con desambiguación geográfica.
    """
    queries_buscadas = []

    def mock_busqueda(query, max_results=10):
        queries_buscadas.append(query)
        return [{"title": "Snippet mock", "href": "https://example.com", "body": "Body mock"}]

    def mock_extraer(resultados, tipo, region):
        if tipo == "discoteca":
            return [{"nombre": "Discoteca Industrial Copera", "ciudad": "Granada", "fuente": "[1]"}]
        elif tipo == "festival":
            return [{"nombre": "Festival Zaidín Rock", "ciudad": "Granada", "fuente": "[1]"}]
        return []

    mocker.patch("agents.scout_descubridor.buscar_duckduckgo", side_effect=mock_busqueda)
    mocker.patch("agents.scout_descubridor.extraer_candidatos_con_ia", side_effect=mock_extraer)

    añadidos = descubrir_y_añadir_leads(region="Granada", tipo="discotecas,festivales", limite=5)

    assert añadidos == 2
    # Verificar que buscó específicamente ambos tipos en DuckDuckGo incluyendo 'España'
    assert any("discotecas" in q and "España" in q for q in queries_buscadas)
    assert any("festivales" in q and "España" in q for q in queries_buscadas)

    lead_disco = next(l for l in mock_db if l["nombre_sala"] == "Discoteca Industrial Copera")
    assert lead_disco["tipo"] == "discoteca"
    assert lead_disco["region"] == "Granada"

    lead_fest = next(l for l in mock_db if l["nombre_sala"] == "Festival Zaidín Rock")
    assert lead_fest["tipo"] == "festival"
    assert lead_fest["region"] == "Granada"


