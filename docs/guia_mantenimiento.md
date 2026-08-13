# Guía de mantenimiento — Bakandeya Agent Manager

Documento de referencia técnica **completo**: qué hace cada archivo, función por función, y cómo
hacer los cambios habituales. El objetivo es que puedas mantener y modificar el sistema sin
depender de una IA. Si `docs/como_funciona.md` es la introducción conceptual (léela primero si no
lo has hecho), este documento es el manual de taller.

> **Convención de esta guía:** cada vez que veas `archivo.py:42`, es la línea aproximada en ese
> archivo. Las líneas se mueven con el tiempo — si no coincide exactamente, busca el nombre de la
> función citada.

---

## 1. Mapa completo del repo

```
Bakandeya_Management/
├── CLAUDE.md                    # Contexto del proyecto para trabajar con Claude Code
├── requirements.txt              # Dependencias Python
├── .env / .env.example           # Credenciales (real / plantilla sin valores)
├── .gitignore                    # drafts/, .venv/, credenciales, etc.
│
├── agents/                       # Los 5 agentes. Cada uno se ejecuta suelto e independiente.
│   ├── scout_descubridor.py      # Descubre entidades nuevas (nombres) por región/tipo
│   ├── scout.py                  # Enriquece leads 'nuevo' con datos de contacto
│   ├── redactor.py               # Genera el pitch (propuesta) por email
│   ├── enviador.py                # Crea el borrador/envío en Gmail
│   └── lector_bandeja.py         # Clasifica las respuestas recibidas
│
├── lib/                          # Infraestructura compartida — "no reinventar la rueda"
│   ├── __init__.py               # Bootstrap: fuerza el uso del almacén de certificados del SO
│   ├── estados.py                # La máquina de estados del pipeline (fuente única de verdad)
│   ├── busqueda.py               # Búsqueda DuckDuckGo compartida (scout + descubridor)
│   ├── sheets.py                 # Toda la lectura/escritura de la Google Sheet
│   ├── gemini_client.py          # Wrapper de la API de Gemini (extracción/clasificación)
│   ├── claude_client.py          # Wrapper de la API de Claude (sin usar aún en producción)
│   ├── gmail_client.py           # Envío/lectura de Gmail (real y modo simulado)
│   └── telegram.py               # Notificaciones a Telegram (con mock si faltan credenciales)
│
├── data/
│   └── epk_bakandeya.json        # Bio, enlaces, rider técnico y caché de la banda
│
├── drafts/                       # Generado en modo simulado (ignorado por git — tiene datos reales)
│   ├── borrador_*.html           # Emails simulados que "habría enviado" el enviador
│   └── respuestas_simuladas.json # Respuestas de prueba que "lee" el lector_bandeja
│
├── scripts/                      # Utilidades de mantenimiento, NO forman parte del pipeline
│   ├── git-hooks/pre-commit      # Corre pytest antes de cada commit
│   ├── install_hooks.py          # Instala el hook anterior en .git/hooks/
│   ├── test_sheets_connection.py # Diagnóstico: ¿está bien configurada la conexión a Sheets?
│   ├── setup_sheet_columns.py    # Crea las columnas telefono/website/instagram si faltan
│   ├── import_excel_to_sheets.py # Importación puntual de datos desde un Excel legado
│   └── inspect_excel.py          # Inspecciona un Excel antes de importarlo
│
├── tests/                        # pytest — nunca tocan la red, todo mockeado
│   ├── conftest.py               # Fixtures autouse: mock_db + mocks de Sheets/Gmail/IA
│   ├── test_agent_flow.py        # Flujo redactor → enviador → lector
│   ├── test_scout.py             # Scout enriquecedor
│   ├── test_scout_descubridor.py # Scout descubridor
│   └── test_estados.py           # La máquina de estados
│
├── .claude/skills/                # Guías que Claude Code carga automáticamente al tocar un área
│   ├── pitch-generation/          # Pautas de tono/estructura para el redactor
│   ├── scout-descubrimiento/      # Reglas anti-alucinación para los scouts
│   └── test-harness/              # Cómo correr los tests sin tocar APIs reales
│
└── docs/
    ├── como_funciona.md           # Introducción conceptual (léela primero)
    └── guia_mantenimiento.md      # Este documento
```

---

## 2. El esquema de datos — la hoja `leads`

