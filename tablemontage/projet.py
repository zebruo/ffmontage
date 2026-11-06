"""Nouveau projet : un script de départ (modeles/film.py) écrit dans le dossier des médias, avec les options
choisies dans la fenêtre du nouveau projet."""
import os
import re

from . import chemins, reglages

VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".wmv"}
PHOTOS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
EXT_SUITES = {".png", ".webp", ".bmp", ".tif", ".tiff"}     # comme le script : les .jpg restent des photos
SUITE_MIN = 24


def chemin_script(dossier):
    return os.path.join(dossier, os.path.basename(os.path.normpath(dossier)) + " film.py")


def creer(dossier, options=None):
    """Écrit « <dossier> film.py » dans le dossier (qui ne doit pas déjà l'avoir) ; renvoie son chemin.
    `options` : {nom du réglage: valeur}, écrites à la place de celles du modèle."""
    nom = os.path.basename(os.path.normpath(dossier))
    with open(chemins.dossier_ressources() / "modeles" / "film.py", encoding="utf-8") as f:
        texte = f.read().replace("__NOM__", repr(nom))
    if options:
        sources = {r.nom: r.source for r in reglages.lire(texte).reglages}
        texte = reglages.remplacer(texte, {n: reglages.formater(v, sources.get(n, "")) for n, v in options.items()})
    chemin = chemin_script(dossier)
    with open(chemin, "x", encoding="utf-8", newline="\r\n") as f:
        f.write(texte)
    return chemin


def inventaire(dossier):
    """(vidéos, photos, sons, animations) trouvés dans le dossier et ses sous-dossiers, comme le script les cherche :
    une animation est une suite d'au moins SUITE_MIN images numérotées de même nom (ses images ne sont pas comptées
    dans les photos)."""
    compte, groupes = [0, 0, 0], {}
    for dossier_courant, sous_dossiers, noms in os.walk(dossier):
        sous_dossiers[:] = [d for d in sous_dossiers if not d.startswith((".", "_"))]
        for nom in noms:
            base, ext = os.path.splitext(nom)
            ext = ext.lower()
            for i, groupe in enumerate((VIDEOS, PHOTOS, SONS)):
                compte[i] += ext in groupe
            m = re.fullmatch(r"(.*?)\d+", base)
            if m and ext in EXT_SUITES:
                cle = (dossier_courant, m.group(1), ext)
                groupes[cle] = groupes.get(cle, 0) + 1
    animations = [n for n in groupes.values() if n >= SUITE_MIN]
    return compte[0], compte[1] - sum(animations), compte[2], len(animations)
