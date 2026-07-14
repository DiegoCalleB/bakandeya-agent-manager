"""
Máquina de estados del pipeline de leads — la "coordinación" del sistema.

Recordatorio de arquitectura: no hay un proceso orquestador. El `estado` de cada fila en la
Google Sheet ES el orquestador (ver docs/como_funciona.md). Este módulo es la ÚNICA fuente de
verdad de qué estados existen y qué transiciones son legales, para que ningún agente escriba un
estado arbitrario ni deje leads atascados en bucles.

Uso desde un agente:
    import lib.estados as estados
    estados.transicionar(lead, estados.PENDIENTE, notas="...", pitch="...")
"""

import lib.sheets as sheets

# --- Estados canónicos -----------------------------------------------------------------------
ANTIGUO = "antiguo"          # leads precargados a mano, fuera del pipeline hasta normalizar
NUEVO = "nuevo"              # recién descubierto o pendiente de enriquecer
SIN_CONTACTO = "sin_contacto"  # el scout no encontró email tras búsqueda exhaustiva (terminal)
PENDIENTE = "pendiente_aprobacion"  # pitch redactado, esperando el OK humano
APROBADO = "aprobado"        # Diego aprobó a mano: listo para enviar
ESPERANDO = "esperando_respuesta"   # email/borrador enviado, esperando respuesta de la sala
INTERESADO = "interesado"
NO_INTERESADO = "no_interesado"
NEGOCIANDO = "negociando"    # entra negociación real: la gestiona un humano
DESCARTADO = "descartado"    # terminal, fuera del embudo

# --- Grafo de transiciones válidas -----------------------------------------------------------
# {estado_actual: {estados_a_los_que_puede_pasar}}.
TRANSICIONES = {
    ANTIGUO: {NUEVO, DESCARTADO},
    NUEVO: {NUEVO, PENDIENTE, SIN_CONTACTO, DESCARTADO},
    SIN_CONTACTO: {NUEVO, DESCARTADO},  # se reintenta si más adelante aparece un contacto
    PENDIENTE: {APROBADO, NUEVO, DESCARTADO, SIN_CONTACTO},  # a NUEVO si el humano rechaza el pitch
    APROBADO: {ESPERANDO, DESCARTADO},
    ESPERANDO: {INTERESADO, NO_INTERESADO, NEGOCIANDO},
    INTERESADO: {NEGOCIANDO, DESCARTADO},
    NEGOCIANDO: {INTERESADO, NO_INTERESADO, DESCARTADO},
    NO_INTERESADO: {DESCARTADO},
    DESCARTADO: set(),
}

# Conjunto de todos los estados conocidos (claves + destinos).
ESTADOS_VALIDOS = set(TRANSICIONES) | {e for destinos in TRANSICIONES.values() for e in destinos}


def es_transicion_valida(estado_actual, nuevo_estado):
    """Devuelve True si pasar de `estado_actual` a `nuevo_estado` está permitido por el grafo."""
    estado_actual = (estado_actual or "").strip()
    if estado_actual == nuevo_estado:
        return True
    return nuevo_estado in TRANSICIONES.get(estado_actual, set())


def transicionar(lead, nuevo_estado, notas=None, pitch=None):
    """
    Cambia el estado de un lead validándolo contra el grafo de transiciones.

    `lead` es el dict de la fila (debe tener 'id' y 'estado'). Si la transición no es válida,
    NO escribe nada, loguea el intento y devuelve False — así un bug en un agente no puede
    llevar un lead a un estado imposible.
    """
    lead_id = lead.get("id")
    estado_actual = (lead.get("estado") or "").strip()

    if nuevo_estado not in ESTADOS_VALIDOS:
        print(f"[estados] Estado desconocido '{nuevo_estado}' — ignorado (lead {lead_id}).")
        return False

    if not es_transicion_valida(estado_actual, nuevo_estado):
        print(f"[estados] Transición inválida ignorada: '{estado_actual}' -> '{nuevo_estado}' (lead {lead_id}).")
        return False

    print(f"[estados] {lead_id}: {estado_actual} -> {nuevo_estado}")
    
    # Si pasa a ESPERANDO, también registramos la fecha de envío actual automáticamente
    if nuevo_estado == ESPERANDO:
        from datetime import datetime
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        datos = {"estado": nuevo_estado, "fecha_envio": fecha_hoy}
        if pitch is not None:
            datos["pitch_generado"] = pitch
        if notas is not None:
            datos["notas"] = notas
        return sheets.actualizar_datos_lead(lead_id, datos)
        
    return sheets.actualizar_estado_lead(lead_id, nuevo_estado, pitch=pitch, notas=notas)
