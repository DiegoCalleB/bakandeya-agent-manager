import pytest
from agents.redactor import procesar_nuevos_leads
from agents.enviador import enviar_leads_aprobados, parsear_pitch
from agents.lector_bandeja import procesar_bandeja_entrada


def test_parsear_pitch_extrae_asunto():
    """El asunto generado (ASUNTO: ...) debe ir al asunto real y NO quedarse en el cuerpo."""
    pitch = "ASUNTO: Bakandeya en La Sala\n\n¡Hola equipo!\n\nOs escribimos porque..."
    asunto, cuerpo = parsear_pitch(pitch, "La Sala")
    assert asunto == "Bakandeya en La Sala"
    assert cuerpo.startswith("¡Hola equipo!")
    assert "ASUNTO:" not in cuerpo  # el bug: ya no se cuela en el cuerpo


def test_parsear_pitch_sin_marcador_usa_generico():
    """Si el pitch no trae marcador ASUNTO:, se degrada a asunto genérico + cuerpo completo."""
    pitch = "Hola, os escribo para proponer un concierto."
    asunto, cuerpo = parsear_pitch(pitch, "Mae West")
    assert asunto == "Propuesta de concierto: Bakandeya en Mae West"
    assert cuerpo == pitch

def test_redactor_flow(mock_sheets_api):
    """
    Verifica que el redactor procese leads en estado 'nuevo', genere pitch
    y los pase a 'pendiente_aprobacion' solo si tienen email.
    """
    # Inicialmente hay 2 leads 'nuevo' (lead_001 con email y lead_003 sin email)
    leads_nuevos = [l for l in mock_sheets_api if l["estado"] == "nuevo"]
    assert len(leads_nuevos) == 2
    
    procesados = procesar_nuevos_leads()
    assert procesados == 1
    
    # Lead 001 con email debe cambiar a 'pendiente_aprobacion' y tener pitch
    lead_001 = next(l for l in mock_sheets_api if l["id"] == "lead_001")
    assert lead_001["estado"] == "pendiente_aprobacion"
    assert "PITCH GENERADO MOCK" in lead_001["pitch_generado"]
    
    # Lead 003 sin email debe seguir en 'nuevo'
    lead_003 = next(l for l in mock_sheets_api if l["id"] == "lead_003")
    assert lead_003["estado"] == "nuevo"
    assert lead_003["pitch_generado"] == ""

def test_enviador_flow(mock_sheets_api, emails_enviados):
    """
    Verifica que el enviador tome leads en estado 'aprobado', envíe el email
    y los pase a 'esperando_respuesta'.
    """
    # Cambiamos manualmente el estado de lead_001 a 'aprobado' para simular aprobación humana
    lead_001 = next(l for l in mock_sheets_api if l["id"] == "lead_001")
    lead_001["estado"] = "aprobado"
    lead_001["pitch_generado"] = "Pitch de prueba aprobado"
    
    enviados = enviar_leads_aprobados()
    assert enviados == 1
    
    # Comprobar estado final y email en mock
    assert lead_001["estado"] == "esperando_respuesta"
    assert len(emails_enviados) == 1
    assert emails_enviados[0]["destinatario"] == "conciertos@salaelsol.com"
    assert emails_enviados[0]["cuerpo"] == "Pitch de prueba aprobado"

def test_lector_bandeja_flow(mock_sheets_api):
    """
    Verifica que el lector procese respuestas entrantes de Gmail, las
    asocie al lead esperando y actualice el estado a 'interesado'/'negociando'.
    """
    # Preparamos lead_001 en estado de espera
    lead_001 = next(l for l in mock_sheets_api if l["id"] == "lead_001")
    lead_001["estado"] = "esperando_respuesta"
    lead_001["email_contacto"] = "conciertos@salaelsol.com"
    
    procesadas = procesar_bandeja_entrada()
    assert procesadas == 1
    
    # Debería haber cambiado a 'interesado' según el mock de Claude
    assert lead_001["estado"] == "interesado"
    assert "Respuesta recibida" in lead_001["notas"]

def test_redactor_flow_tipos(mocker, mock_sheets_api):
    """
    Verifica que el redactor genere pitches diferenciados según el tipo de lead.
    """
    # Preparamos un lead de tipo ayuntamiento
    lead_ayto = next(l for l in mock_sheets_api if l["id"] == "lead_001")
    lead_ayto["tipo"] = "ayuntamiento"
    lead_ayto["estado"] = "nuevo"
    
    # Mockear generar_texto_gemini para capturar el system_instruction
    captured_calls = []
    def mock_generar(prompt, model_name=None, system_instruction=None, temperature=None):
        captured_calls.append((prompt, system_instruction))
        return "PITCH AYTO MOCK: Fiestas Patronales"
        
    mocker.patch("lib.gemini_client.generar_texto_gemini", side_effect=mock_generar)
    
    procesados = procesar_nuevos_leads()
    assert procesados == 1
    
    assert len(captured_calls) == 1
    prompt, system = captured_calls[0]
    assert "ayuntamiento" in prompt.lower() or "programación" in prompt.lower()
    assert "concejalía de festejos" in system.lower() or "caché" in system.lower()
    assert lead_ayto["estado"] == "pendiente_aprobacion"
    assert lead_ayto["pitch_generado"] == "PITCH AYTO MOCK: Fiestas Patronales"
