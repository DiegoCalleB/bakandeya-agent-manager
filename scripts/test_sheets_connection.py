import os
import sys
# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from lib.sheets import obtener_cliente_sheets, DOCUMENTO_SHEETS

def probar_conexion():
    print("--------------------------------------------------")
    print("INICIANDO PRUEBA DE CONEXIÓN A GOOGLE SHEETS")
    print("--------------------------------------------------")
    print(f"Archivo de credenciales (ENV): {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
    print(f"Nombre del Documento (ENV): {DOCUMENTO_SHEETS}")
    print("--------------------------------------------------")
    
    # Comprobar que el archivo JSON de credenciales existe
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not os.path.exists(cred_path):
        print(f"❌ ERROR: El archivo de credenciales no existe en la ruta: {os.path.abspath(cred_path)}")
        return
        
    try:
        print("1. Autenticando con Google APIs...")
        client = obtener_cliente_sheets()
        print("[SUCCESS] Cliente autenticado correctamente.")
        
        print(f"2. Buscando y abriendo el documento '{DOCUMENTO_SHEETS}'...")
        spreadsheet = client.open(DOCUMENTO_SHEETS)
        print(f"[SUCCESS] Documento '{DOCUMENTO_SHEETS}' abierto con éxito.")
        
        print("3. Leyendo pestañas disponibles...")
        pestanas = [w.title for w in spreadsheet.worksheets()]
        print(f"   Pestañas encontradas: {pestanas}")
        
        if "leads" in pestanas:
            sheet = spreadsheet.worksheet("leads")
            filas = sheet.get_all_values()
            print(f"[SUCCESS] Pestaña 'leads' leída correctamente.")
            print(f"   Total filas encontradas (incluyendo cabecera): {len(filas)}")
            if len(filas) > 0:
                print(f"   Columnas actuales: {filas[0]}")
        else:
            print("[ERROR] No se encontró la pestaña llamada 'leads' en el documento.")
            print("   -> Por favor, crea una hoja/pestaña llamada 'leads' en tu documento de Google Sheets.")
            
    except Exception as e:
        print(f"[ERROR] Error de conexión: {e}")
        print("\nConsejos para resolverlo:")
        print("1. Verifica que el nombre del documento en Google Drive coincida exactamente con la variable del .env.")
        print("2. Asegúrate de haber compartido el documento con el email de la cuenta de servicio como 'Editor'.")

if __name__ == "__main__":
    probar_conexion()
