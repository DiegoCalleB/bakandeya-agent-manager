import sys
import os
from datetime import datetime
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.sheets as sheets
import lib.gmail_client as gmail_client
import lib.telegram as telegram
import lib.estados as estados
import lib.bandas as bandas

BAND_ID_DEFAULT = sheets.BAND_ID_DEFAULT

# Dossier real en PDF: se adjunta directo al borrador en vez de depender de un link de Drive
# que puede no estar compartido públicamente.
RUTA_DOSSIER_PDF = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "Dossier Bakandeya.pdf"
)


def parsear_pitch(pitch, nombre_sala, asunto_generico=None):
    """
    Separa el pitch generado por el redactor en (asunto, cuerpo).

    El redactor devuelve siempre el formato:  ``ASUNTO: <asunto>\\n\\n<cuerpo>``.
    Aquí extraemos ese asunto para usarlo como asunto REAL del email, en vez de tirarlo
    y dejar la línea 'ASUNTO: ...' colgando dentro del cuerpo (que era el bug).

    Degradación segura: si por lo que sea el pitch no trae el marcador ``ASUNTO:``, se usa
    un asunto genérico y el pitch completo como cuerpo. Nunca falla.
    """
    if asunto_generico is None:
        asunto_generico = f"Propuesta de concierto: Bakandeya en {nombre_sala}"
    if not pitch:
        return asunto_generico, ""

    texto = pitch.strip()
    # Separamos solo en la primera línea: el resto es el cuerpo tal cual.
    primera_linea, _, resto = texto.partition("\n")

    if primera_linea.strip().upper().startswith("ASUNTO:"):
        asunto = primera_linea.split(":", 1)[1].strip().strip('"').strip()
        cuerpo = resto.strip()
        return (asunto or asunto_generico), cuerpo

    # Sin marcador reconocible: no arriesgamos, mandamos todo como cuerpo.
    return asunto_generico, texto


