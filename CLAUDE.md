# CLAUDE.md — Bakandeya Agent Manager

Este archivo da contexto a Claude Code en cada sesión sobre este proyecto. Léelo entero antes de tocar código.

## Qué es esto

Sistema de agentes de IA que automatiza el trabajo operativo de manager de banda para
**Bakandeya**: buscar salas y festivales, escribir propuestas (pitches) personalizadas,
enviarlas (con aprobación humana) y clasificar las respuestas. No sustituye el criterio de
Filgue — solo automatiza la parte repetitiva. Todo envío pasa por aprobación humana. Ningún
contacto se marca "listo para enviar" sin verificación humana de que existe de verdad.

Contexto completo del proyecto (fases, costes, modelo económico): ver `docs/informe_proyecto.md`.

## Fase actual

**Fase 1 — MVP operativo, ahora multi-tenant.** El plan original decía "no construir
multi-tenant hasta demostrar bolos reales con Bakandeya" — pero la app hermana
(`Bakandeya_AIStudio_Application`, el dashboard/CRM) se adelantó por su cuenta y ya soporta
varias bandas registradas compartiendo la misma Google Sheet. Decisión de Diego
(2026-08-10): en vez de pelear contra eso, los agentes de este repo también pasan a ser
multi-tenant — ver sección "Multi-tenant" más abajo. Sigue habiendo una única banda real en
producción (Bakandeya) hasta que se demuestre tracción real con más; Stripe/facturación
siguen sin construirse.

## Arquitectura

No hay un "orquestador" como pieza de código separada: **el estado de cada fila en la
Google Sheet ES el orquestador**. Cada agente:
1. Lee las filas en el estado que le corresponde.
2. Hace su trabajo.
3. Actualiza el estado de la fila.
4. Termina — no hay proceso corriendo en bucle.

Cuatro agentes, ejecutados por cron vía GitHub Actions (nunca un servidor 24h encendido):

| Agente | Lee estado | Escribe estado | Cron |
|---|---|---|---|
| `scout.py` | — (fuentes externas) | `nuevo` | diario 06:00 |
| `redactor.py` | `nuevo` | `pendiente_aprobacion` | diario 09:00 |
| `enviador.py` | `aprobado` | `esperando_respuesta` | diario 09:30 |
| `lector_bandeja.py` | `esperando_respuesta` | `interesado` / `no_interesado` / `negociando` | cada 2h |
| `monitor_redes.py` | — (fuentes externas) | `metricas` (Google Sheet) | quincenal (días 1 y 15, 08:00) |
| `seguimiento.py` | `esperando_respuesta` (>=10 días) | `esperando_respuesta` + notas | semanal (lunes 09:00) |
| `reporte_semanal.py` | `leads` + `metricas` | Telegram (notificación) | semanal (domingo 18:00) |
| `agente_finanzas.py` | `conciertos` | `finanzas` (Google Sheet) | semanal (lunes 10:00) |

**Orden de construcción: Redactor → Gmail (enviador + OAuth) → Scout.** Scout es el más
arriesgado (no existe una API de "todas las salas"; requiere semilla manual + búsqueda +
extracción con IA + verificación). No lo ataques primero.

### Segundo funnel: `medios_scout` (prensa/radio/TV/canales de promoción)

Además de `leads` (booking de conciertos), existe una hoja hermana `medios_scout` para contactos
de prensa (radio, TV, periódicos, blogs musicales, canales de redes) — el objetivo aquí NO es
que nos contraten, es conseguir cobertura editorial (entrevista, reseña, mención). Reutiliza el
mismo grafo de estados (`lib/estados.py`) y casi toda la infraestructura (`lib/sheets.py` y
`lib/estados.py` aceptan un parámetro `nombre_hoja` para esto), pero tiene su propio contenido
de pitch (nunca habla de aforo/caché/fechas de concierto) y su propio esquema de columnas — ver
más abajo. `redactor.py`, `enviador.py` y `lector_bandeja.py` soportan ambas hojas
(`--medios` en redactor/enviador; lector_bandeja las procesa juntas en la misma pasada, ya que
solo hay una bandeja de Gmail). `scout_medios.py` ya existe (descubrimiento + enriquecimiento,
mismo patrón anti-alucinación que `scout.py`: confianza/fuente, solo se escribe lo verificado).

