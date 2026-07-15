import os
import sys
import json
import uuid
import unicodedata
import argparse
from dotenv import load_dotenv

# Asegurar que el directorio raíz está en el path para las importaciones de lib
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

import lib.sheets as sheets
import lib.gemini_client as gemini_client
import lib.estados as estados
from lib.busqueda import buscar_duckduckgo, formatear_snippets

def normalizar_nombre(texto):
    """
    Normaliza el texto quitando acentos, pasándolo a minúsculas y eliminando
    espacios y prefijos comunes para una comparación de deduplicación más limpia.
    """
    if not texto:
        return ""
    texto = texto.lower().strip()
    # Eliminar acentos
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    
    # Eliminar prefijos comunes
    prefijos = ["ayuntamiento de ", "ayuntamiento ", "concello de ", "concello ", "ayto de ", "concejo de ", "sala de conciertos ", "sala ", "festival de musica ", "festival ", "fest "]
    for prefijo in prefijos:
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):]
            
    # Eliminar sufijos comunes
    sufijos = [" festival", " fest", " sala"]
    for sufijo in sufijos:
        if texto.endswith(sufijo):
            texto = texto[:-len(sufijo)]
            
    return texto.replace(" ", "").replace("-", "").replace("_", "").strip()

def extraer_candidatos_con_ia(resultados, tipo, region):
    """
    Utiliza Gemini para analizar snippets de búsqueda y extraer nombres de candidatos estructurados.
    """
    if not resultados:
        return []

    res_str = formatear_snippets(resultados)

    prompt = (
        f"Analiza los siguientes resultados de búsqueda web para encontrar nombres de {tipo}s en la región/provincia '{region}':\n\n"
        f"{res_str}\n"
        f"Tu objetivo es extraer una lista de entidades reales de tipo '{tipo}' que pertenezcan a la zona geográfica de '{region}'.\n"
        "Reglas:\n"
        f"1. Si el tipo es 'ayuntamiento', extrae únicamente el nombre oficial del ayuntamiento o concello (ej: 'Ayuntamiento de Vigo', 'Concello de Lalín') y su localidad.\n"
        f"2. Si el tipo es 'festival', extrae el nombre oficial del festival de música o ciclo de conciertos (ej: 'Festival PortAmérica', 'O Son do Camiño') y su localidad.\n"
        f"3. Si el tipo es 'sala', extrae el nombre de la sala de conciertos, pub de música en vivo o club y su localidad.\n"
        "4. Ignora directorios genéricos, agencias, turoperadores o noticias. Solo extrae entidades reales.\n"
        "5. GROUNDING: no inventes entidades. Extrae SOLO las que aparezcan explícitamente en los\n"
        "   snippets de arriba. Para cada candidato, 'fuente' debe ser el índice del snippet que lo\n"
        "   respalda (ej: '[3]'). Si no puedes señalar un snippet concreto, NO incluyas ese candidato.\n"
        "6. Devuelve un objeto JSON con este esquema exacto:\n"
        "{\n"
        "  \"candidatos\": [\n"
        "    {\n"
        "      \"nombre\": \"Nombre oficial de la entidad\",\n"
        "      \"ciudad\": \"Localidad/Municipio\",\n"
        "      \"fuente\": \"[n]\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    system_prompt = (
        "Eres un extractor experto de entidades geográficas y culturales a partir de textos de búsqueda. "
        "Tu única salida posible debe ser un objeto JSON válido según el esquema solicitado. "
        "No inventes entidades: si no está en los snippets, no existe para ti."
    )

    ans = gemini_client.generar_texto_gemini(
        prompt=prompt,
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        temperature=0.1,
        forzar_json=True  # JSON mode: respuesta siempre JSON válido, sin fences.
    )
    if not ans:
        return []

    try:
        data = json.loads(ans)
        return data.get("candidatos", [])
    except Exception as e:
        print(f"[scout_descubridor.py] Error al parsear JSON de Gemini: {e}. Respuesta: {ans}")
        return []

