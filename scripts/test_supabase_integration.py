"""
Script de integración para verificar la conexión directa a Supabase
y las operaciones CRUD en las tablas 'leads', 'registered_bands' y 'messages',
así como la gestión del bucket de almacenamiento 'band-media'.
"""
import os
import uuid
from dotenv import load_dotenv
import lib.supabase_client as sb

load_dotenv()

def probar_conexion_y_operaciones():
    print("=== TEST DE INTEGRACIÓN CON SUPABASE & STORAGE ===")
    
    # 1. Obtener leads
    leads = sb.obtener_leads()
    print(f"1. Conexión a DB exitosa. Leads obtenidos: {len(leads)}")
    
    # 2. Crear lead de prueba
    test_id = f"test-{uuid.uuid4().hex[:8]}"
    nuevo_lead = {
        "id": test_id,
        "band_id": sb.BAND_ID_DEFAULT,
        "nombre_sala": "Sala Test Supabase",
        "ciudad": "Madrid",
        "region": "Madrid",
        "aforo": 400,
        "genero": "Mestizaje",
        "tipo": "sala",
        "email_contacto": "test@salasupabase.es",
        "fuente": "Test Script",
        "estado": "nuevo",
        "pitch_generado": "Pitch de prueba",
        "notas": "Registro generado en prueba de integración"
    }
    
    creado = sb.crear_leads([nuevo_lead])
    print(f"2. Creación de lead ({test_id}): {'EXITOSA' if creado else 'FALLIDA'}")
    
    # 3. Actualizar estado y datos del lead
    act_estado = sb.actualizar_estado_lead(test_id, "pendiente_aprobacion", notas="Actualizado a pendiente")
    print(f"3. Actualización de estado ({test_id}): {'EXITOSA' if act_estado else 'FALLIDA'}")
    
    act_datos = sb.actualizar_datos_lead(test_id, {"telefono": "600000000", "instagram": "@salatest"})
    print(f"4. Actualización de datos ({test_id}): {'EXITOSA' if act_datos else 'FALLIDA'}")
    
    # 4. Registrar mensaje de hilo
    msg_reg = sb.registrar_mensaje_hilo(
        lead_id=test_id,
        nombre_sala="Sala Test Supabase",
        fecha="2026-08-12T11:45:00Z",
        remitente="banda",
        remitente_nombre="Bakandeya",
        asunto="Test Asunto",
        mensaje="Hola, este es un mensaje de prueba.",
        mensaje_id=f"msg-{test_id}"
    )
    print(f"5. Registro de mensaje de hilo: {'EXITOSO' if msg_reg else 'FALLIDO'}")
    
    # 5. Probar subida a Supabase Storage (bucket 'band-media')
    try:
        bytes_prueba = b"Contenido de prueba para Supabase Storage"
        path_test = f"diagnostics/test_{test_id}.txt"
        url_publica = sb.subir_archivo_media(bytes_prueba, path_test, content_type="text/plain")
        print(f"6. Subida a Supabase Storage ('band-media'): {'EXITOSA' if url_publica else 'FALLIDA'}")
        if url_publica:
            print(f"   URL pública: {url_publica}")
    except Exception as e:
        print(f"6. Subida a Supabase Storage fallida: {e}")
        
    # 6. Limpieza del lead de prueba
    try:
        client = sb.get_supabase_client()
        client.table("leads").delete().eq("id", test_id).execute()
        client.table("messages").delete().eq("id", f"msg-{test_id}").execute()
        client.storage.from_("band-media").remove([f"diagnostics/test_{test_id}.txt"])
        print("7. Limpieza de datos de prueba en Supabase completada.")
    except Exception as e:
        print(f"7. Error durante limpieza: {e}")

    print("==================================================")

if __name__ == "__main__":
    probar_conexion_y_operaciones()
