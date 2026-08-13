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

@pytest.fixture
def hilos_registrados():
    """
    Lista mutable en memoria para acumular los mensajes registrados vía sheets.registrar_mensaje_hilo.
    """
    return []

@pytest.fixture
def mock_db_medios():
    """
    Simula la hoja 'medios' (radio/TV/prensa/canales), vacía por defecto — cada test que la
    necesite la puebla explícitamente.
    """
    return []

@pytest.fixture(autouse=True)
def mock_sheets_api(mocker, mock_db, mock_db_medios, hilos_registrados):
    """
    Mockea automáticamente todas las funciones del módulo lib.sheets para usar bases de datos
    en memoria. `nombre_hoja` enruta entre 'leads' (mock_db) y 'medios' (mock_db_medios).
    """
    def _hoja(nombre_hoja):
        return mock_db_medios if nombre_hoja == "medios_scout" else mock_db

    def mock_obtener_leads(estado=None, nombre_hoja="leads", **kwargs):
        datos = _hoja(nombre_hoja)
        if estado:
            return [row for row in datos if row["estado"] == estado]
        return datos

    def mock_actualizar_estado_lead(lead_id, nuevo_estado, pitch=None, notas=None, nombre_hoja="leads", **kwargs):
        for row in _hoja(nombre_hoja):
            if str(row["id"]) == str(lead_id):
                row["estado"] = nuevo_estado
                if pitch is not None:
                    row["pitch_generado"] = pitch
                if notas is not None:
                    row["notas"] = notas
                return True
        return False

    def mock_actualizar_datos_lead(lead_id, datos_dict, nombre_hoja="leads", **kwargs):
        for row in _hoja(nombre_hoja):
            if str(row["id"]) == str(lead_id):
                for key, val in datos_dict.items():
                    if val is not None:
                        row[key] = val
                return True
        return False

    def mock_crear_leads(lista_datos_dict, nombre_hoja="leads", **kwargs):
        destino = _hoja(nombre_hoja)
        for datos_dict in lista_datos_dict:
            if nombre_hoja == "medios_scout":
                row_dict = {
                    "id": datos_dict.get("id", ""),
                    "nombre_medio": datos_dict.get("nombre_medio", ""),
                    "tipo_medio": datos_dict.get("tipo_medio", ""),
                    "ciudad": datos_dict.get("ciudad", ""),
                    "alcance": datos_dict.get("alcance", ""),
                    "email_contacto": datos_dict.get("email_contacto", ""),
                    "enfoque_editorial": datos_dict.get("enfoque_editorial", ""),
                    "fuente": datos_dict.get("fuente", ""),
                    "estado": datos_dict.get("estado", "nuevo"),
                    "pitch_generado": datos_dict.get("pitch_generado", ""),
                    "fecha_envio": datos_dict.get("fecha_envio", ""),
                    "fecha_ultima_respuesta": datos_dict.get("fecha_ultima_respuesta", ""),
                    "notas": datos_dict.get("notas", ""),
                    "band_id": datos_dict.get("band_id", "")
                }
            else:
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
                    "notas": datos_dict.get("notas", ""),
                    "band_id": datos_dict.get("band_id", "")
                }
            destino.append(row_dict)
        return True

    def mock_registrar_mensaje_hilo(lead_id, nombre_sala, fecha, remitente, remitente_nombre, asunto, mensaje, mensaje_id=None):
        hilos_registrados.append({
            "lead_id": lead_id, "nombre_sala": nombre_sala, "fecha": fecha,
            "remitente": remitente, "remitente_nombre": remitente_nombre,
            "asunto": asunto, "mensaje": mensaje, "mensaje_id": mensaje_id
        })
        return True

    mocker.patch("lib.sheets.obtener_leads", side_effect=mock_obtener_leads)
    mocker.patch("lib.sheets.actualizar_estado_lead", side_effect=mock_actualizar_estado_lead)
    mocker.patch("lib.sheets.actualizar_datos_lead", side_effect=mock_actualizar_datos_lead)
    mocker.patch("lib.sheets.crear_leads", side_effect=mock_crear_leads)
    mocker.patch("lib.sheets.registrar_mensaje_hilo", side_effect=mock_registrar_mensaje_hilo)
    mocker.patch("lib.sheets.obtener_cliente_sheets", return_value=None)

    # Multi-tenant: en los tests no hay 'registro_bandas'/'dossier_epk'/'config_autonomia' reales
    # (esas hojas las gestiona Bakandeya_AIStudio_Application). Mockeamos el punto de lectura
    # común (_leer_filas_hoja_externa) para que devuelva [] limpiamente en vez de que cada test
    # dispare el camino de excepción de obtener_cliente_sheets() -> None. Con [] cada función
    # cae en su fallback real (una única banda "Bakandeya" activa, EPK vacío que se enriquece
    # con el JSON estático, autonomía con los valores por defecto) — el mismo comportamiento
    # single-tenant que tenían los agentes antes de multi-tenant.
    mocker.patch("lib.sheets._leer_filas_hoja_externa", return_value=[])

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
    def mock_enviar_email(destinatario, asunto, cuerpo_texto, ruta_adjunto=None, epk=None):
        emails_enviados.append({
            "destinatario": destinatario,
            "asunto": asunto,
            "cuerpo": cuerpo_texto,
            "ruta_adjunto": ruta_adjunto
        })
        return {"id": f"msg_mock_{len(emails_enviados)}"}

    def mock_crear_borrador(destinatario, asunto, cuerpo_texto, thread_id=None, in_reply_to=None, ruta_adjunto=None, epk=None):
        emails_enviados.append({
            "destinatario": destinatario,
            "asunto": asunto,
            "cuerpo": cuerpo_texto,
            "ruta_adjunto": ruta_adjunto
        })
        return {"id": f"draft_mock_{len(emails_enviados)}"}

    def mock_leer_respuestas(query="is:unread", band_id=None):
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
    mocker.patch("lib.gmail_client.crear_borrador", side_effect=mock_crear_borrador)
    mocker.patch("lib.gmail_client.leer_respuestas", side_effect=mock_leer_respuestas)
    mocker.patch("lib.gmail_client.marcar_como_leido", return_value=True)
    mocker.patch("lib.gmail_client.obtener_servicio_gmail", return_value=None)
    mocker.patch("lib.gmail_client.es_modo_simulado", return_value=True)
    # Multi-tenant: enviador.py verifica que la cuenta de Gmail conectada coincide con el email
    # oficial de la banda en su EPK antes de enviar. En tests simulamos que SÍ coincide (el email
    # de contacto de band-bakandeya en data/epk_bakandeya.json) para no bloquear los flujos
    # existentes; un test dedicado cubre el caso de bloqueo por email equivocado.
    mocker.patch("lib.gmail_client.obtener_email_conectado", return_value="diego.delacalleb@gmail.com")

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
def mock_google_places(mocker):
    """
    Los tests NUNCA deben llamar a la Google Places API real — ni siquiera si el .env local
    del desarrollador tiene una GOOGLE_PLACES_API_KEY de verdad configurada (para probarlo en
    local a mano). Sin este mock, un test run haría llamadas reales y no deterministas (y
    gastaría cuota real) en cuanto esa variable exista. Por defecto simulamos que Places no
    está configurado, igual que en un entorno sin la key; un test dedicado a la integración
    sobrescribe esto explícitamente.
    """
    mocker.patch("lib.google_places.esta_configurado", return_value=False)
    mocker.patch("lib.google_places.buscar_lugar", return_value=None)


