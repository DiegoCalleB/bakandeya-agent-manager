import sys
import os
import re
import json
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.sheets as sheets
import lib.gmail_client as gmail_client
import lib.gemini_client as gemini_client
import lib.telegram as telegram
import lib.estados as estados
import lib.metricas as metricas
import lib.bandas as bandas

BAND_ID_DEFAULT = sheets.BAND_ID_DEFAULT

_RE_IMPORTE = re.compile(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(?:€|eur|euros)", re.IGNORECASE)


def _extraer_importe_eur(texto):
    """
    Extracción best-effort de un importe en euros de un texto libre (p. ej. 'oferta_economica'
    generada por Gemini a partir de la respuesta). Solo para ANOTAR el importe frente a los
    umbrales de autonomía de la banda — nunca para decidir ni actuar automáticamente. Si no
    encuentra un patrón claro de "número + €/eur/euros", devuelve None sin intentar adivinar.
    """
    if not texto:
        return None
    m = _RE_IMPORTE.search(texto)
    if not m:
        return None
    crudo = m.group(1)
    # Normalizar formato español (1.500,50) o con coma decimal (500,00) a float.
    if "," in crudo and "." in crudo:
        crudo = crudo.replace(".", "").replace(",", ".")
    elif "," in crudo:
        crudo = crudo.replace(",", ".")
    try:
        return float(crudo)
    except ValueError:
        return None

_RE_NOMBRE_REMITENTE = re.compile(r'^"?([^"<]+?)"?\s*<[^>]+>$')


def _extraer_nombre_remitente(remitente):
    """
    Extrae el nombre visible de una cabecera 'From' tipo 'Nombre Apellido <email@dominio.com>'.
    Si no hay nombre (solo la dirección), devuelve el email tal cual.
    """
    if not remitente:
        return ""
    m = _RE_NOMBRE_REMITENTE.match(remitente.strip())
    return m.group(1).strip() if m else remitente.strip()


def _cargar_filas_esperando(nombre_hoja, band_id):
    """
    Devuelve las filas de `nombre_hoja` DE UNA BANDA concreta en estado 'esperando_respuesta'/
    'interesado'/'negociando', junto con el propio nombre_hoja, para poder distinguir el origen
    al escribir de vuelta (leads.transicionar/registrar_mensaje_hilo necesitan saber en qué hoja
    está la fila).
    """
    filas = (
        sheets.obtener_leads(estado=estados.ESPERANDO, nombre_hoja=nombre_hoja) +
        sheets.obtener_leads(estado=estados.INTERESADO, nombre_hoja=nombre_hoja) +
        sheets.obtener_leads(estado=estados.NEGOCIANDO, nombre_hoja=nombre_hoja)
    )
    filas = [f for f in filas if (f.get("band_id") or BAND_ID_DEFAULT) == band_id]
    return [(fila, nombre_hoja) for fila in filas]


def procesar_bandeja_entrada():
    """
    Multi-tenant: recorre las bandas activas de 'registro_bandas' y, para cada una, lee SU
    PROPIA bandeja de Gmail (cada banda tiene su propio email conectado — ya no hay una única
    bandeja compartida entre bandas) y la empareja solo contra las filas de ESA banda que
    estaban esperando respuesta. Clasifica con Gemini y actualiza la hoja correspondiente.
    """
    print("[lector_bandeja.py] Iniciando lectura de respuestas...")
    total_clasificados = 0
    for banda in bandas.listar_bandas_activas():
        band_id = banda.get("band_id") or BAND_ID_DEFAULT
        nombre_banda = banda.get("nombre_banda") or band_id
        total_clasificados += _procesar_bandeja_de_banda(band_id, nombre_banda)

    print(f"[lector_bandeja.py] Lectura finalizada. Respuestas clasificadas: {total_clasificados}")
    return total_clasificados


def _procesar_bandeja_de_banda(band_id, nombre_banda):
    """Lee y clasifica las respuestas nuevas de la bandeja de Gmail de UNA banda concreta."""
    respuestas = gmail_client.leer_respuestas(band_id=band_id)
    if not respuestas:
        print(f"[lector_bandeja.py] Banda '{nombre_banda}' ({band_id}): sin respuestas nuevas.")
        return 0

    filas_esperando = (
        _cargar_filas_esperando("leads", band_id) + _cargar_filas_esperando("medios_scout", band_id)
    )
    clasificados = 0

    for respuesta in respuestas:
        remitente = respuesta.get("remitente")
        cuerpo = respuesta.get("cuerpo")

        # Intentar emparejar la respuesta con una fila esperando respuesta por email
        lead_asociado = None
        nombre_hoja_asociada = "leads"
        for fila, nombre_hoja in filas_esperando:
            email_lead = fila.get("email_contacto")
            if email_lead and email_lead.lower() in remitente.lower():
                lead_asociado = fila
                nombre_hoja_asociada = nombre_hoja
                break

        if not lead_asociado:
            # Si el email no coincide con ninguna fila esperando de esta banda, se omite
            continue

        es_medios = nombre_hoja_asociada == "medios_scout"
        lead_id = lead_asociado.get("id")
        nombre_sala = lead_asociado.get("nombre_medio") if es_medios else lead_asociado.get("nombre_sala")

        print(f"[lector_bandeja.py] Nueva respuesta de '{nombre_sala}' ({remitente}) para la banda '{nombre_banda}'. Clasificando...")

        contexto_original = (
            "un medio de comunicación a nuestro contacto de prensa" if es_medios
            else "un local/festival a nuestra propuesta de concierto"
        )
        prompt = (
            f"Analiza la siguiente respuesta recibida de {contexto_original}:\n\n"
            f"Asunto: {respuesta.get('asunto')}\n"
            f"Cuerpo:\n{cuerpo}\n\n"
            "Devuelve un objeto JSON estructurado con las siguientes claves:\n"
            "1. 'categoria': una de estas tres opciones estrictas: 'interesado', 'no_interesado', 'negociando'.\n"
            "2. 'fecha_propuesta': fecha o rango de fechas mencionado (de concierto, o de entrevista/publicación si es un medio), o null si no proponen fechas.\n"
            "3. 'oferta_economica': condiciones de caché, taquilla o entrada mencionadas (ej. '80% taquilla (10€ entrada)', 'caché fijo 500€', 'entrada libre'), o null si no especifican dinero (lo normal si es un medio de comunicación).\n"
            "4. 'resumen': síntesis de 1-2 frases del mensaje en tono claro y directo.\n"
        )

        system_prompt = (
            f"Eres un analista experto de respuestas de booking y de prensa para la banda de música {nombre_banda}. "
            "Devuelve únicamente un objeto JSON válido con el esquema exacto solicitado."
        )

        # Gemini 2.5 Flash en modo JSON para análisis rápido y estructurado
        json_str = gemini_client.generar_texto_gemini(
            prompt, 
            model_name="gemini-2.5-flash", 
            system_instruction=system_prompt,
            temperature=0.1,
            forzar_json=True
        )
        
        datos_analizados = {}
        if json_str:
            try:
                datos_analizados = json.loads(json_str)
            except Exception as e:
                print(f"[lector_bandeja.py] Error al parsear JSON de Gemini: {e}. Respuesta: {json_str}")
        
        categoria = (datos_analizados.get("categoria") or "").strip().lower()
        if categoria not in ["interesado", "no_interesado", "negociando"]:
            if "no" in categoria or "descart" in categoria:
                categoria = "no_interesado"
            elif "nego" in categoria:
                categoria = "negociando"
            else:
                categoria = "interesado"

        fecha_propuesta = datos_analizados.get("fecha_propuesta")
        oferta_economica = datos_analizados.get("oferta_economica")
        resumen = datos_analizados.get("resumen") or cuerpo[:200].replace("\n", " ")

        # Nivel de autonomía definido por la banda (config_autonomia): solo se usa para ANOTAR
        # la oferta frente a sus umbrales de caché, nunca para aceptar/rechazar en automático —
        # la aprobación humana de cualquier respuesta sigue siendo obligatoria (regla innegociable).
        aviso_autonomia = ""
        if categoria == "negociando" and oferta_economica and not es_medios:
            autonomia = bandas.cargar_autonomia_banda(band_id)
            importe = _extraer_importe_eur(oferta_economica)
            if importe is not None:
                if importe < autonomia["cache_minimo"]:
                    aviso_autonomia = f" ⚠️ Por debajo del caché mínimo definido por la banda ({autonomia['cache_minimo']}€)."
                elif importe > autonomia["cache_objetivo"]:
                    aviso_autonomia = f" 🎉 Por encima del caché objetivo de la banda ({autonomia['cache_objetivo']}€)."

        detalles_extra = []
        if fecha_propuesta:
            detalles_extra.append(f"Fecha: {fecha_propuesta}")
        if oferta_economica:
            detalles_extra.append(f"Oferta: {oferta_economica}{aviso_autonomia}")
        str_extra = f" [{', '.join(detalles_extra)}]" if detalles_extra else ""

        notas = f"Respuesta recibida ({respuesta.get('fecha')}){str_extra}: {resumen}"

        estados.transicionar(lead_asociado, categoria, notas=notas, nombre_hoja=nombre_hoja_asociada)

        sheets.registrar_mensaje_hilo(
            lead_id, nombre_sala, respuesta.get("fecha"),
            remitente="sala", remitente_nombre=_extraer_nombre_remitente(remitente),
            asunto=respuesta.get("asunto"), mensaje=cuerpo, mensaje_id=respuesta.get("id")
        )
        gmail_client.marcar_como_leido(respuesta.get("id"), band_id=band_id)

        ciudad_lead = lead_asociado.get("ciudad") or lead_asociado.get("region") or ""
        ciudad_str = f" ({ciudad_lead})" if ciudad_lead else ""
        etiqueta = "Medio" if es_medios else "Recinto"
        titulo_interes = "¡NUEVO INTERÉS DE COBERTURA!" if es_medios else "¡NUEVO INTERÉS / NEGOCIACIÓN DE BOLO!"

        if categoria in ["interesado", "negociando"]:
            msg_telegram = (
                f"🎉 *{titulo_interes}*\n\n"
                f"🎸 *Banda:* {nombre_banda}\n"
                f"🏛️ *{etiqueta}:* {nombre_sala}{ciudad_str}\n"
                f"📊 *Estado:* {categoria.upper()}\n"
            )
            if fecha_propuesta:
                msg_telegram += f"📅 *Fecha propuesta:* {fecha_propuesta}\n"
            if oferta_economica:
                msg_telegram += f"💰 *Oferta / Condiciones:* {oferta_economica}{aviso_autonomia}\n"
            msg_telegram += f"📝 *Resumen:* {resumen}\n\n"
            msg_telegram += f"💡 *El asistente creará un borrador de respuesta contextualizado.*\n\n"
            msg_telegram += metricas.formatear_pie_kpis_telegram()
        else:
            msg_telegram = (
                f"❌ *Respuesta de {nombre_sala}{ciudad_str}*\n"
                f"📊 *Estado:* NO INTERESADO / DESCARTADO\n"
                f"📝 *Resumen:* {resumen}"
            )

        telegram.enviar_notificacion_telegram(msg_telegram)
        clasificados += 1

    return clasificados

if __name__ == "__main__":
    procesar_bandeja_entrada()