def descubrir_y_añadir_leads(region, tipo, limite=10):
    """
    Busca leads de uno o varios tipos específicos (separados por comas) en una región/provincia,
    los deduplica contra los existentes en la Google Sheet, y los crea masivamente en estado 'nuevo'.
    """
    tipos = [t.strip().lower() for t in tipo.split(",") if t.strip()]
    print(f"[scout_descubridor.py] Iniciando descubrimiento en la región/provincia '{region}' para los tipos: {tipos}")
    
    todos_candidatos = []
    
    # 1. Generar búsquedas y extraer candidatos por cada tipo individual
    for tipo_individual in tipos:
        if tipo_individual == "ayuntamiento":
            query = f"municipios y ayuntamientos de la provincia de {region}"
        elif tipo_individual == "festival":
            query = f"festivales de musica ciclos conciertos {region}"
        else:
            query = f"salas de conciertos locales de musica en vivo {region}"
            
        print(f"[scout_descubridor.py] Buscando en DuckDuckGo con query: '{query}'...")
        resultados = buscar_duckduckgo(query, max_results=10)
        
        if not resultados:
            print(f"[scout_descubridor.py] No se obtuvieron resultados para tipo '{tipo_individual}'. Saltando.")
            continue
            
        candidatos = extraer_candidatos_con_ia(resultados, tipo_individual, region)
        print(f"[scout_descubridor.py] IA extrajo {len(candidatos)} posibles candidatos de tipo '{tipo_individual}'.")
        
        # Guardar la asignación del tipo correspondiente
        for c in candidatos:
            c["tipo"] = tipo_individual
            
        todos_candidatos.extend(candidatos)
        
    if not todos_candidatos:
        print("[scout_descubridor.py] No se extrajeron candidatos válidos de ningún tipo.")
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=0, leads_enriquecidos=[])
        return 0
        
    # 2. Cargar leads existentes para deduplicación
    leads_existentes = sheets.obtener_leads()
    nombres_existentes_normalizados = {normalizar_nombre(l.get("nombre_sala")) for l in leads_existentes if l.get("nombre_sala")}
    
    leads_a_crear = []
    
    for cand in todos_candidatos:
        nombre = cand.get("nombre")
        ciudad = cand.get("ciudad") or region
        fuente_snippet = cand.get("fuente")
        tipo_cand = cand.get("tipo")

        if not nombre:
            continue

        nombre_norm = normalizar_nombre(nombre)
        if nombre_norm in nombres_existentes_normalizados:
            print(f"[scout_descubridor.py] Ignorando '{nombre}' (Ya existe en la base de datos).")
            continue

        # Generar ID de 8 caracteres único para no colisionar
        lead_id = f"lead_{uuid.uuid4().hex[:5]}"

        nuevo_lead = {
            "id": lead_id,
            "nombre_sala": nombre,
            "ciudad": ciudad or region,
            "region": "España",  # En la Sheet, la columna 'region' almacena el país (España)
            "tipo": tipo_cand,
            "fuente": f"Scout Descubridor: {region}",
            "estado": estados.NUEVO,
            "notas": (
                f"Descubierto automáticamente por el agente Scout Descubridor (tipo: {tipo_cand})"
                + (f" (snippet {fuente_snippet})." if fuente_snippet else ".")
                + " Contacto SIN verificar: pendiente de enriquecer por el Scout."
            ),
        }
        
        leads_a_crear.append(nuevo_lead)
        nombres_existentes_normalizados.add(nombre_norm) # Prevenir duplicación en la misma corrida
        
        if len(leads_a_crear) >= limite:
            break
            
    if not leads_a_crear:
        print("[scout_descubridor.py] Todos los candidatos descubiertos ya existían en la Google Sheet.")
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=0, leads_enriquecidos=[])
        return 0
        
    print(f"[scout_descubridor.py] Insertando {len(leads_a_crear)} nuevos leads en la Google Sheet...")
    exito = sheets.crear_leads(leads_a_crear)
    
    if exito:
        print(f"[scout_descubridor.py] Proceso completado. Se añadieron {len(leads_a_crear)} leads.")
        print(f"\n[scout_descubridor.py] Iniciando enriquecimiento automático para los {len(leads_a_crear)} nuevos leads...")
        leads_enriquecidos = []
        try:
            from agents.scout import enriquecer_leads_sin_contacto
            leads_enriquecidos = enriquecer_leads_sin_contacto(limite_leads=len(leads_a_crear), region=region, enviar_webhook=False)
        except Exception as e:
            print(f"[scout_descubridor.py] Error al enriquecer automáticamente: {e}")
        
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=len(leads_a_crear), leads_enriquecidos=leads_enriquecidos)
        return len(leads_a_crear)
    else:
        print("[scout_descubridor.py] Error al insertar leads en la Google Sheet.")
        from lib.webhooks import enviar_webhook_finalizacion
        enviar_webhook_finalizacion("scout_descubridor", region, creados=0, leads_enriquecidos=[])
        return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente Scout Descubridor para búsqueda activa de leads.")
    parser.add_argument("--region", type=str, required=True, help="Región o Provincia donde buscar.")
    parser.add_argument("--tipo", type=str, required=True, help="Tipo de entidad a buscar (separado por comas, ej: 'sala,festival').")
    parser.add_argument("--limit", type=int, default=10, help="Límite máximo de nuevos leads a añadir.")
    args = parser.parse_args()
    
    # Validar tipos
    tipos = [t.strip().lower() for t in args.tipo.split(",") if t.strip()]
    tipos_validos = ["sala", "festival", "ayuntamiento"]
    for t in tipos:
        if t not in tipos_validos:
            parser.error(f"Tipo '{t}' inválido. Debe ser uno de {tipos_validos}.")
            
    descubrir_y_añadir_leads(region=args.region, tipo=args.tipo, limite=args.limit)
