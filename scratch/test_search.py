from ddgs import DDGS

def test_ddg_library():
    print("\n--- Probando Librería ddgs ---")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text("ContraClub Madrid web oficial contacto", max_results=5))
            print(f"Éxito: Se encontraron {len(results)} resultados.")
            for idx, r in enumerate(results, 1):
                print(f"  Resultado {idx}:")
                print(f"    Título: {r.get('title')}")
                print(f"    Enlace: {r.get('href')}")
            return True
    except Exception as e:
        print(f"Error al usar ddgs: {e}")
        return False

if __name__ == "__main__":
    test_ddg_library()
