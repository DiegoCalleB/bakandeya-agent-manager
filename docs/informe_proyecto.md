# Informe del Proyecto — Bakandeya Agent Manager

Este documento detalla la visión general, fases del proyecto, costes operativos estimativos, modelo económico y arquitectura de **Bakandeya Agent Manager**.

---

## 1. Resumen Ejecutivo

**Bakandeya Agent Manager** es un sistema de agentes de Inteligencia Artificial enfocado en automatizar la prospección, redacción de propuestas (pitches) personalizadas, envío asistido y seguimiento de oportunidades de contratación musical (salas, festivales y ayuntamientos) para la banda **Bakandeya**.

El sistema **no sustituye el criterio ni la negociación humana**, sino que elimina la carga operativa repetitiva (búsqueda de contactos, redacción de correos base, clasificación de respuestas) manteniendo siempre el control final en manos de la banda/management.

---

## 2. Objetivos del Proyecto

- **Aumento de alcance y eficiencia:** Multiplicar por 10 el número de salas, festivales y ayuntamientos contactados por semana sin aumentar las horas dedicadas al trabajo administrativo.
- **Personalización asistida por IA:** Generar propuestas contextualizadas (adaptadas al tipo de recinto, provincia, influencias del EPK) mediante IA en lugar de plantillas genéricas.
- **Control humano estricto (Human-in-the-Loop):** Garantizar que **ningún correo sale sin aprobación explícita** y sin que los datos de contacto estén previamente verificados.
- **Arquitectura de bajo coste y mantenimiento mínimo:** Sin servidor encendido 24h ni infraestructuras complejas; la orquestación recae en el estado de una hoja de Google Sheets y tareas programadas en GitHub Actions.

---

## 3. Fases del Proyecto

### Fase 1 — MVP Interno (Fase Actual)
- **Alcance:** Validación exclusiva e interna para la banda **Bakandeya**.
- **Stack:** Python 3.11+, Google Sheets (`gspread`), Gmail API, Gemini API (Flash), Telegram Bot API y GitHub Actions.
- **Criterio de éxito para avanzar a Fase 2:** Demostrar el cierre de bolos reales contratados a través del pipeline durante una prueba continua de **4 a 6 semanas**.
- **Regla de oro:** No construir nada de multi-tenant, paneles web ni pasarelas de pago hasta validar la conversión de bolos en esta fase.

### Fase 2 — Plataforma Multi-tenant (SaaS para Managers y Bandas)
- **Alcance:** Expansión del sistema para servir a múltiples bandas y agencias de booking externas.
- **Componentes a incorporar:**
  - **Base de datos multi-tenant:** Migración de Google Sheets a PostgreSQL / Supabase.
  - **Dashboard Web:** Interfaz gráfica para gestión de leads y aprobación rápida de pitches.
  - **Monetización:** Integración con Stripe para suscripciones SaaS.
  - **Multi-cuenta Email/OAuth:** Gestión de credenciales por usuario/banda.

---

## 4. Arquitectura y Componentes Técnicos (Fase 1)

```
                    ┌─────────────────────────┐
                    │ DuckDuckGo + Web Search │
                    └────────────┬────────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │  scout_descubridor.py │ (Genera leads 'nuevo')
                     └───────────┬───────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │        scout.py       │ (Enriquece datos de contacto)
                     └───────────┬───────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      redactor.py      │ (Genera pitch según EPK)
                     └───────────┬───────────┘
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │ Google Sheet (Estado: nuevo) │
                 └───────────────┬───────────────┘
                                 │
                   [ REVISIÓN Y APROBACIÓN HUMANA ]
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │ Google Sheet (Estado: aprobado)│
                 └───────────────┬───────────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      enviador.py      │ (Borrador/Envío por Gmail)
                     └───────────┬───────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │   lector_bandeja.py   │ (Clasifica respuestas)
                     └───────────────────────┘
```

---

## 5. Modelo Económico y Estimación de Costes

El diseño del sistema prioriza un consumo de recursos **prácticamente nulo en estado de reposo** y extremadamente económico durante la ejecución:

| Componente | Servicio / Proveedor | Coste estimado (Fase 1) | Notas |
|---|---|---|---|
| **Orquestación & Ejecución** | GitHub Actions | **0,00 € / mes** | Incluido en la cuota gratuita de GitHub (2.000 min/mes). |
| **Almacenamiento de Datos** | Google Sheets API | **0,00 € / mes** | Uso vía Service Account bajo cuota gratuita de Google Workspace/Cloud. |
| **Modelos de IA** | Gemini API (`gemini-2.5-flash`) | **< 1,00 € - 3,00 € / mes** | Extracción JSON estructurada y redacción con coste marginal muy bajo por cada 1.000 tokens. |
| **Envío & Lectura Email** | Gmail API (OAuth) | **0,00 € / mes** | Reutiliza la cuenta de Gmail asignada a la banda. |
| **Notificaciones** | Telegram Bot API | **0,00 € / mes** | Uso gratuito e ilimitado para mensajes operativos al manager. |
| **TOTAL ESTIMADO FASE 1** | | **< 3,00 € / mes** | Coste directo de llamadas a la API de Inteligencia Artificial. |

---

## 6. Gobernanza, Control Humano y Cumplimiento (RGPD)

1. **Aprobación Humana Obligatoria:** Ningún correo electrónico se envía automáticamente a salas o festivales sin que la columna `estado` en la Google Sheet sea cambiada manualmente a `aprobado`.
2. **Verificación de Contactos:** Se aplica filtrado estricto (datos de alta confianza o validados) antes de permitir que un lead pase al flujo de edición.
3. **Cumplimiento RGPD:** La prospección se limita exclusivamente a datos de contacto profesionales y públicos de entidades (salas de conciertos, festivales, comisiones de fiestas de ayuntamientos), respetando la normativa de comunicaciones comerciales B2B.

---

## 7. Referencias

- **Visión conceptual y flujo:** [`docs/como_funciona.md`](como_funciona.md)
- **Manual de mantenimiento técnico:** [`docs/guia_mantenimiento.md`](guia_mantenimiento.md)
- **Reglas del proyecto y convenciones:** [`AGENTS.md`](../AGENTS.md)
