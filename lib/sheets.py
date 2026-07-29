import os
import gspread
from dotenv import load_dotenv

load_dotenv()

# Nombre del documento de Sheets por defecto
DOCUMENTO_SHEETS = os.getenv("GOOGLE_SHEETS_DOCUMENT", "Bakandeya Leads")

# Pestaña donde se registra cada mensaje (enviado o recibido) del hilo de conversación de un
# lead. Su esquema lo define la app externa de dashboard (Bakandeya_AIStudio_Application,
# server.ts) que también la lee — no cambies el orden de las columnas sin avisar allí también.
NOMBRE_HOJA_HILOS = "hilos_emails"
CABECERAS_HILOS = ["id", "lead_id", "nombre_sala", "fecha", "remitente", "remitente_nombre", "asunto", "mensaje"]

def obtener_cliente_sheets():
    """
    Autentica con la Service Account de Google Sheets, ya sea usando el archivo
    en GOOGLE_APPLICATION_CREDENTIALS o construyendo las credenciales dinámicamente
    desde las variables de entorno si están disponibles (ideal para GitHub Actions).
    """
    # 1. Intentar con variables de entorno individuales (evita depender de archivos físicos en CI)
    email = os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL")
    private_key = os.getenv("GOOGLE_PRIVATE_KEY")
    
    if email and private_key:
        try:
            # Limpiar la clave privada (reemplazar saltos de línea literales \n por reales)
            clean_key = private_key.replace("\\n", "\n").replace("\n", "\n")
            # Si contiene saltos de línea reales escapados, los normalizamos
            if "\\n" in clean_key:
                clean_key = clean_key.replace("\\n", "\n")
            
            # Asegurar que los delimitadores PEM estén presentes
            if "-----BEGIN PRIVATE KEY-----" not in clean_key:
                # Si viene en formato simple, recomponer
                clean_key = "-----BEGIN PRIVATE KEY-----\n" + clean_key.replace(" ", "\n") + "\n-----END PRIVATE KEY-----"
            
            info = {
                "type": "service_account",
                "project_id": "bakandeya-booking",
                "private_key": clean_key,
                "client_email": email,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{email}"
            }
            return gspread.service_account_from_dict(info)
        except Exception as e:
            print(f"[sheets.py] Fallo de autenticación directa con diccionario: {e}. Probando método tradicional...")
            
    # 2. Método tradicional por archivo
    credenciales_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credenciales_path:
        raise ValueError("La variable de entorno GOOGLE_APPLICATION_CREDENTIALS no está configurada")
    return gspread.service_account(filename=credenciales_path)

def obtener_leads(estado=None):
    """
    Lee todas las filas de la hoja 'leads'. Si se especifica 'estado',
    filtra y devuelve solo las filas que coincidan con ese estado.
    """
    try:
        client = obtener_cliente_sheets()
        sheet = client.open(DOCUMENTO_SHEETS).worksheet("leads")
        # numericise_ignore=['all']: gspread por defecto intenta convertir celdas "numéricas" a
        # int/float. Un id hexadecimal como "499e3100" (de una importación antigua sin prefijo
        # "lead_") se lee como notación científica y desborda a float('inf'), rompiendo cualquier
        # búsqueda posterior por ese id. Nada del código depende de que 'aforo' llegue ya
        # convertido (se castea con int() donde hace falta), así que es seguro leer todo como texto.
        datos = sheet.get_all_records(numericise_ignore=['all'])
        
        if estado:
            return [row for row in datos if row.get("estado") == estado]
        return datos
    except Exception as e:
        print(f"Error al obtener leads de Google Sheets: {e}")
        return []

