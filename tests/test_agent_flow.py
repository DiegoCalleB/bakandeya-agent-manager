import pytest
from agents.redactor import procesar_nuevos_leads, procesar_nuevos_medios, ENFOQUES_PRENSA
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

def test_enviador_flow(mock_sheets_api, emails_enviados, hilos_registrados):
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

    # El envío también debe quedar registrado en el hilo de conversación del lead
    assert len(hilos_registrados) == 1
    assert hilos_registrados[0]["lead_id"] == "lead_001"
    assert hilos_registrados[0]["remitente"] == "banda"
    assert hilos_registrados[0]["mensaje"] == "Pitch de prueba aprobado"

def test_enviador_bloquea_si_el_email_conectado_no_es_el_oficial(mocker, mock_sheets_api, emails_enviados):
    """
    Multi-tenant: si la cuenta de Gmail conectada para una banda no coincide con su email
    oficial (EPK), NO debe enviarse ningún borrador — mejor no enviar que hacerlo desde la
    mailbox equivocada.
    """
    mocker.patch("lib.gmail_client.obtener_email_conectado", return_value="cuenta-equivocada@gmail.com")

    lead_001 = next(l for l in mock_sheets_api if l["id"] == "lead_001")
    lead_001["estado"] = "aprobado"
    lead_001["pitch_generado"] = "Pitch de prueba aprobado"

    enviados = enviar_leads_aprobados()
    assert enviados == 0
    assert len(emails_enviados) == 0
    assert lead_001["estado"] == "aprobado"  # no debe haber transicionado


def test_lector_bandeja_flow(mock_sheets_api, hilos_registrados):
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

    # La respuesta recibida también debe quedar registrada en el hilo, con remitente 'sala'
    assert len(hilos_registrados) == 1
    assert hilos_registrados[0]["lead_id"] == "lead_001"
    assert hilos_registrados[0]["remitente"] == "sala"
    assert hilos_registrados[0]["mensaje_id"] == "reply_mock_001"

def test_redactor_medios_flow(mocker, mock_db_medios):
    """
    Verifica que el redactor genere pitches de PRENSA (no de booking) para la hoja 'medios':
    usa un ángulo de ENFOQUES_PRENSA (no ENFOQUES_ESTILO) y encuadra el objetivo como
    cobertura editorial, no como propuesta de contratación de conciertos.
    """
    mock_db_medios.append({
        "id": "medio_001",
        "nombre_medio": "Radio Fusión FM",
        "tipo_medio": "radio",
        "ciudad": "Madrid",
        "alcance": "regional",
        "email_contacto": "redaccion@radiofusion.es",
        "enfoque_editorial": "",
        "fuente": "Semilla Manual",
        "estado": "nuevo",
        "pitch_generado": "",
        "fecha_envio": "",
        "fecha_ultima_respuesta": "",
        "notas": ""
    })

    captured = []
    def mock_generar(prompt, model_name=None, system_instruction=None, temperature=None):
        captured.append((prompt, system_instruction))
        return "ASUNTO: Bakandeya para Radio Fusión FM\n\nHola equipo,\n\nOs escribimos..."

    mocker.patch("lib.gemini_client.generar_texto_gemini", side_effect=mock_generar)

    procesados = procesar_nuevos_medios()
    assert procesados == 1

    medio = mock_db_medios[0]
    assert medio["estado"] == "pendiente_aprobacion"
    assert "ASUNTO:" in medio["pitch_generado"]

    prompt, system = captured[0]
    assert "cobertura editorial" in system.lower()
    assert any(nombre_enfoque in system for nombre_enfoque, _ in ENFOQUES_PRENSA)
    assert "Medio:" in prompt


