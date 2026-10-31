"""Chemins valables aussi bien depuis les sources que depuis l'exécutable (PyInstaller).

Dossier de l'application : celui de TableDeMontage.exe, ou la racine du projet.
  bin/ffmpeg.exe     utilisé en priorité s'il existe, sinon ffmpeg du PATH
  portable.txt       s'il existe : les données (aperçus, préférences) vont dans ./donnees au lieu de %LOCALAPPDATA%
"""
import os
import shutil
import sys
from pathlib import Path

FIGE = getattr(sys, "frozen", False)


def dossier_app():
    return Path(sys.executable).parent if FIGE else Path(__file__).resolve().parent.parent


def dossier_ressources():
    """Fichiers livrés avec l'application (icones/) : dans _internal une fois compilée."""
    return Path(getattr(sys, "_MEIPASS", dossier_app())) if FIGE else dossier_app()


def dossier_bin():
    d = dossier_app() / "bin"
    return d if d.is_dir() else None


def trouver_ffmpeg():
    if (d := dossier_bin()) and (d / "ffmpeg.exe").exists():
        return str(d / "ffmpeg.exe")
    return shutil.which("ffmpeg") or "ffmpeg"


def dossier_donnees():
    if os.environ.get("TABLEMONTAGE_DONNEES"):     # pour les essais : préférences et aperçus à part
        d = Path(os.environ["TABLEMONTAGE_DONNEES"])
    elif (dossier_app() / "portable.txt").exists():
        d = dossier_app() / "donnees"
    else:
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "TableDeMontage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def commande_lanceur(*args):
    """Commande qui exécute un script de montage dans un processus séparé."""
    if FIGE:
        return [str(dossier_app() / "lanceur.exe"), *map(str, args)]
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe" and (python.parent / "python.exe").exists():
        python = python.parent / "python.exe"
    return [str(python), "-X", "utf8", str(dossier_app() / "lanceur.py"), *map(str, args)]


def environnement():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if d := dossier_bin():
        env["PATH"] = f"{d}{os.pathsep}{env.get('PATH', '')}"
    return env