Cada fila es un lead. Estas son las columnas (algunas se crean dinámicamente la primera vez que
un agente las necesita, ver `lib/sheets.py` sección 4):

| Columna | Tipo | Quién la escribe | Notas |
|---|---|---|---|
| `id` | string | scout_descubridor / manual | `lead_xxxxx` (uuid corto) |
| `nombre_sala` | string | scout_descubridor / manual | Nombre de la entidad |
| `ciudad` | string | scout_descubridor / manual | |
| `region` | string | scout_descubridor / manual | Provincia/región |
| `aforo` | int | scout | Capacidad de la sala; vacío si no aplica |
| `genero` | string | scout | Estilo musical predominante |
| `tipo` | string | scout / scout_descubridor | `sala` / `festival` / `ayuntamiento` |
| `email_contacto` | string | scout | **Debe estar verificado antes de `aprobado`** |
| `telefono` | string | scout | |
| `website` | string | scout | |
| `instagram` | string | scout | |
| `fuente` | string | scout_descubridor / manual | De dónde salió el lead (auditoría) |
| `estado` | string | todos, vía `lib/estados.py` | Ver sección 3 |
| `pitch_generado` | text | redactor | `ASUNTO: ...\n\n<cuerpo>` |
| `fecha_envio` | date | *(no implementado aún)* | |
| `fecha_ultima_respuesta` | date | *(no implementado aún)* | |
| `notas` | text | todos | Log acumulativo de lo que ha hecho cada agente |

---

## 3. La máquina de estados (`lib/estados.py`)

**Por qué existe:** antes cada agente escribía el string de estado que quisiera directamente en
la Sheet (`sheets.actualizar_estado_lead(lead_id, "nuevo")`). Eso permitía transiciones absurdas
(por ejemplo, un lead recién descubierto saltando directo a `aprobado`) y dejaba leads
**atascados**: si el scout no encontraba email, el lead se quedaba en `nuevo` para siempre y se
reintentaba en cada ejecución del cron sin salida posible.

`lib/estados.py` es ahora la **única fuente de verdad**. Define:

1. **Constantes** de cada estado (`estados.NUEVO`, `estados.PENDIENTE`, etc.) — así nunca se
   escribe un string suelto que pueda tener una errata.
2. **El grafo `TRANSICIONES`**: un diccionario `{estado_actual: {estados_destino_permitidos}}`.
3. **`transicionar(lead, nuevo_estado, notas=None, pitch=None)`**: la función que todos los
   agentes deben usar para cambiar de estado. Comprueba en el grafo si el salto es legal; si no
   lo es, **no escribe nada**, solo loguea un aviso y devuelve `False`.

### Diagrama de transiciones actual

```
antiguo ──► nuevo ──► pendiente_aprobacion ──► aprobado ──► esperando_respuesta
   │           │  ▲          │                    │               │
   │           │  │          └──► nuevo           └──► descartado ├──► interesado ──► negociando
   │           ▼  │          (pitch rechazado)                    ├──► no_interesado
   │      sin_contacto                                            └──► negociando ──► interesado
   │           │                                                                   └──► no_interesado
   └──► descartado (terminal, sin salida)
```

- **`sin_contacto`** (nuevo en esta guía): estado terminal-pero-reversible. El scout lo usa cuando,
  tras una búsqueda exhaustiva, no logra ningún email. Saca al lead del bucle de reintentos
  infinitos. Puede volver a `nuevo` si en el futuro se le añade un contacto a mano.
- **`descartado`**: terminal de verdad, no tiene salida en el grafo.
- **La barrera humana** sigue siendo el salto `pendiente_aprobacion → aprobado`: solo tú lo haces,
  a mano, en la Sheet.

### Cómo se usa desde un agente

```python
import lib.estados as estados

# lead es el dict de la fila, tal como lo devuelve sheets.obtener_leads()
ok = estados.transicionar(lead, estados.PENDIENTE, pitch="ASUNTO: ...")
if not ok:
    # la transición fue rechazada por el grafo — no se escribió nada
    ...
```

---

## 4. `lib/sheets.py` — acceso a la Google Sheet

La "base de datos" del sistema. Usa `gspread` con una **service account** (no OAuth de usuario).

