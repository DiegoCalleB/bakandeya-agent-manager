import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

import lib.sheets as sheets

def crear_columnas_necesarias():
    try:
        print("[setup_sheet_columns.py] Conectando a Google Sheets...")
        client = sheets.obtener_cliente_sheets()
        sheet = client.open(sheets.DOCUMENTO_SHEETS).worksheet("leads")
        
        headers = sheet.row_values(1)
        print(f"[setup_sheet_columns.py] Cabeceras actuales: {headers}")
        
        columnas_a_agregar = ["telefono", "website", "instagram"]
        
        for col_name in columnas_a_agregar:
            headers = sheet.row_values(1)
            if col_name not in headers:
                print(f"[setup_sheet_columns.py] Columna '{col_name}' faltante. Insertándola...")
                if col_name == "telefono":
                    idx = headers.index("email_contacto") if "email_contacto" in headers else 6
                    sheet.insert_cols([[col_name]], col=idx + 2)
                elif col_name == "website":
                    idx = headers.index("telefono") if "telefono" in headers else 7
                    sheet.insert_cols([[col_name]], col=idx + 2)
                elif col_name == "instagram":
                    idx = headers.index("website") if "website" in headers else 8
                    sheet.insert_cols([[col_name]], col=idx + 2)
                print(f"[setup_sheet_columns.py] Columna '{col_name}' insertada con éxito.")
            else:
                print(f"[setup_sheet_columns.py] Columna '{col_name}' ya existe.")
                
        print("[setup_sheet_columns.py] Configuración de columnas completada.")
    except Exception as e:
        print(f"[setup_sheet_columns.py] Error al configurar columnas: {e}")

if __name__ == "__main__":
    crear_columnas_necesarias()
