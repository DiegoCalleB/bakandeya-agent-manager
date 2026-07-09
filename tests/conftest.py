import pytest

@pytest.fixture
def mock_db():
    """
    Simula una base de datos en memoria representando las filas de la hoja de Google Sheets.
    """
    return [
        {
            "id": "lead_001",
            "nombre_sala": "Sala El Sol",
            "ciudad": "Madrid",
            "region": "Madrid",
            "aforo": 300,
            "genero": "Afrobeat / Fusión",
            "tipo": "",
            "email_contacto": "conciertos@salaelsol.com",
            "fuente": "Semilla Manual",
            "estado": "nuevo",
            "pitch_generado": "",
            "fecha_envio": "",
            "fecha_ultima_respuesta": "",
            "notas": ""
        },
        {
            "id": "lead_002",
            "nombre_sala": "Apolo",
            "ciudad": "Barcelona",
            "region": "Cataluña",
            "aforo": 1000,
            "genero": "Fusión / Rock",
            "tipo": "sala",
            "email_contacto": "programacion@sala-apolo.com",
            "fuente": "Semilla Manual",
            "estado": "pendiente_aprobacion",
            "pitch_generado": "Pitch original de prueba",
            "fecha_envio": "",
            "fecha_ultima_respuesta": "",
            "notas": ""
        },
        {
            "id": "lead_003",
            "nombre_sala": "Sala Karma",
            "ciudad": "Pontevedra",
            "region": "Galicia",
            "aforo": 250,
            "genero": "Afrobeat",
            "tipo": "",
            "email_contacto": "",  # Lead inválido para enviar porque no tiene email verificado
            "fuente": "Semilla Manual",
            "estado": "nuevo",
            "pitch_generado": "",
            "fecha_envio": "",
            "fecha_ultima_respuesta": "",
            "notas": ""
        }
    ]

@pytest.fixture(autouse=True)
def mock_sheets_api(mocker, mock_db):
    """
    Mockea automáticamente todas las funciones del módulo lib.sheets para usar la base de datos en memoria.
    """
    def mock_obtener_leads(estado=None):
        if estado:
            return [row for row in mock_db if row["estado"] == estado]
        return mock_db

    def mock_actualizar_estado_lead(lead_id, nuevo_estado, pitch=None, notas=None):
        for row in mock_db:
            if str(row["id"]) == str(lead_id):
                row["estado"] = nuevo_estado
                if pitch is not None:
                    row["pitch_generado"] = pitch
                if notas is not None:
                    row["notas"] = notas
                return True
        return False

    def mock_actualizar_datos_lead(lead_id, datos_dict):
        for row in mock_db:
            if str(row["id"]) == str(lead_id):
                for key, val in datos_dict.items():
                    if val is not None:
                        row[key] = val
                return True
        return False

    def mock_crear_leads(lista_datos_dict):
        for datos_dict in lista_datos_dict:
            row_dict = {
                "id": datos_dict.get("id", ""),
                "nombre_sala": datos_dict.get("nombre_sala", ""),
                "ciudad": datos_dict.get("ciudad", ""),
                "region": datos_dict.get("region", ""),
                "aforo": datos_dict.get("aforo", 0),
                "genero": datos_dict.get("genero", ""),
                "tipo": datos_dict.get("tipo", ""),
                "email_contacto": datos_dict.get("email_contacto", ""),
                "fuente": datos_dict.get("fuente", ""),
                "estado": datos_dict.get("estado", "nuevo"),
                "pitch_generado": datos_dict.get("pitch_generado", ""),
                "fecha_envio": datos_dict.get("fecha_envio", ""),
                "fecha_ultima_respuesta": datos_dict.get("fecha_ultima_respuesta", ""),
                "notas": datos_dict.get("notas", "")
            }
            mock_db.append(row_dict)
        return True

    mocker.patch("lib.sheets.obtener_leads", side_effect=mock_obtener_leads)
    mocker.patch("lib.sheets.actualizar_estado_lead", side_effect=mock_actualizar_estado_lead)
    mocker.patch("lib.sheets.actualizar_datos_lead", side_effect=mock_actualizar_datos_lead)
    mocker.patch("lib.sheets.crear_leads", side_effect=mock_crear_leads)
    mocker.patch("lib.sheets.obtener_cliente_sheets", return_value=None)
    
    return mock_db