**Ojo con el nombre:** se llama `medios_scout`, no `medios` — ver la nota en el esquema de la
hoja más abajo sobre por qué, y no lo cambies sin releerla.

## Multi-tenant

`Bakandeya_AIStudio_Application` (el dashboard/CRM, repo hermano, Node/TS — NUNCA se edita
desde aquí, es de solo lectura para este proyecto) gestiona el registro de bandas, su EPK y su
nivel de autonomía en tres pestañas de la MISMA Google Sheet que este repo usa. Este repo las
**lee** (nunca las autocrea ni las reescribe — ese esquema lo posee y mantiene la app Node,
`server/sheets.ts`):

| Pestaña | Qué es | Función de lectura (Python) |
|---|---|---|
| `registro_bandas` | Bandas registradas en la app y su estado de cuenta | `lib/sheets.py::obtener_bandas_activas()` |
| `dossier_epk` | Bio, rider técnico, enlaces, contacto de management por banda | `lib/sheets.py::obtener_epk_banda(band_id)` |
| `config_autonomia` | Umbrales de caché y profundidad de negociación por banda | `lib/sheets.py::obtener_autonomia_banda(band_id)` |

`lib/bandas.py` adapta esas tres lecturas a la forma que ya esperan `redactor.py` y
`gmail_client.py` (`listar_bandas_activas`, `cargar_epk_banda`, `cargar_autonomia_banda`). Para
`band-bakandeya` en concreto, `cargar_epk_banda` sigue enriqueciendo con
`data/epk_bakandeya.json` (integrantes, influencias, trayectoria, precisión de instrumentos) —
contenido curado a mano que el esquema de `dossier_epk` todavía no modela. Una banda nueva
funciona en cuanto rellena su EPK en la app, sin tocar código Python.

Todas las filas nuevas que crean/actualizan los agentes (`leads`, `medios_scout`,
`hilos_emails`) llevan una columna `band_id` (con red de seguridad en `lib/sheets.py` que la
crea sola si todavía no existe en esa hoja). `redactor.py`, `enviador.py` y `lector_bandeja.py`
filtran/operan por `band_id` — **nunca mezclan datos de una banda con los de otra**, ni siquiera
al procesar la bandeja de Gmail (que es compartida, ver regla del buzón único abajo). Los tres
agentes aceptan `--banda <band_id>` por CLI; si se omite, recorren TODAS las bandas activas de
`registro_bandas` (con una sola banda registrada, o si esa hoja aún no existe, el comportamiento
es idéntico al single-tenant original: todo cae en `band-bakandeya` por defecto).

**Regla explícita de Diego (2026-08-10) — cada banda envía desde su propio email oficial:**
cada banda tiene su propia cuenta de Gmail conectada por OAuth (su "agente virtual" propio) —
**nunca** un buzón compartido entre bandas, y **nunca** el email personal de quien esté
logueado en el CRM. `lib/gmail_client.py` resuelve qué token usar por banda
(`_ruta_token(band_id)`): `band-bakandeya` sigue usando el `token.json` de siempre en la raíz
del repo (retrocompatibilidad); cualquier otra banda usa `tokens/{band_id}.json` (o la variable
de entorno `GMAIL_TOKEN_PATH_<BAND_ID>` para inyectarlo como secreto de GitHub Actions). Ese
token se genera UNA VEZ conectando la cuenta de Gmail real de la banda con el flujo OAuth local
(igual que se hizo para Bakandeya) — los agentes nunca abren un login interactivo para una
banda que no sea la original, porque reventaría en un cron sin navegador; si el token de una
banda no existe o caducó, `enviador.py` no envía nada para ella y lo dice claramente.

