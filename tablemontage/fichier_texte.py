"""Lire et réécrire un fichier texte (script, vers, sous-titres…) sans changer sa forme : BOM, fins de ligne et
encodage sont retenus à la lecture et rendus à l'écriture. Le texte, lui, est toujours en fins de ligne « \\n »."""
import codecs
from dataclasses import dataclass


@dataclass
class Forme:
    bom: bool = False
    fin_de_ligne: str = "\n"
    codage: str = "utf-8"


def lire(chemin):
    """(texte en fins de ligne \\n, Forme du fichier) ; un fichier qui n'est pas en UTF-8 est lu en cp1252."""
    with open(chemin, "rb") as f:
        brut = f.read()
    try:
        texte, codage = brut.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        texte, codage = brut.decode("cp1252", errors="replace"), "cp1252"
    forme = Forme(brut.startswith(codecs.BOM_UTF8), "\r\n" if "\r\n" in texte else "\n", codage)
    return texte.replace("\r\n", "\n"), forme


def ecrire(chemin, texte, forme):
    """Écrit le texte (fins de ligne \\n) dans la forme d'origine du fichier."""
    with open(chemin, "wb") as f:
        f.write((codecs.BOM_UTF8 if forme.bom else b"") + texte.replace("\n", forme.fin_de_ligne).encode(forme.codage))
