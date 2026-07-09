import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Falta la variable GEMINI_API_KEY en el .env")
    exit(1)

genai.configure(api_key=api_key)

try:
    print("--- Modelos que admiten generateContent en tu clave API ---")
    modelos = list(genai.list_models())
    for m in modelos:
        if 'generateContent' in m.supported_generation_methods:
            print(f"  - {m.name} (displayName: {m.display_name})")
except Exception as e:
    print(f"Error al listar modelos: {e}")