Antes de crear cualquier borrador, `enviador.py` verifica con
`gmail_client.obtener_email_conectado(band_id)` que la cuenta realmente conectada coincide con
el email oficial de esa banda en su `dossier_epk` — si no coincide, no envía nada y avisa por
Telegram (mejor no enviar que hacerlo desde la mailbox equivocada).

Como cada banda tiene su propia bandeja de Gmail, `lector_bandeja.py` ya NO lee una única
bandeja compartida: recorre las bandas activas y llama a `gmail_client.leer_respuestas(band_id=...)`
una vez por banda, emparejando cada respuesta solo contra las filas esperando de ESA banda.

**Nivel de autonomía (`config_autonomia`):** los agentes lo LEEN (`lector_bandeja.py` anota si
una oferta de caché está por debajo/encima de los umbrales de la banda, tanto en `notas` como en
el aviso de Telegram) pero nunca lo usan para saltarse la aprobación humana — la regla
innegociable nº 1 (ningún email sale sin aprobación) no depende de esta configuración, ni aquí
ni en la app Node.

**Deuda conocida / límites de este primer corte multi-tenant:** el contenido de los pitches
(`agents/redactor.py`) sigue teniendo reglas de estilo específicas de Bakandeya (p. ej. la regla
14 de festivales menciona "percusión reciclada, luthería urbana" explícitamente) — el nombre de
firma y la persona del sistema ya son dinámicos por banda, pero el contenido musical de las
reglas no se ha generalizado. Antes de dar de alta una segunda banda real, revisa y adapta esas
reglas de estilo. `scout.py`/`scout_descubridor.py` (enriquecimiento de contacto) no filtran por
banda porque rellenar email/teléfono/dirección de un lead ya existente es agnóstico de banda;
solo la CREACIÓN de leads nuevos (`scout_descubridor.py`, `scout_medios.py`) estampa `band_id`.

**Requisito operativo para dar de alta una banda nueva de verdad:** hay que conectar su cuenta
de Gmail real con el flujo OAuth local (`python -c "import lib.gmail_client as g; g.obtener_servicio_gmail('band-nueva')"`
o similar, una vez, en local) para generar `tokens/band-nueva.json`, y luego desplegar ese
fichero como secreto de GitHub Actions (`GMAIL_TOKEN_PATH_BAND_NUEVA` apuntando a una ruta, o
escribiendo el secreto directamente en `tokens/band-nueva.json` en el workflow, igual que ya se
hace con `GMAIL_TOKEN_JSON` → `token.json` en `.github/workflows/enviador.yml`). Sin ese paso,
`enviador.py` no manda nada para esa banda (falla explícito, no en silencio).

## Stack

- **Lenguaje:** Python 3.11+
- **Datos:** Google Sheets vía `gspread` (service account, no OAuth de usuario para esto)
- **Email:** Gmail API con OAuth — reutilizar patrón de `larra_sync.py` si Diego lo aporta al repo
- **IA:** Gemini Flash (`gemini-2.5-flash`, vía `lib/gemini_client.py`) para todo: `scout.py`,
  `scout_descubridor.py`, `redactor.py` y `lector_bandeja.py`. *Decisión (2026-07-10): se descarta
  por ahora la migración de `redactor.py` a Claude Sonnet — se mantiene la estrategia mono-modelo
  con Gemini. `lib/claude_client.py` queda sin usar por ningún agente.* Toda extracción de datos
  usa salida estructurada (JSON mode,
  `forzar_json=True`) para robustez. Nota: `google-generativeai` está deprecado por Google
  (recomiendan `google-genai`) — funciona, pero es deuda técnica a migrar.
- **Notificaciones:** Telegram Bot API
- **Scheduler:** GitHub Actions (cron), no Celery/n8n/servidores propios
- **Scraping puntual (Scout):** `requests` + `BeautifulSoup` para HTML simple, `playwright`
  solo si la web requiere JS
