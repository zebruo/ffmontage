"""Pistes de son de la timeline : la forme d'onde des fichiers audio d'une commande ffmpeg.

ffmpeg décode chaque fichier en mono 16 bits à basse fréquence ; on garde le maximum par tranche de PAS secondes.
Le calcul se fait dans un fil à part ; le résultat est gardé tant que le fichier ne change pas.
"""
import array
import os
import re
import subprocess
import threading

from PySide6.QtCore import QObject, Signal

PAS = 0.02              # secondes par point de la forme d'onde
FREQUENCE = 4000        # échantillons par seconde décodés (assez pour l'enveloppe)
_cache = {}             # {(chemin, date de modification): enveloppe}


def enveloppe(chemin, ffmpeg="ffmpeg"):
    """Liste de niveaux (0 à 1), un par tranche de PAS secondes."""
    cle = (chemin, os.path.getmtime(chemin))
    if cle in _cache:
        return _cache[cle]
    brut = subprocess.run([ffmpeg, "-v", "error", "-i", chemin, "-vn", "-ac", "1", "-ar", str(FREQUENCE),
                           "-f", "s16le", "-"], capture_output=True, check=True,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0).stdout
    echantillons = array.array("h")
    echantillons.frombytes(brut[:len(brut) // 2 * 2])
    n = int(FREQUENCE * PAS)
    niveaux = [max(max(echantillons[i:i + n]), -min(echantillons[i:i + n])) / 32768
               for i in range(0, len(echantillons) - n + 1, n)]
    _cache[cle] = niveaux
    return niveaux


def sources_audio(commande):
    """[(chemin, décalage en s, nom)] : les fichiers audio d'une commande analysée et l'instant où ils commencent
    dans le film (un adelay dans la chaîne qui les reçoit)."""
    sorties = []
    mappees = {int(m.group(1)) for k, v in enumerate(commande.options_sortie[:-1])
               if v == "-map" and (m := re.fullmatch(r"(\d+):a.*", commande.options_sortie[k + 1]))}
    dans_graphe = {}
    for ch in commande.chaines:
        for etiquette in ch.entrees:
            if m := re.fullmatch(r"(\d+):a.*", etiquette):
                decalage = 0.0
                for f in ch.filtres:
                    if f.nom == "adelay":
                        valeur = dict((k, v) for k, v in f.args if k).get("delays") \
                            or next((v for k, v in f.args if not k), "0")
                        premier = re.split(r"[|]", valeur)[0].strip()
                        try:
                            decalage = float(premier[:-1]) if premier.endswith("s") else float(premier) / 1000
                        except ValueError:
                            pass
                        break
                dans_graphe[int(m.group(1))] = decalage
    for e in commande.entrees:
        if "lavfi" in e.options or e.index not in mappees | set(dans_graphe):
            continue
        chemin = os.path.join(commande.cwd, e.source)
        if os.path.isfile(chemin):
            sorties.append((chemin, dans_graphe.get(e.index, 0.0), os.path.basename(e.source)))
    return sorties


class CalculSon(QObject):
    """Calcule les formes d'onde en arrière-plan ; « pret » donne [(nom, décalage, pas, niveaux)]."""
    pret = Signal(list)
    _brut = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._brut.connect(self._relayer)

    def lancer(self, sources, ffmpeg):
        self._generation += 1
        generation = self._generation

        def travail():
            pistes = []
            for chemin, decalage, nom in sources:
                try:
                    pistes.append((nom, decalage, PAS, enveloppe(chemin, ffmpeg)))
                except (OSError, subprocess.CalledProcessError):
                    pass
            self._brut.emit([generation, pistes])
        threading.Thread(target=travail, daemon=True).start()

    def _relayer(self, donnees):
        if donnees[0] == self._generation:
            self.pret.emit(donnees[1])