@pytest.fixture(autouse=True)
def mock_gemini_api(mocker):
    """
    Mockea automáticamente las llamadas de generación de texto del módulo lib.gemini_client.
    """
    def mock_generar_texto_gemini(prompt, model_name=None, system_instruction=None, temperature=None, forzar_json=False):
        prompt_lower = prompt.lower() if prompt else ""
        system_lower = system_instruction.lower() if system_instruction else ""
        
        # 1. El redactor tiene prioridad cuando se trata de redactar un pitch
        if "redactor" in system_lower or "pitch" in prompt_lower or "propuesta artística" in prompt_lower or "propuesta de concierto" in prompt_lower:
            return "PITCH GENERADO MOCK: Hola, nos gustaría presentar a Bakandeya en vuestra sala."
        # 2. El clasificador de respuestas (lector de bandeja / responder)
        if "lector" in system_lower or "clasifica" in prompt_lower or "categor" in prompt_lower or "analiza la siguiente respuesta" in prompt_lower:
            if forzar_json:
                return '{"categoria": "interesado", "fecha_propuesta": "15 de noviembre", "oferta_economica": "80% taquilla", "resumen": "Interesados en la propuesta"}'
            return "interesado"
        # 3. El scout devuelve un JSON para extraer los datos
        if "contacto" in prompt_lower or "email" in prompt_lower:
            return '{"email": "info@salakarma.es", "telefono": "+34 986 112233", "instagram": "@salakarma", "aforo": 250}'
        if forzar_json:
            return '{}'
        return "Respuesta simulada genérica de Gemini."

    mocker.patch("lib.gemini_client.generar_texto_gemini", side_effect=mock_generar_texto_gemini)