- **Google Places API (New)** (`lib/google_places.py`, opcional, desde 2026-08-11): primera
  fuente de dirección/teléfono/web en `scout.py` — dato estructurado y verificado por Google,
  se acepta como confianza `alta` sin pasar por el LLM. **No tiene campo de email** (no existe
  en su esquema, en ninguna versión de la API) — no sustituye la búsqueda de contacto, solo le
  da un mejor punto de partida (sobre todo la web oficial). Requiere `GOOGLE_PLACES_API_KEY`;
  si no está configurada, `scout.py` funciona exactamente igual que antes. Cuota: los campos de
  teléfono/web caen en tier "Enterprise" de Google, solo 1.000 llamadas gratis/mes (no 5.000,
  que es el tier "Pro" — ojo con esa diferencia al planear lotes grandes).

No introducir n8n, LangGraph, CrewAI ni frameworks de orquestación nuevos sin que Diego lo
pida explícitamente. La complejidad de este proyecto se controla a propósito.

## Estructura del repo

```
bakandeya-agent-manager/
├── CLAUDE.md
├── README.md
├── .env.example
├── requirements.txt
├── agents/
│   ├── scout.py
│   ├── scout_medios.py
│   ├── redactor.py
│   ├── enviador.py
│   ├── lector_bandeja.py
│   ├── monitor_redes.py
│   ├── seguimiento.py
│   ├── reporte_semanal.py
│   └── agente_finanzas.py
├── lib/
│   ├── sheets.py          # conexión y helpers de la Google Sheet
│   ├── bandas.py          # multi-tenant: registro_bandas / dossier_epk / config_autonomia
│   ├── gmail_client.py    # OAuth, enviar, leer (un único buzón para todas las bandas)
│   ├── claude_client.py   # wrapper llamadas a Claude API
│   └── telegram.py        # notificaciones
├── data/
│   └── epk_bakandeya.json # bio, links, rider técnico, caché objetivo, disponibilidad
├── .github/workflows/
│   ├── scout.yml
│   ├── redactor.yml
│   ├── enviador.yml
│   ├── lector_bandeja.yml
│   ├── monitor_redes.yml
│   ├── seguimiento.yml
│   ├── reporte_semanal.yml
│   └── agente_finanzas.yml
└── tests/
```

## Esquema de la Google Sheet (hoja `leads`)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | string | uuid corto |
| `nombre_sala` | string | |
| `ciudad` / `region` | string | |
| `aforo` | int | |
| `genero` | string | |
| `email_contacto` | string | verificado antes de `aprobado` |
| `fuente` | string | de dónde salió el contacto (para auditar) |
| `estado` | string | `nuevo` / `pendiente_aprobacion` / `aprobado` / `enviado` / `esperando_respuesta` / `interesado` / `no_interesado` / `negociando` / `descartado` |
| `pitch_generado` | text | output del Redactor |
| `fecha_envio` | date | fecha del último envío/borrador, autogenerada por `estados.py` |
| `fecha_ultima_respuesta` | date | |
| `contacto_nombre` | string | nombre de la persona de programación/booking, si el Scout lo encuentra literal en la web (confianza `media`+) |
| `contexto_extra` | text | frase breve sobre qué tipo de eventos/ambiente tiene la sala o festival, extraída de su propia web; usada por el Redactor para personalizar de verdad en vez de solo por género/aforo |
| `direccion` | string | dirección postal completa (calle, número, CP) del recinto, si el Scout la encuentra literal en la web (confianza `alta` únicamente — para logística de gira un dato dudoso es peor que no tenerlo) |
| `notas` | text | |
| `band_id` | string | multi-tenant: a qué banda pertenece el lead (ver sección "Multi-tenant"). Columna propiedad de `Bakandeya_AIStudio_Application`; los agentes la leen/escriben pero no la autocrean si ya existe |

### Esquema de la Google Sheet (hoja `medios_scout`)

