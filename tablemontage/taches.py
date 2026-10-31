"""Un processus (lanceur ou ffmpeg) lancé en arrière-plan, sans fenêtre console, ses lignes renvoyées à l'interface."""
import os
import subprocess
import threading

from PySide6.QtCore import QObject, Signal, Slot

CLES_PROGRESSION = {"frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms", "out_time", "dup_frames",
                    "drop_frames", "speed", "progress"}


def temps_progression(ligne):
    """Secondes écrites par « -progress » de ffmpeg (out_time_us=…), sinon None. Les autres clés renvoient -1."""
    cle, egal, valeur = ligne.partition("=")
    if not egal or not (cle in CLES_PROGRESSION or cle.startswith("stream_")):
        return None
    if cle == "out_time_us":
        try:
            return int(valeur) / 1e6
        except ValueError:
            return -1
    return -1


class Tache(QObject):
    ligne = Signal(str, bool)       # texte, vient de stderr
    fini = Signal(int)              # code de retour

    _ligne_brute = Signal(str, bool)
    _fini_brut = Signal(int)

    def __init__(self, args, cwd=None, env=None, parent=None):
        super().__init__(parent)
        self.args, self.cwd, self.env = args, cwd, env
        self._processus = None
        self.arretee = False
        # les fils de lecture émettent ces signaux ; reçus dans le fil de l'interface, ils sont relayés
        self._ligne_brute.connect(self._relayer_ligne)
        self._fini_brut.connect(self._relayer_fini)

    def lancer(self):
        try:
            self._processus = subprocess.Popen(
                self.args, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as e:
            self.ligne.emit(f"Impossible de lancer {self.args[0]} : {e}", True)
            self.fini.emit(-1)
            return
        lecteurs = [threading.Thread(target=self._lire, args=(flux, err), daemon=True)
                    for flux, err in ((self._processus.stdout, False), (self._processus.stderr, True))]
        for t in lecteurs:
            t.start()
        threading.Thread(target=self._attendre, args=(lecteurs,), daemon=True).start()

    def arreter(self):
        self.arretee = True
        if self._processus and self._processus.poll() is None:
            self._processus.kill()

    def en_cours(self):
        return self._processus is not None and self._processus.poll() is None

    def _lire(self, flux, err):
        for l in flux:
            self._ligne_brute.emit(l.rstrip("\r\n"), err)

    def _attendre(self, lecteurs):
        code = self._processus.wait()
        for t in lecteurs:
            t.join()
        self._fini_brut.emit(code)

    @Slot(str, bool)
    def _relayer_ligne(self, texte, err):
        self.ligne.emit(texte, err)

    @Slot(int)
    def _relayer_fini(self, code):
        self.fini.emit(code)