def test_enviador_medios_flow(mock_db_medios, emails_enviados, hilos_registrados):
    """
    Verifica que el enviador procese la hoja 'medios' cuando se le pide explícitamente
    (nombre_hoja='medios'), sin tocar 'leads'.
    """
    mock_db_medios.append({
        "id": "medio_002",
        "nombre_medio": "El Diario Cultural",
        "tipo_medio": "prensa",
        "ciudad": "Barcelona",
        "alcance": "nacional",
        "email_contacto": "cultura@eldiariocultural.example",
        "enfoque_editorial": "",
        "fuente": "Semilla Manual",
        "estado": "aprobado",
        "pitch_generado": "ASUNTO: Bakandeya, fusión con conciencia\n\nHola equipo,\n\nCuerpo de prueba.",
        "fecha_envio": "",
        "fecha_ultima_respuesta": "",
        "notas": ""
    })

    enviados = enviar_leads_aprobados(nombre_hoja="medios_scout")
    assert enviados == 1

    medio = mock_db_medios[0]
    assert medio["estado"] == "esperando_respuesta"
    assert emails_enviados[0]["destinatario"] == "cultura@eldiariocultural.example"
    assert hilos_registrados[0]["lead_id"] == "medio_002"
    assert hilos_registrados[0]["remitente"] == "banda"


def test_lector_bandeja_medios_flow(mocker, mock_db_medios, hilos_registrados):
    """
    Verifica que el lector también empareje respuestas contra la hoja 'medios' (no solo
    'leads') y actualice esa fila, sin tocar la hoja de leads.
    """
    mock_db_medios.append({
        "id": "medio_003",
        "nombre_medio": "Podcast Ritmos",
        "tipo_medio": "podcast",
        "ciudad": "",
        "alcance": "nacional",
        "email_contacto": "hola@podcastritmos.example",
        "enfoque_editorial": "",
        "fuente": "Semilla Manual",
        "estado": "esperando_respuesta",
        "pitch_generado": "",
        "fecha_envio": "",
        "fecha_ultima_respuesta": "",
        "notas": ""
    })

    def mock_leer_respuestas(query="is:unread", band_id=None):
        return [{
            "id": "reply_medio_001",
            "remitente": "Ana <hola@podcastritmos.example>",
            "asunto": "Re: Bakandeya",
            "fecha": "Thu, 9 Jul 2026 10:00:00 +0200",
            "cuerpo": "¡Nos encantaría entrevistaros para el podcast!"
        }]
    mocker.patch("lib.gmail_client.leer_respuestas", side_effect=mock_leer_respuestas)

    procesadas = procesar_bandeja_entrada()
    assert procesadas == 1

    medio = mock_db_medios[0]
    assert medio["estado"] in ("interesado", "negociando")
    assert hilos_registrados[0]["lead_id"] == "medio_003"
    assert hilos_registrados[0]["mensaje_id"] == "reply_medio_001"


def test_redactor_flow_filtra_por_banda(mock_sheets_api):
    """
    Multi-tenant: un lead 'nuevo' con band_id de OTRA banda no debe procesarse cuando se pide
    la banda por defecto (band-bakandeya) — evita que un pitch de una banda se cuele mezclado
    con los leads de otra que comparten la misma Google Sheet.
    """
    mock_sheets_api.append({
        "id": "lead_otra_banda",
        "nombre_sala": "Sala de Otra Banda",
        "ciudad": "Valencia",
        "region": "Valencia",
        "aforo": 200,
        "genero": "Rock",
        "tipo": "",
        "email_contacto": "booking@otrasala.example",
        "fuente": "Semilla Manual",
        "estado": "nuevo",
        "pitch_generado": "",
        "fecha_envio": "",
        "fecha_ultima_respuesta": "",
        "notas": "",
        "band_id": "band-otra"
    })

    procesados = procesar_nuevos_leads()
    # Solo lead_001 (band-bakandeya implícito) se procesa; lead_otra_banda se ignora.
    assert procesados == 1

    lead_otra = next(l for l in mock_sheets_api if l["id"] == "lead_otra_banda")
    assert lead_otra["estado"] == "nuevo"
    assert lead_otra["pitch_generado"] == ""


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
