import os
import shutil
import stat

def instalar_hooks():
    """
    Copia los git hooks personalizados definidos en scripts/git-hooks/
    al directorio oculto .git/hooks/ del repositorio.
    """
    print("[INFO] Instalando Git Hooks...")
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(scripts_dir, "git-hooks")
    
    # El directorio .git/hooks está en la raíz del proyecto (un nivel arriba de scripts/)
    git_hooks_dir = os.path.abspath(os.path.join(scripts_dir, "..", ".git", "hooks"))
    
    if not os.path.exists(git_hooks_dir):
        # Intentar crearlo si por alguna razón .git existe pero no .git/hooks
        parent_git = os.path.abspath(os.path.join(scripts_dir, "..", ".git"))
        if os.path.exists(parent_git):
            os.makedirs(git_hooks_dir, exist_ok=True)
        else:
            print(
                f"[WARN] No se encontró el directorio .git en {parent_git}.\n"
                "Asegúrate de inicializar Git ('git init') antes de instalar los hooks."
            )
            return False
            
    src_file = os.path.join(src_dir, "pre-commit")
    dst_file = os.path.join(git_hooks_dir, "pre-commit")
    
    try:
        shutil.copy2(src_file, dst_file)
        
        # Dar permisos de ejecución (chmod +x)
        st = os.stat(dst_file)
        os.chmod(dst_file, st.st_mode | stat.S_IEXEC)
        print(f"[SUCCESS] Git hook 'pre-commit' instalado en: {dst_file}")
        return True
    except Exception as e:
        print(f"[ERROR] Error al copiar/configurar el git hook: {e}")
        return False

if __name__ == "__main__":
    instalar_hooks()
