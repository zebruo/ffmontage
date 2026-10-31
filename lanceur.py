"""Point d'entrée du lanceur de scripts (devient lanceur.exe dans la version compilée)."""
import sys

if getattr(sys, "frozen", False):
    import tablemontage.modules_scripts  # noqa: F401  (modules embarqués pour les scripts de montage)
from tablemontage.lanceur import principal

if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
