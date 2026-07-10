# Cómo funciona Bakandeya Agent Manager

Este documento explica, sin dar nada por sabido, cómo funciona el sistema completo. Si vienes
de VBA/Access, la idea más importante que tienes que interiorizar es esta: **aquí no hay un
programa "grande" corriendo todo el rato**. Hay varios scripts pequeños e independientes que se
despiertan, hacen una cosa, y se apagan. Lo que los coordina no es código: es una hoja de cálculo.

---

## 1. La idea central: la Google Sheet ES el orquestador

Imagina una cinta transportadora de una fábrica. Cada contacto (sala, festival, ayuntamiento) es
una caja que va avanzando por estaciones. En cada estación un operario hace su tarea y empuja la
caja a la siguiente. Ningún operario controla a los demás: cada uno mira las cajas que están en
"su" estación y actúa.

Aquí:

- Cada **fila** de la hoja `leads` de Google Sheets es una caja (un contacto).
- La columna **`estado`** dice en qué estación está esa caja.
- Cada **agente** (un script de Python) es un operario: lee las filas en su estado, trabaja,
  cambia el estado de la fila y **termina**.

No hay un "orquestador.py". El estado de cada fila ES el orquestador. Esto se llama a veces
*arquitectura basada en estado* y es deliberadamente simple: no hay procesos colgados, no hay
servidor encendido 24h, no hay cola de mensajes que mantener. Si algo falla, la fila se queda en
su estado y el agente lo reintenta la próxima vez que se ejecute.

### El ciclo de vida de un lead (los estados)

```
                 scout / scout_descubridor
                          │  (crean/enriquecen)
                          ▼
   ┌────────┐  redactor  ┌──────────────────────┐  (Diego revisa a mano)  ┌──────────┐
   │ nuevo  │──────────► │ pendiente_aprobacion │ ──────────────────────► │ aprobado │
   └────────┘            └──────────────────────┘                         └────┬─────┘
                                                                                │ enviador
                                                                                ▼
                                                                    ┌──────────────────────┐
                                                                    │  esperando_respuesta │
                                                                    └───────────┬──────────┘
                                                                                │ lector_bandeja
                             ┌──────────────────────────────────────────────────┼───────────────┐
                             ▼                          ▼                         ▼               ▼
                       interesado                no_interesado             negociando       (descartado)
```

**La barrera humana está entre `pendiente_aprobacion` y `aprobado`.** Ese salto SOLO lo hace
Diego a mano en la hoja. Ningún email sale sin ese visto bueno. Es una regla innegociable
(ver `CLAUDE.md`): la IA propone, el humano dispone.

---

## 2. Los cinco agentes

Cada agente es un script en `agents/` que se puede ejecutar suelto (`python agents/scout.py ...`)
y que en producción lanza un cron de GitHub Actions. Aquí, qué hace cada uno:

| Agente | Lee estado | Escribe estado | Modelo IA | Por qué ese modelo |
|---|---|---|---|---|
| `scout_descubridor.py` | — (busca en la web) | `nuevo` | Gemini Flash | Descubrir nombres es volumen y barato |
| `scout.py` | `nuevo` (incompletos) | `nuevo` (enriquecido) | Gemini Flash | Extraer contactos es volumen y barato |
| `redactor.py` | `nuevo` (con email) | `pendiente_aprobacion` | **Claude Sonnet** (pendiente de migrar) | La calidad del texto vende el bolo |
| `enviador.py` | `aprobado` | `esperando_respuesta` | — (no usa IA) | Solo manda el email por Gmail |
| `lector_bandeja.py` | `esperando_respuesta` | `interesado`/`no_interesado`/`negociando` | Gemini/Claude Haiku | Clasificar 3 etiquetas es simple y barato |

> **Estrategia de modelo (híbrida).** Se usa **Gemini Flash** para las tareas de volumen y bajo
> coste (buscar, enriquecer, clasificar) y **Claude Sonnet** donde la calidad de redacción
> importa de verdad (el redactor). Hoy el redactor todavía usa Gemini; migrarlo a Sonnet está
> pendiente. El wrapper de cada proveedor vive en `lib/gemini_client.py` y `lib/claude_client.py`.

### scout_descubridor.py — el que encuentra sitios nuevos
Le das una región y un tipo (`python agents/scout_descubridor.py --region Pontevedra --tipo sala`).
Busca en DuckDuckGo, le pasa los resultados a la IA para que extraiga nombres reales de salas de
esa zona, descarta los que ya existen (deduplicación por nombre normalizado) y crea filas nuevas
en estado `nuevo`. **No verifica que existan de verdad ni tiene sus contactos** — solo siembra
nombres para que el Scout los enriquezca después.

### scout.py — el que rellena los datos que faltan
Coge leads en `nuevo` a los que les falta email/teléfono/web/instagram. Para cada uno: busca en
DuckDuckGo, extrae datos de los snippets con IA, y si encuentra la web oficial la descarga
(`requests` + `BeautifulSoup`) para sacar más detalles (aforo, género). Guarda lo que encuentra
sin sobrescribir lo que ya había.