Se autocrea con estas cabeceras la primera vez que se escribe en ella (ver
`lib/sheets.py::_ESQUEMAS_HOJAS_AUTOCREABLES`). **Importante:** se llama `medios_scout` y NO
`medios` a propósito — existe una pestaña `medios` distinta gestionada directamente desde
Google AI Studio (con su propio esquema, `ID/Nombre/Tipo/Estado/Contacto/Notas`), aprovisionada
en vivo fuera de este repo. Usar el mismo nombre de pestaña para ambos sistemas corrompió datos
una vez (columnas renombradas/desplazadas) — no lo vuelvas a unificar sin coordinarlo primero.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | string | |
| `nombre_medio` | string | |
| `tipo_medio` | string | `radio` / `tv` / `prensa` / `blog` / `podcast` / `canal_redes` |
| `ciudad` | string | |
| `alcance` | string | `local` / `regional` / `nacional` |
| `direccion` | string | dirección postal completa de la redacción/sede, si se encuentra literal en la web (confianza `alta` únicamente) |
| `email_contacto` | string | verificado antes de `aprobado`, igual que en `leads` |
| `enfoque_editorial` | text | qué cubre de verdad ese medio, extraído de su web — es el equivalente de `contexto_extra` para el pitch de prensa |
| `fuente` | string | |
| `estado` | string | mismo grafo que `leads` (`lib/estados.py`) |
| `pitch_generado` | text | output de `redactor.py --medios` (`generar_pitch_medio`) |
| `fecha_envio` | date | |
| `fecha_ultima_respuesta` | date | |
| `notas` | text | |
| `band_id` | string | multi-tenant, mismo significado que en `leads`. Esta columna sí la autocrea este repo (`CABECERAS_MEDIOS`), ya que `medios_scout` es propiedad de Python |

### Esquema de la Google Sheet (hoja `metricas`)

| Columna | Tipo | Notas |
|---|---|---|
| `fecha` | date | `YYYY-MM-DD` |
| `instagram` | int | número de seguidores |
| `tiktok` | int | número de seguidores |
| `youtube` | int | número de suscriptores |
| `notas` | string | detalle de la actualización (ej: "Registro automático") |

## Reglas innegociables (no las rompas aunque Diego tenga prisa)

1. Ningún email sale sin aprobación humana explícita (cambio manual de estado a `aprobado`).
2. Ningún lead pasa a `aprobado` sin que el email de contacto esté verificado.
3. Rate limiting propio al buscar/scrapear — no dispares peticiones en bucle sin pausas.
4. Nunca hardcodear credenciales — todo vía variables de entorno (`.env`, `.env.example` sin valores reales).
5. Cumplimiento RGPD básico: solo se contactan datos de contacto profesionales de la sala/festival, nunca datos personales fuera de ese contexto.
6. Multi-tenant: cada banda envía SIEMPRE desde su propio email oficial (su propia cuenta de Gmail conectada por OAuth). Nunca un buzón compartido entre bandas ni el email personal de un usuario — ver sección "Multi-tenant".
7. Multi-tenant: ningún agente mezcla datos de una banda con los de otra — toda lectura/escritura de leads/medios/hilos filtra por `band_id`.

## Convenciones de código

- Comentarios y docstrings en español.
- Nombres de funciones/variables en español si describen dominio de negocio (`buscar_salas`,
  `generar_pitch`), en inglés si son utilidades técnicas genéricas (`fetch_page`, `retry`).
- Un script por agente, ejecutable de forma independiente (`python agents/redactor.py`) para
  poder probarlo suelto sin lanzar todo el pipeline.
- Logs claros a stdout (los recoge GitHub Actions) — nada de prints sueltos sin contexto.

## Cómo trabajar conmigo en este proyecto

- Trocea las tareas en pasos que quepan en 1,5–2h de sesión. Si algo va a llevar más, dilo
  antes de empezar.
- Da 2-3 opciones cuando haya varias formas razonables de resolver algo, no una sola.
- Sé directo si una petición rompe alguna regla innegociable o añade complejidad que no toca
  en esta fase — dilo, no lo hagas en silencio.
- Antes de escribir código nuevo, revisa si ya existe algo reutilizable en `lib/`.

## Estado del proyecto

_(Actualizar esta sección a medida que avance)_

