import os
import gspread
from dotenv import load_dotenv

load_dotenv()

# Nombre del documento de Sheets por defecto
DOCUMENTO_SHEETS = os.getenv("GOOGLE_SHEETS_DOCUMENT", "Bakandeya Leads")

def obtener_cliente_sheets():
    """
    Autentica con la Service Account de Google Sheets.
    """
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
        datos = sheet.get_all_records()
        
        if estado:
            return [row for row in datos if row.get("estado") == estado]
        return datos
    except Exception as e:
        print(f"Error al obtener leads de Google Sheets: {e}")
        return []

def actualizar_datos_lead(lead_id, datos_dict):
    """
    Actualiza campos específicos de un lead en la hoja de cálculo.
    datos_dict es un diccionario con claves como: 'estado', 'pitch_generado', 'email_contacto', 'telefono', 'website', 'instagram', 'aforo', 'notas'.
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