def enviar_leads_aprobados(nombre_hoja="leads", band_id=BAND_ID_DEFAULT):
    """
    Busca filas en estado 'aprobado' en `nombre_hoja` ('leads' o 'medios_scout') DE UNA BANDA
    concreta (multi-tenant: filtra por 'band_id'). Crea un borrador en Gmail con el pitch
    generado y cambia el estado a 'esperando_respuesta'. Notifica por Telegram.

    IMPORTANTE (decisión explícita de Diego, 2026-08-10): cada banda envía SIEMPRE desde su
    propio email oficial — su propia cuenta de Gmail conectada por OAuth (ver
    lib/gmail_client.py::obtener_servicio_gmail). Nunca un buzón compartido entre bandas ni el
    email personal de un usuario. Antes de crear ningún borrador se verifica que la cuenta
    conectada para `band_id` coincide con el email oficial de esa banda en su EPK — si no
    coincide (o no hay ninguna cuenta conectada todavía), NO se envía nada para esa banda: es
    preferible no enviar a enviar desde la mailbox equivocada.
    """
    es_medios = nombre_hoja == "medios_scout"
    print(f"[enviador.py] Iniciando creación de borradores para '{nombre_hoja}' aprobados (banda: {band_id})...")
    leads = sheets.obtener_leads(estado=estados.APROBADO, nombre_hoja=nombre_hoja)
    leads = [l for l in leads if (l.get("band_id") or BAND_ID_DEFAULT) == band_id]
    enviados = 0

    if not leads:
        print(f"[enviador.py] No hay filas 'aprobado' para la banda '{band_id}' en '{nombre_hoja}'.")
        return 0

    epk = bandas.cargar_epk_banda(band_id)
    nombre_firma = (epk.get("contacto") or {}).get("nombre") or "el equipo de management"
    email_oficial = (epk.get("contacto") or {}).get("email")

    email_conectado = gmail_client.obtener_email_conectado(band_id)
    if email_oficial and email_conectado and email_conectado.strip().lower() != email_oficial.strip().lower():
        msg = (
            f"⚠️ La cuenta de Gmail conectada para '{band_id}' ({email_conectado}) no coincide con "
            f"su email oficial en el EPK ({email_oficial}). No se ha enviado ningún borrador — "
            "revisa qué cuenta se conectó antes de reintentar."
        )
        print(f"[enviador.py] {msg}")
        telegram.enviar_notificacion_telegram(msg)
        return 0
    if email_oficial and not email_conectado:
        print(f"[enviador.py] La banda '{band_id}' ({email_oficial}) todavía no tiene su Gmail conectado (o está en modo simulado). Sin borradores.")
        if not gmail_client.es_modo_simulado():
            return 0

    for lead in leads:
        lead_id = lead.get("id")
        email = lead.get("email_contacto")
        nombre = lead.get("nombre_medio") if es_medios else lead.get("nombre_sala")
        pitch = lead.get("pitch_generado")

        if not email or not pitch:
            print(f"[enviador.py] Fila {lead_id} ({nombre}) no tiene email de contacto o pitch generado. Se omite.")
            continue

        asunto_generico = f"{epk.get('nombre') or 'Bakandeya'} - contacto de prensa" if es_medios else None
        asunto, cuerpo = parsear_pitch(pitch, nombre, asunto_generico=asunto_generico)
        print(f"[enviador.py] Creando borrador en Gmail para {email} (asunto: {asunto})...")

        ruta_adjunto = RUTA_DOSSIER_PDF if os.path.exists(RUTA_DOSSIER_PDF) else None
        res = gmail_client.crear_borrador(email, asunto, cuerpo, ruta_adjunto=ruta_adjunto, epk=epk)
        if res:
            estados.transicionar(lead, estados.ESPERANDO, nombre_hoja=nombre_hoja)
            mensaje_id = (res.get("message") or {}).get("id") or res.get("id")
            sheets.registrar_mensaje_hilo(
                lead_id, nombre, datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                remitente="banda", remitente_nombre=nombre_firma,
                asunto=asunto, mensaje=cuerpo, mensaje_id=mensaje_id
            )
            etiqueta = "Medio" if es_medios else "Recinto"
            msg_tg = (
                f"📝 *BORRADOR DE PROPOSAL CREADO EN GMAIL*\n\n"
                f"🎸 *Banda:* {epk.get('nombre') or band_id}\n"
                f"🏛️ *{etiqueta}:* {nombre} ({email})\n"
                f"✉️ *Asunto:* {asunto}\n"
                f"✍️ *Firmado por:* {nombre_firma}\n"
                f"📌 *Estado:* ESPERANDO RESPUESTA\n\n"
                f"💡 *El borrador está disponible en tu Gmail para que lo revises antes de enviarlo.*"
            )
            telegram.enviar_notificacion_telegram(msg_tg)
            enviados += 1

    print(f"[enviador.py] Creación de borradores finalizada. Total borradores creados: {enviados}")
    return enviados


def enviar_todas_las_bandas(medios=False):
    """
    Punto de entrada multi-tenant por defecto: recorre 'registro_bandas' (solo cuentas activas)
    y ejecuta enviar_leads_aprobados para cada una. Con solo band-bakandeya registrada (caso
    single-tenant original), el comportamiento es idéntico al de antes.
    """
    total = 0
    nombre_hoja = "medios_scout" if medios else "leads"
    for banda in bandas.listar_bandas_activas():
        band_id = banda.get("band_id") or BAND_ID_DEFAULT
        nombre_banda = banda.get("nombre_banda") or band_id
        print(f"[enviador.py] === Banda: {nombre_banda} ({band_id}) ===")
        total += enviar_leads_aprobados(nombre_hoja=nombre_hoja, band_id=band_id)
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agente Enviador de borradores de leads o medios aprobados.")
    parser.add_argument("--medios", action="store_true", help="Procesar la hoja 'medios_scout' en vez de 'leads'.")
    parser.add_argument("--banda", type=str, default=None, help="band_id concreto a procesar. Si se omite, procesa todas las bandas activas de 'registro_bandas'.")
    args = parser.parse_args()

    if args.banda:
        enviar_leads_aprobados(nombre_hoja="medios_scout" if args.medios else "leads", band_id=args.banda)
    else:
        enviar_todas_las_bandas(medios=args.medios)
