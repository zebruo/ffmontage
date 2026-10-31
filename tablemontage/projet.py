"""Nouveau projet : un script de départ (modeles/film.py) écrit dans le dossier des médias."""
import os

from . import chemins

VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".wmv"}
PHOTOS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def chemin_script(dossier):
    return os.path.join(dossier, os.path.basename(os.path.normpath(dossier)) + " film.py")


def creer(dossier):
    """Écrit « <dossier> film.py » dans le dossier (qui ne doit pas déjà l'avoir) ; renvoie son chemin."""
    nom = os.path.basename(os.path.normpath(dossier))
    with open(chemins.dossier_ressources() / "modeles" / "film.py", encoding="utf-8") as f:
        texte = f.read().replace("__NOM__", repr(nom))
    chemin = chemin_script(dossier)
    with open(chemin, "x", encoding="utf-8", newline="\r\n") as f:
        f.write(texte)
    return chemin


def inventaire(dossier):
    """(vidéos, photos, sons) trouvés dans le dossier et ses sous-dossiers, comme le script les cherche."""
    compte = [0, 0, 0]
    for _, sous_dossiers, noms in os.walk(dossier):
        sous_dossiers[:] = [d for d in sous_dossiers if not d.startswith((".", "_"))]
        for nom in noms:
            ext = os.path.splitext(nom)[1].lower()
            for i, groupe in enumerate((VIDEOS, PHOTOS, SONS)):
                compte[i] += ext in groupe
    return tuple(compte)
