import lib.estados as estados


def test_es_transicion_valida():
    # Transiciones legales del pipeline
    assert estados.es_transicion_valida(estados.NUEVO, estados.PENDIENTE)
    assert estados.es_transicion_valida(estados.NUEVO, estados.SIN_CONTACTO)
    assert estados.es_transicion_valida(estados.APROBADO, estados.ESPERANDO)
    assert estados.es_transicion_valida(estados.ESPERANDO, estados.NEGOCIANDO)
    # Saltos ilegales
    assert not estados.es_transicion_valida(estados.NUEVO, estados.ESPERANDO)
    assert not estados.es_transicion_valida(estados.NUEVO, estados.APROBADO)
    assert not estados.es_transicion_valida(estados.DESCARTADO, estados.NUEVO)


def test_transicionar_valida_escribe(mock_db):
    """Una transición válida se escribe en la Sheet (mock) y actualiza el estado del lead."""
    lead = next(l for l in mock_db if l["id"] == "lead_001")  # estado 'nuevo'
    assert lead["estado"] == estados.NUEVO

    ok = estados.transicionar(lead, estados.PENDIENTE)

    assert ok is True
    assert lead["estado"] == estados.PENDIENTE


def test_transicionar_invalida_no_escribe(mock_db):
    """Una transición inválida se ignora: devuelve False y no toca el estado."""
    lead = next(l for l in mock_db if l["id"] == "lead_001")  # estado 'nuevo'

    ok = estados.transicionar(lead, estados.ESPERANDO)  # nuevo -> esperando es ilegal

    assert ok is False
    assert lead["estado"] == estados.NUEVO


def test_transicionar_estado_desconocido_no_escribe(mock_db):
    """Un estado que no existe en el grafo se rechaza."""
    lead = next(l for l in mock_db if l["id"] == "lead_001")

    ok = estados.transicionar(lead, "estado_inventado")

    assert ok is False
    assert lead["estado"] == estados.NUEVO