### redactor.py — el que escribe la propuesta
Coge leads en `nuevo` **que ya tienen email**. Usa el EPK de la banda
(`data/epk_bakandeya.json`) y genera un pitch personalizado según el tipo (sala / festival /
ayuntamiento). Deja la fila en `pendiente_aprobacion`. Las pautas de tono están en la skill
`.claude/skills/pitch-generation/`.

### enviador.py — el que manda el correo
Coge leads en `aprobado` (aprobados a mano por Diego), envía el pitch por Gmail y pasa la fila a
`esperando_respuesta`. Avisa por Telegram.

### lector_bandeja.py — el que lee las respuestas
Lee la bandeja de Gmail, empareja cada respuesta con su lead por email, y clasifica el tono con
IA en `interesado` / `no_interesado` / `negociando`. Avisa por Telegram.

---

## 3. Qué es (de verdad) una llamada a un LLM

Cuando un agente "usa IA", por dentro lo único que pasa es una función que recibe texto y
devuelve texto. Los tres ingredientes:

- **system prompt** (el rol): "Eres un extractor experto de datos de contacto...". Define QUIÉN
  es el modelo y sus reglas fijas.
- **prompt** (la tarea): los datos concretos de esta vez (los snippets de búsqueda, el nombre de
  la sala...) y qué queremos que devuelva.
- **temperature** (cuánta creatividad): de 0 a 1.
  - `0.1` para **extraer datos**: queremos que sea literal y repetible, no que "invente".
  - `0.7` para **redactar pitches**: queremos variedad y un texto que suene natural.

Todo esto se ve concentrado en `lib/gemini_client.py` (función `generar_texto_gemini`) y
`lib/claude_client.py` (`generar_texto`).

### Salida estructurada (JSON mode) — el patrón clave que introdujimos
Antes, para que la IA devolviera datos, le pedíamos "devuélveme un JSON" y luego el código
quitaba a mano los ```` ```json ```` que el modelo a veces añadía. Frágil: un carácter raro y
`json.loads` explota.

Ahora usamos **JSON mode**: al pedir la respuesta se activa `forzar_json=True`, que le dice a
Gemini (`response_mime_type="application/json"`) que la respuesta *tiene* que ser un JSON válido.
El modelo ya no puede añadir texto ni fences, así que el código hace `json.loads(respuesta)`
directo. Menos código defensivo y una clase entera de bugs eliminada.

### Anti-alucinación: confianza + fuente
Un LLM, si no encuentra un dato, tiende a **inventárselo** con total seguridad (a esto se le
llama "alucinar"). Para una regla innegociable como "no contactar a un email inventado", eso es
peligroso. La defensa que añadimos:

- A la IA le pedimos que, por cada dato, diga su **`confianza`** (`alta`/`media`/`baja`) y la
  **`fuente`** (qué snippet lo respalda).
- El helper `_procesar_campos_extraidos` (en `scout.py`) **solo escribe en la Sheet los datos de
  confianza `alta`**. Los de confianza media/baja se anotan en `notas` como "a verificar", pero
  no rellenan el campo. Así el dato no se pierde, pero tampoco se da por bueno sin más.
- El descubridor usa la misma idea con *grounding*: la IA solo puede devolver una entidad si
  señala el snippet que la respalda; si no puede, no la incluye. Menos salas inventadas.

---

## 4. La infraestructura de apoyo (`lib/`)

Cada archivo de `lib/` envuelve un servicio externo y devuelve valores "seguros" ante error
(`None`, `[]`, `False`) en vez de reventar:

- **`sheets.py`** — la "base de datos". Lee/escribe la Google Sheet vía `gspread`. Funciones
  clave: `obtener_leads(estado=...)`, `actualizar_datos_lead()`, `actualizar_estado_lead()`,
  `crear_leads()`.
- **`gemini_client.py`** / **`claude_client.py`** — llamadas a la IA (ver sección 3).
- **`gmail_client.py`** — enviar y leer correo con Gmail (OAuth de usuario).
- **`telegram.py`** — notificaciones. Si faltan credenciales, imprime un mock y sigue.

---

## 5. Cómo probar el sistema

### Con el arnés de tests (sin tocar APIs reales)
Los tests de `tests/` mockean TODAS las APIs externas (Sheets, Gmail, IA) — no tocan la red. Se
ejecutan sobre una base de datos en memoria (fixtures de `tests/conftest.py`).

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

Hay además un git hook (`scripts/git-hooks/pre-commit`) que corre los tests antes de cada commit
y aborta si fallan. Ver la skill `.claude/skills/test-harness/`.

### Suelto contra las APIs reales (requiere `.env` con credenciales)
```bash
# Descubrir salas nuevas en una provincia (crea filas 'nuevo')
python agents/scout_descubridor.py --region Pontevedra --tipo sala --limit 3

# Enriquecer 1 lead incompleto (rellena contactos)
python agents/scout.py --limit 1
```

Cada agente escribe logs claros a stdout con su prefijo (`[scout.py] ...`), que en producción
recoge GitHub Actions.

---

## 6. Resumen en una frase

Una hoja de cálculo donde el `estado` de cada fila decide qué agente la toca; cada agente es un
script pequeño que se despierta, hace su parte con ayuda de IA (con salida estructurada y control
de confianza para no inventar), cambia el estado y se apaga; y nada se envía sin que un humano lo
apruebe.
