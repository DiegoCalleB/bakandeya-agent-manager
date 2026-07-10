# CLAUDE.md — Bakandeya Agent Manager

Este archivo da contexto a Claude Code en cada sesión sobre este proyecto. Léelo entero antes de tocar código.

## Qué es esto

Sistema de agentes de IA que automatiza el trabajo operativo de manager de banda para
**Bakandeya**: buscar salas y festivales, escribir propuestas (pitches) personalizadas,
enviarlas (con aprobación humana) y clasificar las respuestas. No sustituye el criterio de
Filgue — solo automatiza la parte repetitiva. Todo envío pasa por aprobación humana. Ningún
contacto se marca "listo para enviar" sin verificación humana de que existe de verdad.

Contexto completo del proyecto (fases, costes, modelo económico): ver `docs/informe_proyecto.md`
si existe en el repo, o preguntar a Diego.

## Fase actual

**Fase 1 — MVP interno**, validando solo con Bakandeya. No construir nada de Fase 2
(multi-tenant, Supabase, Stripe, dashboard) hasta que esta fase demuestre bolos reales
cerrados durante 4-6 semanas.

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

**Orden de construcción: Redactor → Gmail (enviador + OAuth) → Scout.** Scout es el más
arriesgado (no existe una API de "todas las salas"; requiere semilla manual + búsqueda +
extracción con IA + verificación). No lo ataques primero.

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
│   ├── redactor.py
│   ├── enviador.py
│   └── lector_bandeja.py
├── lib/
│   ├── sheets.py          # conexión y helpers de la Google Sheet
│   ├── gmail_client.py    # OAuth, enviar, leer
│   ├── claude_client.py   # wrapper llamadas a Claude API
│   └── telegram.py        # notificaciones
├── data/
│   └── epk_bakandeya.json # bio, links, rider técnico, caché objetivo, disponibilidad
├── .github/workflows/
│   ├── scout.yml
│   ├── redactor.yml
│   ├── enviador.yml
│   └── lector_bandeja.yml
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
| `fecha_envio` | date | |
| `fecha_ultima_respuesta` | date | |
| `notas` | text | |

## Reglas innegociables (no las rompas aunque Diego tenga prisa)

1. Ningún email sale sin aprobación humana explícita (cambio manual de estado a `aprobado`).
2. Ningún lead pasa a `aprobado` sin que el email de contacto esté verificado.
3. Rate limiting propio al buscar/scrapear — no dispares peticiones en bucle sin pausas.
4. Nunca hardcodear credenciales — todo vía variables de entorno (`.env`, `.env.example` sin valores reales).
5. Cumplimiento RGPD básico: solo se contactan datos de contacto profesionales de la sala/festival, nunca datos personales fuera de ese contexto.

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

- [ ] Fase 0 — Contactos, playbook y EPK de Filgue volcados
- [x] `redactor.py` funcionando con EPK real y adaptado a Salas, Festivales y Ayuntamientos con variedad y traducción automática
- [x] Bug del `ASUNTO:` en `enviador.py` arreglado (el asunto generado ya no se cuela en el cuerpo)
- [x] `enviador.py` + Gmail OAuth real funcionando y probado (se generó `token.json` y crea borradores en Gmail de verdad)
- [x] `scout.py` — versión semilla manual + enriquecimiento adaptada a Salas, Festivales y Ayuntamientos
- [x] Scout robustecido — salida estructurada (JSON mode) + anti-alucinación (confianza/fuente)
- [x] `lector_bandeja.py` funcionando (clasifica con Gemini Flash)
- [x] Máquina de estados (`lib/estados.py`) con grafo de transiciones válidas y soporte para regeneración de pitches
- [x] Workflows de GitHub Actions configurados con los secretos del repositorio
- [ ] Primeras pruebas con salas reales (envío de los primeros borradores aprobados)

> **Documentación:** el funcionamiento completo del sistema (arquitectura basada en estado,
> ciclo de vida del lead, rol de cada agente) está explicado en `docs/como_funciona.md`. Deuda
> técnica conocida y priorizada en `docs/guia_mantenimiento.md` (sección 9).
>
> **Siguiente paso:** Revisar los borradores generados en tu bandeja de Gmail, cambiar el estado
> de las salas de tu interés a `aprobado` en la Google Sheet y ejecutar `enviador.py` en modo real.