def actualizar_datos_lead(lead_id, datos_dict):
    """
    Actualiza campos específicos de un lead en la hoja de cálculo.
    datos_dict es un diccionario con claves como: 'estado', 'pitch_generado', 'email_contacto', 'telefono', 'website', 'instagram', 'aforo', 'contacto_nombre', 'contexto_extra', 'notas'.
    """
    try:
        client = obtener_cliente_sheets()
        sheet = client.open(DOCUMENTO_SHEETS).worksheet("leads")
        
        celda = sheet.find(str(lead_id), in_column=1)
        if not celda:
            print(f"Lead con ID {lead_id} no encontrado en la hoja.")
            return False
            
        fila = celda.row
        
        # Obtener mapeo dinámico de cabeceras
        headers = sheet.row_values(1)
        
        # Si se solicita actualizar el tipo y no existe la columna, la creamos al lado de genero
        if "tipo" in datos_dict and "tipo" not in headers:
            print("[sheets.py] Columna 'tipo' no encontrada. Insertándola automáticamente...")
            idx_genero = headers.index("genero") if "genero" in headers else (headers.index("email_contacto") - 1 if "email_contacto" in headers else 5)
            # Insertar columna 'tipo' a la derecha de genero
            sheet.insert_cols([["tipo"]], col=idx_genero + 2)
            # Recargar cabeceras actualizadas
            headers = sheet.row_values(1)
            
        # Si se solicita actualizar el teléfono y no existe la columna, la creamos al lado de email_contacto
        if "telefono" in datos_dict and "telefono" not in headers:
            print("[sheets.py] Columna 'telefono' no encontrada. Insertándola automáticamente...")
            idx_email = headers.index("email_contacto") if "email_contacto" in headers else 6
            # Insertar columna 'telefono' a la derecha de email_contacto
            sheet.insert_cols([["telefono"]], col=idx_email + 2)
            # Recargar cabeceras actualizadas
            headers = sheet.row_values(1)
            
        # Si se solicita actualizar instagram y no existe la columna, la creamos al lado de telefono
        if "instagram" in datos_dict and "instagram" not in headers:
            print("[sheets.py] Columna 'instagram' no encontrada. Insertándola automáticamente...")
            idx_tel = headers.index("telefono") if "telefono" in headers else (headers.index("email_contacto") + 1 if "email_contacto" in headers else 7)
            # Insertar columna 'instagram' a la derecha de telefono
            sheet.insert_cols([["instagram"]], col=idx_tel + 2)
            # Recargar cabeceras actualizadas
            headers = sheet.row_values(1)

        # Si se solicita actualizar contacto_nombre y no existe la columna, la creamos al lado de instagram
        if "contacto_nombre" in datos_dict and "contacto_nombre" not in headers:
            print("[sheets.py] Columna 'contacto_nombre' no encontrada. Insertándola automáticamente...")
            idx_insta = headers.index("instagram") if "instagram" in headers else (headers.index("email_contacto") + 1 if "email_contacto" in headers else 8)
            sheet.insert_cols([["contacto_nombre"]], col=idx_insta + 2)
            headers = sheet.row_values(1)

        # Si se solicita actualizar contexto_extra y no existe la columna, la creamos al lado de notas
        if "contexto_extra" in datos_dict and "contexto_extra" not in headers:
            print("[sheets.py] Columna 'contexto_extra' no encontrada. Insertándola automáticamente...")
            idx_notas = headers.index("notas") if "notas" in headers else len(headers) - 1
            sheet.insert_cols([["contexto_extra"]], col=idx_notas + 1)
            headers = sheet.row_values(1)

        column_mapping = {header: idx + 1 for idx, header in enumerate(headers)}
        
        for key, val in datos_dict.items():
            if key in column_mapping and val is not None:
                sheet.update_cell(fila, column_mapping[key], val)
                
        return True
    except Exception as e:
        print(f"Error al actualizar datos del lead {lead_id}: {e}")
        return False

def actualizar_estado_lead(lead_id, nuevo_estado, pitch=None, notas=None):
    """
    Busca un lead por su 'id' y actualiza su estado, y opcionalmente
    el pitch generado y las notas asociadas.
    """
    datos = {"estado": nuevo_estado}
    if pitch is not None:
        datos["pitch_generado"] = pitch
    if notas is not None:
        datos["notas"] = notas
        
    return actualizar_datos_lead(lead_id, datos)

