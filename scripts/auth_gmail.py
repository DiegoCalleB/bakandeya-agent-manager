import sys
import os

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.gmail_client import obtener_servicio_gmail

def main():
    print("[auth_gmail.py] Iniciando flujo de autenticación de Gmail...")
    try:
        # Esto iniciará el flujo de autenticación local si credentials.json está presente.
        # Guardará automáticamente las credenciales validadas en token.json.
        servicio = obtener_servicio_gmail()
        if servicio:
            print("[auth_gmail.py] ¡Éxito! Autenticación completada y token.json generado con éxito.")
        else:
            print("[auth_gmail.py] Error: No se pudo obtener el servicio de Gmail.")
    except FileNotFoundError as e:
        print(f"\n[auth_gmail.py] ERROR: {e}")
        print("Asegúrate de haber descargado 'credentials.json' de Google Cloud y haberlo colocado en la raíz del proyecto.")
    except Exception as e:
        print(f"\n[auth_gmail.py] Error inesperado durante la autenticación: {e}")

if __name__ == "__main__":
    main()