| Función | Qué hace |
|---|---|
| `obtener_cliente_sheets()` | Autentica con el JSON de credenciales (`GOOGLE_APPLICATION_CREDENTIALS`). |
| `obtener_leads(estado=None)` | Lee TODAS las filas (`get_all_records()`) y filtra por estado en memoria (no hay query server-side). |
| `actualizar_datos_lead(lead_id, datos_dict)` | Busca la fila por `id`, y actualiza celda por celda. **Auto-crea columnas que falten** (`tipo`, `telefono`, `instagram`) insertándolas al lado de una columna ancla. Un valor `None` en `datos_dict` NO se escribe (pero una cadena vacía `""` sí — así se puede "vaciar" un campo). |
| `actualizar_estado_lead(lead_id, nuevo_estado, pitch=None, notas=None)` | Azúcar sobre la anterior — **no la llames directamente desde un agente nuevo, usa `estados.transicionar`**. |
| `crear_leads(lista_datos_dict)` | Inserción masiva (`append_rows`) usada por el descubridor. |

**Detalle importante:** cada llamada a estas funciones abre una conexión nueva
(`obtener_cliente_sheets()` dentro de cada función). No hay caché ni sesión persistente — está
bien para un cron que corre y termina, sería ineficiente si algún día esto corriera en bucle.

---

## 5. Los clientes de IA

### `lib/gemini_client.py` — el motor de volumen (scout, descubridor, lector)

```python
generar_texto_gemini(prompt, model_name="gemini-2.5-flash", system_instruction=None,
                      temperature=0.7, forzar_json=False, max_retries=3, delay_segundos=30)
```