def _obtener_o_crear_hoja_hilos(client):
    """
    Devuelve la pestaña 'hilos_emails', creándola con sus cabeceras si todavía no existe
    (p. ej. primera vez que se registra un mensaje tras añadir esta funcionalidad).
    """
    documento = client.open(DOCUMENTO_SHEETS)
    try:
        return documento.worksheet(NOMBRE_HOJA_HILOS)
    except gspread.exceptions.WorksheetNotFound:
        print(f"[sheets.py] Pestaña '{NOMBRE_HOJA_HILOS}' no encontrada. Creándola...")
        hoja = documento.add_worksheet(title=NOMBRE_HOJA_HILOS, rows=1000, cols=len(CABECERAS_HILOS))
        hoja.append_row(CABECERAS_HILOS)
        return hoja


def registrar_mensaje_hilo(lead_id, nombre_sala, fecha, remitente, remitente_nombre, asunto, mensaje, mensaje_id=None):
    """
    Añade una fila a 'hilos_emails' con un mensaje del hilo de conversación de un lead
    (un pitch/borrador enviado, una respuesta de negociación nuestra, o una respuesta recibida
    de la sala/festival). `remitente` debe ser 'banda' o 'sala'.

    Esta hoja la consume también el dashboard externo (Bakandeya_AIStudio_Application) para
    mostrar el hilo completo — no toca ni depende de la hoja 'leads'.
    """
    try:
        client = obtener_cliente_sheets()
        hoja = _obtener_o_crear_hoja_hilos(client)

        # Evita duplicar la misma fila si el agente se reejecuta sobre el mismo mensaje
        # (p. ej. lector_bandeja.py reprocesando un email que no se marcó como leído a tiempo).
        if mensaje_id:
            ids_existentes = hoja.col_values(1)
            if mensaje_id in ids_existentes:
                return True

        from datetime import datetime
        fila_id = mensaje_id or f"em-{lead_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        hoja.append_row([fila_id, str(lead_id), nombre_sala or "", fecha or "", remitente, remitente_nombre or "", asunto or "", mensaje or ""])
        return True
    except Exception as e:
        print(f"Error al registrar mensaje de hilo para lead {lead_id}: {e}")
        return False


def crear_leads(lista_datos_dict):
    """
    Inserta múltiples leads en la hoja de cálculo 'leads' en una sola operación.
    Cada elemento de lista_datos_dict debe ser un diccionario con claves correspondientes a las columnas.
    """
    if not lista_datos_dict:
        print("[sheets.py] No hay leads para crear.")
        return True
    try:
        client = obtener_cliente_sheets()
        sheet = client.open(DOCUMENTO_SHEETS).worksheet("leads")
        
        # Obtener cabeceras actuales para mapear el orden de inserción
        headers = sheet.row_values(1)
        
        # Si 'tipo' no está en los headers de la hoja física, la insertamos dinámicamente antes
        # de crear leads, para asegurar que no perdemos el campo tipo.
        if "tipo" not in headers:
            print("[sheets.py] Columna 'tipo' no encontrada al crear leads. Insertándola automáticamente...")
            idx_genero = headers.index("genero") if "genero" in headers else (headers.index("email_contacto") - 1 if "email_contacto" in headers else 5)
            sheet.insert_cols([["tipo"]], col=idx_genero + 2)
            headers = sheet.row_values(1)
            
        rows_to_append = []
        for datos_dict in lista_datos_dict:
            row_values = []
            for header in headers:
                row_values.append(datos_dict.get(header, ""))
            rows_to_append.append(row_values)
            
        sheet.append_rows(rows_to_append)
        print(f"[sheets.py] Creados con éxito {len(lista_datos_dict)} leads en la Google Sheet.")
        return True
    except Exception as e:
        print(f"Error al crear múltiples leads en Google Sheets: {e}")
        return False