@pytest.fixture
def emails_enviados():
    """
    Lista mutable en memoria para acumular los emails enviados por el mock de Gmail.
    """
    return []

@pytest.fixture(autouse=True)
def mock_gmail_api(mocker, emails_enviados):
    """
    Mockea automáticamente el envío y la lectura de correos en lib.gmail_client.
    """
    def mock_enviar_email(destinatario, asunto, cuerpo_texto):
        emails_enviados.append({
            "destinatario": destinatario,
            "asunto": asunto,
            "cuerpo": cuerpo_texto
        })
        return {"id": f"msg_mock_{len(emails_enviados)}"}

    def mock_leer_respuestas(query="is:unread"):
        return [
            {
                "id": "reply_mock_001",
                "remitente": "conciertos@salaelsol.com",
                "asunto": "Re: Propuesta de concierto: Bakandeya en Sala El Sol",
                "fecha": "Thu, 9 Jul 2026 10:00:00 +0200",
                "cuerpo": "Hola, nos interesa vuestra propuesta de directo. ¿Qué caché manejáis y qué fechas tenéis?"
            }
        ]

    mocker.patch("lib.gmail_client.enviar_email", side_effect=mock_enviar_email)
    mocker.patch("lib.gmail_client.leer_respuestas", side_effect=mock_leer_respuestas)
    mocker.patch("lib.gmail_client.obtener_servicio_gmail", return_value=None)
    
    return emails_enviados

@pytest.fixture(autouse=True)
def mock_claude_api(mocker):
    """
    Mockea automáticamente las llamadas de generación de texto del módulo lib.claude_client.
    """
    def mock_generar_texto(prompt, model=None, system_prompt=None, max_tokens=None):
        prompt_lower = prompt.lower() if prompt else ""
        system_lower = system_prompt.lower() if system_prompt else ""
        
        if "redactor" in system_lower or "pitch" in prompt_lower:
            return "PITCH GENERADO MOCK: Hola, nos gustaría presentar a Bakandeya en vuestra sala."
        if "lector" in system_lower or "clasifica" in prompt_lower or "respuesta" in prompt_lower:
            return "interesado"
            
        return "Respuesta simulada genérica de Claude."

    mocker.patch("lib.claude_client.generar_texto", side_effect=mock_generar_texto)
    mocker.patch("lib.claude_client.obtener_cliente_claude", return_value=None)

@pytest.fixture(autouse=True)
def mock_gemini_api(mocker):
    """
    Mockea automáticamente las llamadas de generación de texto del módulo lib.gemini_client.
    """
    def mock_generar_texto_gemini(prompt, model_name=None, system_instruction=None, temperature=None):
        prompt_lower = prompt.lower() if prompt else ""
        system_lower = system_instruction.lower() if system_instruction else ""
        
        # El redactor se evalúa primero para evitar conflictos con la palabra 'email' en su prompt
        if "redactor" in system_lower or "pitch" in prompt_lower or "propuesta" in prompt_lower:
            return "PITCH GENERADO MOCK: Hola, nos gustaría presentar a Bakandeya en vuestra sala."
        # El scout devuelve un JSON para extraer los datos
        if "contacto" in prompt_lower or "email" in prompt_lower:
            return '{"email": "info@salakarma.es", "telefono": "+34 986 112233", "instagram": "@salakarma", "aforo": 250}'
        return "Respuesta simulada genérica de Gemini."

    mocker.patch("lib.gemini_client.generar_texto_gemini", side_effect=mock_generar_texto_gemini)