- **`forzar_json=True`** activa el "JSON mode" de Gemini (`response_mime_type="application/json"`):
  el modelo está *obligado* a devolver JSON válido, sin fences ```` ```json ````. Todas las
  funciones de extracción del scout lo usan — así `json.loads(respuesta)` nunca falla por un
  carácter suelto.
- **Reintentos automáticos** solo ante error 429/quota (backoff exponencial: 30s, 60s, 120s...).
  Cualquier otro error devuelve `None` directamente, sin reintentar.
- El SDK subyacente (`google-generativeai`) está **deprecado por Google** (recomiendan migrar a
  `google-genai`). Funciona hoy; es deuda técnica pendiente.

### `lib/claude_client.py` — sin usar en producción (decisión consciente)

```python
generar_texto(prompt, model="claude-3-5-sonnet-20241022", system_prompt=None, max_tokens=2000)
```

Wrapper mínimo: **sin reintentos, sin backoff**. Si Claude devuelve un 429 o un error de red, la
función simplemente falla y devuelve `None`. Antes de usarlo en producción real (migrar el
redactor), hay que añadirle paridad con `gemini_client` (reintentos ante 429/5xx) — ver sección 9.

---

## 6. `lib/busqueda.py` — búsqueda compartida (scout + descubridor)

Antes cada scout tenía su propia copia idéntica de la función de búsqueda. Ahora:

- **`buscar_duckduckgo(query, max_results=8, pausa=True)`**: busca con la librería `ddgs`. Mete
  una pausa aleatoria (1–2,5s) antes de la petición para no disparar búsquedas en bucle (DuckDuckGo
  bloquea si detecta abuso). Devuelve `[]` ante cualquier error, nunca lanza excepción.
- **`formatear_snippets(resultados, con_url=True)`**: convierte la lista de resultados en el
  bloque de texto numerado `[1] Título: ... [2] Título: ...` que se le pega al prompt de la IA.

---

## 7. `lib/gmail_client.py` — envío/lectura de correo (real y simulado)

**Clave: `es_modo_simulado()`.** Si no existe `credentials.json` (o si `EMAIL_MODE=simulado` en
el `.env`), el cliente entra en modo simulado automáticamente — así puedes probar el pipeline
completo sin arriesgarte a enviar un email real ni necesitar el OAuth de Gmail configurado.

| Función | Modo real | Modo simulado |
|---|---|---|
| `enviar_email(...)` | Envía de verdad por la API de Gmail | Redirige a `crear_borrador` |
| `crear_borrador(destinatario, asunto, cuerpo)` | Crea un borrador real en Gmail | Escribe un archivo `drafts/borrador_<email>.html` bonito (con badge "Borrador Simulado Local") |
| `leer_respuestas(query="is:unread")` | Lee la bandeja real de Gmail | Lee `drafts/respuestas_simuladas.json` (si no existe, crea una plantilla de ejemplo) |

**Para probar el flujo completo sin credenciales:** no hagas nada especial, el modo simulado se
activa solo. Para forzarlo aunque tengas credenciales reales: `EMAIL_MODE=simulado` en `.env`.

---

## 8. Referencia de cada agente

### 8.1 `scout_descubridor.py` — encuentra nombres nuevos

```
python agents/scout_descubridor.py --region Pontevedra --tipo sala --limit 5
```

Flujo (`descubrir_y_añadir_leads`):
1. Construye una query según `--tipo` (distinta para sala/festival/ayuntamiento).
2. `buscar_duckduckgo` → hasta 10 resultados.
3. `extraer_candidatos_con_ia`: un único prompt a Gemini con **grounding obligatorio** — cada
   candidato debe traer el índice del snippet (`fuente`) que lo respalda; si la IA no puede
   señalar uno, no lo puede incluir.
4. Deduplicación: `normalizar_nombre()` quita acentos, prefijos ("Ayuntamiento de..."), sufijos y
   espacios, y compara contra los `nombre_sala` ya existentes en la Sheet.
5. Inserta en lote (`sheets.crear_leads`) con `estado=estados.NUEVO` y una nota que deja claro que
   el contacto está **sin verificar**.

**Limitación conocida:** `region` se guarda literalmente en la columna `region`, pero el país
queda hardcodeado como `"España"` en `nuevo_lead["region"]` — revisar si algún día se necesita
guardar la provincia real en esa columna en vez del país (hoy la región real solo vive en la
`fuente` y en las `notas`).

### 8.2 `scout.py` — enriquece leads con datos de contacto

```
python agents/scout.py --limit 3 --region Granada
```

Flujo (`enriquecer_leads_sin_contacto`), por cada lead:
1. Infiere el `tipo` si falta (`inferir_tipo_lead`, por palabras clave).
2. **Google Places** (`lib/google_places.py`, opcional — solo si `GOOGLE_PLACES_API_KEY` está
   configurada): Text Search + Place Details para dirección/teléfono/web verificados por
   Google. Se acepta como confianza `alta` directamente (dato estructurado, no texto
   interpretado por un LLM) siempre que el nombre devuelto se parezca lo bastante al buscado
   (`difflib`, umbral 0.55). **Places no tiene email** — ese campo no existe en su API; solo
   adelanta trabajo dándole al paso 3 una web oficial ya verificada en vez de tener que
   adivinarla de snippets. Cuota: los campos de teléfono/web caen en el tier "Enterprise" de
   Google, con solo 1.000 llamadas gratis/mes — cuidado con lotes muy grandes (`--all`).
3. **Búsqueda amplia** + `extraer_datos_contacto_de_snippets` (1 sola llamada a la IA).
4. Si la web encontrada es "standalone" (no red social), la descarga
   (`descargar_texto_pagina`, `requests` + `BeautifulSoup`) y extrae de nuevo
   (`extraer_datos_contacto`) — es la mejor fuente de aforo/género.
5. Si sigue faltando email, un **fallback dirigido** (una búsqueda más, más específica).
6. Combina todo con `_combinar()` (primera fuente que aporta un dato gana, nunca se sobrescribe).
7. Guarda solo los datos de **confianza alta** (contacto) o **media** (género/aforo) —
   ver sección 9 sobre `_procesar_campos_extraidos`.
8. **Transición de estado:** si al final sigue sin email → `estados.SIN_CONTACTO`.

**Rate limiting:** `time.sleep(random.uniform(3, 5))` entre cada lead procesado.

### 8.3 `redactor.py` — genera el pitch

```
python agents/redactor.py --limit 5
python agents/redactor.py --id lead_xxxxx   # un lead concreto
```

Flujo (`procesar_nuevos_leads`):
1. Lee leads en `estados.NUEVO` **que ya tienen `email_contacto`**.
2. Carga el EPK (`cargar_epk()` → `data/epk_bakandeya.json`).
3. Elige el prompt según `tipo` (sala / festival / ayuntamiento) — cada uno con sus propias
   reglas de redacción (ver `.claude/skills/pitch-generation/SKILL.md` para las pautas de tono).
4. El `system_prompt` inyecta el EPK completo (bio, enlaces, influencias).
5. Llama a Gemini (`temperature=0.7`, más creatividad que el scout).
6. Si hay pitch → `estados.transicionar(lead, estados.PENDIENTE, pitch=pitch)`.

**Formato de salida esperado siempre:** `"ASUNTO: <asunto>\n\n<cuerpo>"`. El enviador depende de
este formato exacto (ver 8.4).

**Sin rate limiting ni validación de calidad todavía** — pendiente (sección 9).

### 8.4 `enviador.py` — crea el borrador/envío

```
python agents/enviador.py
```

Flujo (`enviar_leads_aprobados`):
1. Lee leads en `estados.APROBADO` (el humano ya dio el visto bueno a mano en la Sheet).
2. **`parsear_pitch(pitch, nombre_sala)`**: separa el `ASUNTO:` del cuerpo. Si el pitch no trae
   el marcador (degradación seguro), usa un asunto genérico y manda todo como cuerpo.
3. `gmail_client.crear_borrador(...)` (real o simulado según `es_modo_simulado()`).
4. Si va bien → `estados.transicionar(lead, estados.ESPERANDO)` + notificación Telegram.

### 8.5 `lector_bandeja.py` — clasifica respuestas

```
python agents/lector_bandeja.py
```

Flujo (`procesar_bandeja_entrada`):
1. `gmail_client.leer_respuestas()` (real o simulado).
2. Empareja cada respuesta con un lead en `estados.ESPERANDO` **por email del remitente**
   (substring match, no exacto).
3. Clasifica con Gemini en una de 3 categorías: `interesado` / `no_interesado` / `negociando`.
4. Si la IA devuelve algo raro, hay un fallback heurístico por palabras (`"no"` → no_interesado,
   `"nego"` → negociando, cualquier otra cosa → **interesado por defecto**).
5. `estados.transicionar(lead_asociado, categoria, notas=...)` + Telegram.

**⚠️ Sesgo conocido y pendiente de arreglar:** el fallback por defecto es `interesado`
([lector_bandeja.py:78](../agents/lector_bandeja.py)). Un email ambiguo, un "unsubscribe" o
cualquier respuesta que la IA no sepa clasificar claramente **cae hacia el lado optimista**. Ver
sección 9.

---

## 9. Deuda técnica conocida (pendiente, priorizada)

1. **Sesgo optimista del lector** ([lector_bandeja.py](../agents/lector_bandeja.py)): el
   fallback por defecto debería ser una categoría neutra que fuerce revisión manual, no
   `interesado`.
2. **Redactor sin rate limiting**: no hay `time.sleep` entre leads, a diferencia del scout.
3. **Sin validación de calidad del pitch**: el redactor no comprueba que el pitch generado
   contenga de verdad el marcador `ASUNTO:` ni los enlaces del EPK antes de pasarlo a
   `pendiente_aprobacion`.
4. **SDK de Gemini deprecado** (`google-generativeai`): Google recomienda migrar a `google-genai`.
5. **`claude_client.py` sin usar**: se descartó (2026-07-10) migrar el redactor a Sonnet; el
   proyecto se queda en Gemini Flash para todo. El wrapper de Claude queda como código muerto
   salvo que se retome esa decisión.
6. **Gmail OAuth real sin probar**: no existe `credentials.json`/`token.json`; todo corre en
   modo simulado (borradores HTML en `drafts/`).
7. **GitHub Actions creado pero sin secrets**: los 4 workflows (`scout.yml`, `redactor.yml`,
   `enviador.yml`, `lector_bandeja.yml`) ya existen en `.github/workflows/`, pero no se
   ejecutarán de verdad hasta añadir `GOOGLE_SERVICE_ACCOUNT_JSON`, `GEMINI_API_KEY`,
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` como secrets del repositorio en GitHub.