- [x] Fase 0 — Contactos, playbook y EPK de Filgue volcados
- [x] `redactor.py` funcionando con EPK real adaptado a Salas, Festivales y Ayuntamientos (firma 'Bakandeya IA Management')
- [ ] `enviador.py` + Gmail OAuth funcionando
- [x] `scout_descubridor.py` — soporte multi-tipo, desambiguación geográfica (España), deduplicación difusa y provincia real en `region`
- [x] `scout.py` — enriquecimiento con extractor Regex, búsquedas dirigidas en redes sociales (Instagram/Facebook/Linktree), 15 snippets y umbral flexible de email
- [ ] `lector_bandeja.py` funcionando
- [x] Primeras pruebas con salas reales ejecutadas con éxito (Guadalajara, Ávila), Festivales y Ayuntamientos con variedad y traducción automática
- [x] Bug del `ASUNTO:` en `enviador.py` arreglado (el asunto generado ya no se cuela en el cuerpo)
- [x] `enviador.py` + Gmail OAuth real funcionando y probado (se generó `token.json` y crea borradores en Gmail de verdad)
- [x] `scout.py` — versión semilla manual + enriquecimiento adaptada a Salas, Festivales y Ayuntamientos
- [x] Scout robustecido — salida estructurada (JSON mode) + anti-alucinación (confianza/fuente)
- [x] `lector_bandeja.py` funcionando (clasifica con Gemini Flash)
- [x] Máquina de estados (`lib/estados.py`) con grafo de transiciones válidas y soporte para regeneración de pitches
- [x] Workflows de GitHub Actions configurados con los secretos del repositorio
- [x] Agente de monitorización de redes sociales (`monitor_redes.py` + workflow quincenal) funcionando
- [x] Agente de seguimiento automático (`seguimiento.py` + workflow semanal + auto fecha_envio) funcionando
- [x] Agente de reporte semanal (`reporte_semanal.py` + workflow semanal) funcionando
- [x] Agente de finanzas (`agente_finanzas.py` + workflow semanal + auto estimación de costes con Gemini) funcionando
- [x] Scout enriquece `contacto_nombre` y `contexto_extra` por lead; Redactor los usa para personalizar de verdad (saludo por nombre + gancho real) en vez de solo género/aforo; enfoque de estilo del pitch ahora se elige aleatoriamente en Python en vez de dejárselo al LLM
- [x] Corregido el contacto de negociación en `responder.py`/EPK: ya no apunta a Diego (que es el desarrollador de la plataforma, no toma decisiones de negocio) — apunta al contacto oficial de la banda (`Bakandeya@gmail.com` / `+34 652938521`)
- [ ] Primeras pruebas con salas reales (envío de los primeros borradores aprobados)
- [x] Multi-tenant (2026-08-10): `lib/bandas.py` + lectura de `registro_bandas`/`dossier_epk`/`config_autonomia`; `band_id` en `leads`/`medios_scout`/`hilos_emails`; `redactor.py`/`enviador.py`/`lector_bandeja.py`/`scout_descubridor.py`/`scout_medios.py` filtran o estampan por banda; firma dinámica en `gmail_client.py`; **cada banda envía desde su propio email oficial conectado por OAuth** (`tokens/{band_id}.json`, nunca un buzón compartido — corregido el mismo día tras una primera versión equivocada que usaba un único buzón); `enviador.py` verifica la cuenta conectada contra el EPK antes de enviar; `lector_bandeja.py` lee la bandeja propia de cada banda y anota ofertas frente a su nivel de autonomía. Pendiente: generalizar el contenido de estilo del pitch (ver "Deuda conocida" en la sección Multi-tenant) antes de dar de alta una segunda banda real; y conectar de verdad el Gmail de esa segunda banda cuando exista (hoy solo band-bakandeya tiene token)

> **Documentación:** el funcionamiento completo del sistema (arquitectura basada en estado,
> ciclo de vida del lead, rol de cada agente) está explicado en `docs/como_funciona.md`. Deuda
> técnica conocida y priorizada en `docs/guia_mantenimiento.md` (sección 9).
>
> **Siguiente paso:** Revisar los borradores generados en tu bandeja de Gmail, cambiar el estado
> de las salas de tu interés a `aprobado` en la Google Sheet y ejecutar `enviador.py` en modo real.
