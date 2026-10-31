"""Table de montage : lancer avec « python TableDeMontage.py [script.py] » (devient TableDeMontage.exe une fois compilé)."""
import sys

from tablemontage.application import principal

if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