---

## 10. Scripts de utilidad (fuera del pipeline)

No los ejecuta ningún cron — son para ti, a mano, cuando haga falta:

- **`scripts/test_sheets_connection.py`**: diagnóstico rápido. Ejecútalo primero si algo falla
  con "Error al obtener leads de Google Sheets" — te dice si el problema es credenciales,
  nombre del documento o que falta la pestaña `leads`.
- **`scripts/setup_sheet_columns.py`**: crea a mano las columnas `telefono`/`website`/`instagram`
  si por lo que sea no se crearon automáticamente.
- **`scripts/import_excel_to_sheets.py`** + **`inspect_excel.py`**: importación puntual desde un
  Excel legado (mapea tamaños S/M/L a un aforo numérico aproximado). Solo se usó para la carga
  inicial de datos de Filgue; no forma parte del flujo normal.

---

## 11. Cómo probar sin tocar producción

### Tests automáticos (nunca tocan la red)

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

`tests/conftest.py` mockea **todas** las llamadas externas (Sheets, Gmail, Gemini) con fixtures
`autouse=True` — corren sobre una base de datos en memoria (`mock_db`, 3 leads de ejemplo). El
git hook `scripts/git-hooks/pre-commit` corre esto automáticamente antes de cada commit.

### Prueba real acotada, sin arriesgar nada

1. **Modo simulado de email:** pon `EMAIL_MODE=simulado` en `.env` (o simplemente no tengas
   `credentials.json`) — el enviador y el lector trabajan contra archivos locales en `drafts/`.
2. **Limita siempre con `--limit`** en scout/scout_descubridor/redactor antes de usar `--all`.
3. Revisa los logs por stdout — cada agente imprime con su prefijo (`[scout.py] ...`) qué está
   haciendo en cada paso.

---

## 12. Recetas de mantenimiento comunes

### Cambiar el tono/contenido de un pitch
Edita el `prompt` y `reglas_redaccion` correspondientes en `agents/redactor.py` (hay 3 bloques:
ayuntamiento, festival, sala). Revisa también `.claude/skills/pitch-generation/SKILL.md` si el
cambio es de estrategia general, no solo de un tipo de lead.

### Añadir un nuevo estado al pipeline
1. Añade la constante en `lib/estados.py`.
2. Añade las transiciones válidas **hacia** y **desde** ese estado en el diccionario
   `TRANSICIONES`.
3. Usa la nueva constante en el agente correspondiente con `estados.transicionar(...)`.
4. Añade un test en `tests/test_estados.py` para la transición nueva.

### Añadir una columna nueva a la Sheet
`lib/sheets.py::actualizar_datos_lead` ya sabe auto-crear columnas que no existen (patrón
`if "campo" in datos_dict and "campo" not in headers: sheet.insert_cols(...)`) — copia ese patrón
si añades un campo nuevo que un agente debe poder rellenar por primera vez.

### Cambiar qué modelo de IA usa un agente
Cada llamada pasa `model_name="gemini-2.5-flash"` explícito — cámbialo directamente en la llamada
a `generar_texto_gemini(...)`. Si migras un agente a Claude, importa `lib.claude_client` en vez
de (o además de) `lib.gemini_client` y usa `generar_texto(...)`.

### Depurar por qué un lead no avanza
1. Mira la columna `notas` del lead en la Sheet — cada agente deja un rastro legible de lo que
   intentó.
2. Comprueba el `estado` actual y compara contra el grafo de la sección 3: ¿hay algún agente que
   *debería* estar leyendo ese estado?
3. Ejecuta el agente correspondiente suelto con `--id <lead_id>` (redactor) o filtrando por
   `--region` (scout) para verlo procesar ese lead en concreto con logs completos.

### Investigar un fallo SSL intermitente
Si ves `CERTIFICATE_VERIFY_FAILED`, es casi seguro el proxy TLS corporativo (ver
`lib/__init__.py`). Comprueba que `truststore` está instalado
(`pip show truststore`) y que `lib/__init__.py` sigue llamando a
`truststore.inject_into_ssl()`.

---

## 13. Glosario

- **JSON mode / salida estructurada**: pedirle a la IA una respuesta que el propio proveedor
  garantiza que será JSON válido (`forzar_json=True` en `gemini_client`), en vez de rogar "por
  favor responde solo JSON" y luego parsear a mano.
- **Grounding**: instruir a la IA para que solo pueda afirmar algo si puede señalar la fuente
  concreta (un snippet de búsqueda) que lo respalda — reduce alucinaciones.
- **Confianza (alta/media/baja)**: etiqueta que la IA pone a cada dato que extrae; solo los datos
  de confianza suficiente se escriben como "verificados" en la Sheet (ver `UMBRALES_POR_CAMPO` en
  `scout.py`).
- **Modo simulado**: cuando faltan credenciales de Gmail (o `EMAIL_MODE=simulado`), el sistema
  simula el envío/lectura de correo con archivos locales en `drafts/`, sin tocar la red.
- **Fixture autouse**: en pytest, una función de preparación que se aplica automáticamente a
  todos los tests sin que cada test tenga que pedirla explícitamente (así los mocks de Sheets/
  Gmail/IA se activan solos).
