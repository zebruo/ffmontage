"""Fenêtre principale : réglages à gauche, aperçu au centre, graphe / commande / journal à droite, timeline en bas."""
import difflib
import html
import json
import os
import re
import time

from PySide6.QtCore import QEvent, QFileSystemWatcher, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar,
                               QScrollArea, QSplitter, QTabBar, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import VERSION, chemins, ffmpeg_analyse, fichier_texte, projet, reglages, son
from .editeur import EditeurScript
from .fichiers import EXT_TEXTE, EditeurFichier, OngletFichiers
from .icones import icone
from .panneau import PanneauReglages
from .taches import Tache, temps_progression
from .timeline import Timeline
from .transport import Transport
from .vue_apercu import VueApercu

MODES_APERCU = [("Aperçu : film entier", None)] + [(f"Aperçu : {s} s depuis la tête", float(s))
                                                   for s in (10, 20, 30, 40, 50, 60)]


class Fenetre(QMainWindow):
    def __init__(self, chemin=None):
        super().__init__()
        self.resize(1500, 920)
        self.preferences = QSettings(str(chemins.dossier_donnees() / "table_montage.ini"), QSettings.IniFormat)
        self.chemin = None
        self.bloc = None
        self.commandes = []
        self._valeurs_execution = {}
        # la version de travail du script est le texte de l'éditeur ; _texte_courant est celui du disque
        self._texte_courant = None
        self._forme = fichier_texte.Forme()   # BOM, fins de ligne et encodage du script, rendus à l'enregistrement
        self._texte_analyse = None          # dernier texte de l'éditeur analysé (bloc de réglages)
        self._texte_capture = None          # dernier texte dont les commandes ffmpeg ont été lues
        self._derniere_retouche = ((), 0.0)  # (réglages, heure) : pour fusionner les retouches rapides en une annulation
        self._attente = {}
        self._apercu = self._export = None
        self._captures, self._generations = {}, {"normale": 0, "apercu": 0}
        self._numero_apercu = 0
        self._apercu_debut = 0.0
        self._apercu_fichier = None
        self._position_a_restaurer = None

        self._construire_interface()
        self._construire_actions()
        if geometrie := self.preferences.value("geometrie"):
            self.restoreGeometry(geometrie)         # taille et position de la dernière session (plein écran compris)

        self.surveillant = QFileSystemWatcher(self)
        self.surveillant.fileChanged.connect(self._fichier_change)
        self._t_ecriture = self._minuteur(250, self._ecrire)
        self._t_analyse = self._minuteur(400, self._analyser_texte)
        self._t_capture = self._minuteur(800, self._lancer_capture)
        self._t_rechargement = self._minuteur(300, self._recharger_si_change)
        self.editeur.document().contentsChanged.connect(self._t_analyse.start)

        self._titre()
        dernier = self.preferences.value("dernier", "")
        if chemin:
            self.ouvrir(chemin)
        elif dernier and os.path.exists(dernier):
            self.ouvrir(dernier)

    def _minuteur(self, ms, fonction):
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(fonction)
        return t

    # ───── construction
    def _construire_interface(self):
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(9)

        self.panneau = PanneauReglages()
        self.panneau.modifie.connect(self._modifier)

        # aperçu
        self.lecteur = QMediaPlayer(self)
        self.sortie_audio = QAudioOutput(QMediaDevices.defaultAudioOutput(), self)
        self.lecteur.setAudioOutput(self.sortie_audio)
        # suivre la sortie son par défaut de Windows (une enceinte Bluetooth qui se connecte après le lancement…)
        self._peripheriques = QMediaDevices(self)
        self._peripheriques.audioOutputsChanged.connect(self._sortie_son_changee)
        self.vue = VueApercu()                  # la vidéo, et les poignées des textes à déplacer
        self.vue.set_apercu_present(False)
        self.vue.deplace.connect(lambda nom, pos: self._modifier({nom: pos}))
        self.lecteur.setVideoOutput(self.vue.video)
        self.lecteur.positionChanged.connect(self._position)
        self.lecteur.playbackStateChanged.connect(self._etat_lecture)
        self.lecteur.mediaStatusChanged.connect(self._statut_media)

        self.transport = Transport()
        self.transport.debut.connect(lambda: self._aller_a(0.0))
        self.transport.recul.connect(lambda: self._aller_a(self.timeline.tete() - 5))
        self.transport.avance.connect(lambda: self._aller_a(self.timeline.tete() + 5))
        self.transport.stop.connect(self._stop)
        self.transport.lecture.connect(self._basculer_lecture)
        self.transport.boucle.connect(
            lambda oui: self.lecteur.setLoops(-1 if oui else 1))     # -1 : QMediaPlayer.Loops.Infinite
        self._depart_lecture = 0.0

        def montrer_textes(oui):
            self.vue.set_poignees_visibles(oui)
            self.preferences.setValue("poignees_textes", oui)
        self.transport.textes.connect(montrer_textes)
        self.transport.set_textes(self.preferences.value("poignees_textes", True, type=bool))
        self.vue.set_poignees_visibles(self.preferences.value("poignees_textes", True, type=bool))
        self.l_apercu = QLabel("")
        self.l_apercu.setStyleSheet("color: #8a8f9c;")
        barre = QHBoxLayout()
        barre.setContentsMargins(0, 0, 0, 0)
        barre.addWidget(self.transport, 1)
        colonne = QWidget()
        v = QVBoxLayout(colonne)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.vue, 1)
        v.addLayout(barre)

        # script, graphe, commande, journal
        self.editeur = EditeurScript()
        self.editeur.undoAvailable.connect(lambda oui: self.a_annuler.setEnabled(oui))
        self.editeur.redoAvailable.connect(lambda oui: self.a_retablir.setEnabled(oui))
        self.editeur.reglage_sous_curseur.connect(lambda nom: self.timeline.set_surbrillance({nom} if nom else set()))
        self.arbre = QTreeWidget()
        self.arbre.setHeaderLabels(["Élément", "Détail"])
        self.arbre.setColumnWidth(0, 200)
        self.texte_commande = QPlainTextEdit(readOnly=True)
        self.texte_commande.setFont(mono)
        self.texte_commande.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.journal = QPlainTextEdit(readOnly=True)
        self.journal.setFont(mono)
        self.journal.setMaximumBlockCount(5000)
        self.fichiers = OngletFichiers()
        self.fichiers.ouvrir.connect(self._ouvrir_fichier)
        self._editeurs_fichiers = {}            # {chemin: EditeurFichier} ouverts dans un onglet
        self._fichiers_script = []
        self.surveillant_fichiers = QFileSystemWatcher(self)
        self.surveillant_fichiers.fileChanged.connect(self._fichier_ouvert_change)
        self.onglets = QTabWidget()
        self.onglets.addTab(self.editeur, "Script")
        self.onglets.addTab(self.fichiers, "Fichiers")
        self.onglets.addTab(self.arbre, "Graphe")
        self.onglets.addTab(self.texte_commande, "Commande")
        self.onglets.addTab(self.journal, "Journal")
        self.onglets.setTabsClosable(True)          # seuls les fichiers ouverts ont une croix
        for i in range(self.onglets.count()):
            self.onglets.tabBar().setTabButton(i, QTabBar.RightSide, None)
        self.onglets.tabCloseRequested.connect(self._fermer_onglet)

        # timeline
        self.timeline = Timeline()
        self.timeline.set_recalcul(self._recalculer)
        self.timeline.modifie.connect(self._modifier)
        self.timeline.deplacement.connect(self._aller_a)
        self.timeline.choisi.connect(self._montrer_reglage)
        self.calcul_son = son.CalculSon(self)
        self.calcul_son.pret.connect(self.timeline.set_sons)
        zone = QScrollArea()
        zone.setWidgetResizable(True)
        zone.setWidget(self.timeline)
        zone.setMinimumHeight(260)

        # à gauche le panneau des réglages sur toute la hauteur ; à droite l'aperçu et les onglets, la timeline dessous
        # (tailles : disposer_par_defaut, d'après la taille de la fenêtre ; celles choisies à la souris sont gardées)
        haut = QSplitter(Qt.Horizontal)
        haut.addWidget(colonne)
        haut.addWidget(self.onglets)
        droite = QSplitter(Qt.Vertical)
        droite.addWidget(haut)
        droite.addWidget(zone)
        principal = QSplitter(Qt.Horizontal)
        principal.addWidget(self.panneau)
        principal.addWidget(droite)
        principal.setStretchFactor(1, 1)
        self.setCentralWidget(principal)
        self._separateurs = {"principal": principal, "haut": haut, "droite": droite}
        self._disposition_faite = False

        self.progression = QProgressBar()
        self.progression.setFixedWidth(150)
        self.progression.setFixedHeight(16)
        self.progression.setTextVisible(True)
        self.progression.setFormat("%p %")
        self.progression.setAlignment(Qt.AlignCenter)
        self.progression.setVisible(False)
        self.l_etat = QLabel("")
        self.statusBar().addWidget(self.l_etat, 1)
        self.statusBar().addPermanentWidget(self.l_apercu)
        self.statusBar().addPermanentWidget(self.progression)

    # ───── disposition des panneaux
    def disposer_par_defaut(self):
        """Tailles des panneaux d'après la fenêtre : réglages 22 % de la largeur (380 à 480 px), timeline la moitié
        de la hauteur, colonne de l'aperçu juste assez large pour l'image (selon sa proportion), le reste aux onglets."""
        largeur, hauteur = self.centralWidget().width(), self.centralWidget().height()
        if largeur < 200 or hauteur < 200:
            return
        panneau = int(min(480, max(380, largeur * 0.22)))
        droite = largeur - panneau
        timeline = int(hauteur * 0.5)
        dessus = hauteur - timeline
        l_film, h_film = self.vue.taille_film()
        hauteur_image = max(100, dessus - self.transport.sizeHint().height() - 8)
        colonne = int(min(max(480, hauteur_image * l_film / h_film + 12), droite - 360))
        self._separateurs["principal"].setSizes([panneau, droite])
        self._separateurs["droite"].setSizes([dessus, timeline])
        self._separateurs["haut"].setSizes([colonne, droite - colonne])

    def _sauver_disposition(self):
        self.preferences.setValue("geometrie", self.saveGeometry())
        for nom, separateur in self._separateurs.items():
            self.preferences.setValue(f"separateur_{nom}", separateur.saveState())

    def _restaurer_disposition(self):
        """Les tailles de la dernière session ; False s'il n'y en a pas (première fois)."""
        etats = {nom: self.preferences.value(f"separateur_{nom}") for nom in self._separateurs}
        if not all(etats.values()):
            return False
        for nom, etat in etats.items():
            self._separateurs[nom].restoreState(etat)
        return True

    def showEvent(self, e):
        super().showEvent(e)
        if not self._disposition_faite:
            self._disposition_faite = True
            if not self._restaurer_disposition():
                QTimer.singleShot(0, self.disposer_par_defaut)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and self._disposition_faite:
            QTimer.singleShot(0, self.disposer_par_defaut)     # agrandie ou rétablie : on recalcule

    def _construire_actions(self):
        def action(texte, raccourcis, fonction, image=None):
            a = QAction(texte, self)
            if raccourcis:
                a.setShortcuts([QKeySequence(r) for r in raccourcis.split("|")])
            if image:
                a.setIcon(icone(image))
            a.triggered.connect(fonction)
            return a

        self.a_nouveau = action("Nouveau projet…", "Ctrl+N", self._nouveau_projet)
        self.a_nouveau.setToolTip("Choisir le dossier des vidéos, photos et musique : un script de départ y est écrit")
        self.a_ouvrir = action("Ouvrir…", "Ctrl+O", self._choisir_script, "ouvrir")
        self.a_recharger = action("Recharger", "F5", lambda: self.recharger(), "recharger")
        self.a_enregistrer = action("Enregistrer", "Ctrl+S", self.enregistrer, "enregistrer")
        self.a_enregistrer.setEnabled(False)
        self.a_annuler = action("Annuler", "Ctrl+Z", self.annuler, "annuler")
        self.a_retablir = action("Rétablir", "Ctrl+Y|Ctrl+Shift+Z", self.retablir, "retablir")
        self.a_apercu = action("Calculer l'aperçu", "F6", self.lancer_apercu, "apercu")
        self.a_apercu.setToolTip("Calculer l'aperçu avec ffmpeg : le film entier ou l'extrait choisi à droite (F6)")
        self.a_exporter = action("Exporter le film", "Ctrl+E", self.lancer_export, "exporter")
        self.a_arreter = action("Arrêter", "Esc", self.arreter, "stop")
        self.a_dossier = action("Ouvrir le dossier du script", None, self._ouvrir_dossier, "dossier")
        self.a_auto = action("Aperçu automatique", None, lambda x: self.preferences.setValue("apercu_auto", x), "auto")
        self.a_auto.setCheckable(True)
        self.a_auto.setChecked(self.preferences.value("apercu_auto", False, type=bool))
        self.a_auto.setToolTip("Recalculer l'aperçu après chaque modification")
        self.a_arreter.setEnabled(False)
        self.a_annuler.setEnabled(False)
        self.a_retablir.setEnabled(False)

        self.mode_apercu = QComboBox()
        for texte, duree in MODES_APERCU:
            self.mode_apercu.addItem(texte, duree or 0.0)
        # préférence : la durée de l'extrait (0 = film entier), pas la position dans la liste
        self.mode_apercu.setCurrentIndex(max(0, self.mode_apercu.findData(
            self.preferences.value("duree_apercu", 0.0, type=float))))
        self.mode_apercu.currentIndexChanged.connect(
            lambda i: self.preferences.setValue("duree_apercu", self.mode_apercu.itemData(i)))

        barre = self.addToolBar("Principal")
        barre.setMovable(False)
        barre.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_ouvrir, self.a_enregistrer, self.a_recharger, None, self.a_annuler, self.a_retablir, None,
                  self.a_apercu, self.a_arreter):         # Arrêter (aperçu ou export) à côté de Calculer l'aperçu
            barre.addSeparator() if a is None else barre.addAction(a)
        barre.addWidget(self.mode_apercu)
        barre.addAction(self.a_auto)
        barre.addSeparator()
        barre.addAction(self.a_exporter)
        barre.addSeparator()
        barre.addAction(self.a_dossier)

        menu = self.menuBar().addMenu("&Fichier")
        for a in (self.a_nouveau, self.a_ouvrir, self.a_enregistrer, self.a_recharger, self.a_dossier, None,
                  self.a_exporter):
            menu.addSeparator() if a is None else menu.addAction(a)
        menu.addSeparator()
        menu.addAction(action("Quitter", "Ctrl+Q", self.close))
        menu = self.menuBar().addMenu("É&dition")
        menu.addAction(self.a_annuler)
        menu.addAction(self.a_retablir)
        menu = self.menuBar().addMenu("Affic&hage")
        menu.addAction(action("Disposition par défaut", "Ctrl+0", self.disposer_par_defaut))
        menu = self.menuBar().addMenu("&Aperçu")
        for a in (self.a_apercu, self.a_auto, self.a_arreter):
            menu.addAction(a)
        QShortcut(QKeySequence(Qt.Key_Space), self, self._basculer_lecture)

    # ───── journal et état
    def _journal(self, texte, erreur=False, source=None):
        couleur = "#e06c75" if erreur else "#c8ccd4"
        prefixe = f"<span style='color:#6b7080'>{time.strftime('%H:%M:%S')} {html.escape(source or '')}</span> "
        self.journal.appendHtml(f"{prefixe}<span style='color:{couleur}'>{html.escape(texte)}</span>")

    def _etat(self, texte):
        self.l_etat.setText(texte)

    def _modifie(self):
        """Le texte de l'éditeur diffère-t-il du script sur le disque ?"""
        return self._texte_courant is not None and self.editeur.texte() != self._texte_courant

    def _reglages_modifies(self):
        """[(nom, valeur sur le disque, valeur dans l'éditeur)] pour les réglages du bloc qui diffèrent."""
        if self._texte_courant is None:
            return []
        disque = {r.nom: r.source for r in reglages.lire(self._texte_courant).reglages}
        return [(r.nom, disque.get(r.nom), r.source) for r in reglages.lire(self.editeur.texte()).reglages
                if disque.get(r.nom) != r.source]

    def _fichiers_modifies(self):
        return [e for e in self._editeurs_fichiers.values() if e.modifie()]

    def _titre(self):
        modifie = self._modifie() or bool(self._fichiers_modifies())
        nom = os.path.basename(self.chemin) if self.chemin else "aucun script"
        self.setWindowTitle(f"{'● ' if modifie else ''}{nom} — Table de montage {VERSION}")
        self.a_enregistrer.setEnabled(modifie)
        self.a_enregistrer.setToolTip("Enregistrer le script et les fichiers modifiés  (Ctrl+S)" if modifie
                                      else "Aucune modification à enregistrer")

    # ───── fichiers lus et écrits par le script
    def _ouvrir_fichier(self, chemin, modifiable):
        """Double-clic dans l'onglet Fichiers : un texte s'ouvre dans un onglet, le reste avec le logiciel de Windows."""
        if os.path.splitext(chemin)[1].lower() not in EXT_TEXTE:
            QDesktopServices.openUrl(QUrl.fromLocalFile(chemin))
            return
        editeur = self._editeurs_fichiers.get(chemin)
        if editeur is None:
            try:
                editeur = EditeurFichier(chemin, modifiable)
            except OSError as e:
                self._journal(f"Ouverture impossible : {e}", True)
                return
            editeur.modifie_change.connect(lambda oui, e=editeur: self._onglet_fichier_modifie(e, oui))
            self._editeurs_fichiers[chemin] = editeur
            self.onglets.addTab(editeur, os.path.basename(chemin))
            self.onglets.setTabToolTip(self.onglets.indexOf(editeur), chemin)
            self.surveillant_fichiers.addPath(chemin)
        self.onglets.setCurrentWidget(editeur)

    def _onglet_fichier_modifie(self, editeur, oui):
        i = self.onglets.indexOf(editeur)
        if i >= 0:
            self.onglets.setTabText(i, ("● " if oui else "") + os.path.basename(editeur.chemin))
        self._titre()

    def _fichier_ouvert_change(self, chemin):
        """Un fichier ouvert dans un onglet, ou lu par le script, a changé sur le disque."""
        if os.path.exists(chemin) and chemin not in self.surveillant_fichiers.files():
            self.surveillant_fichiers.addPath(chemin)
        if editeur := self._editeurs_fichiers.get(chemin):
            editeur.change_sur_disque()
        if any(os.path.normcase(f["chemin"]) == os.path.normcase(chemin) and "écrit" not in f["acces"]
               for f in self._fichiers_script):
            self._texte_capture = None          # le script lit ce fichier : on le relit
            self.l_apercu.setText("aperçu périmé" if self._apercu_fichier else "")
            self._t_capture.start()

    def _fermer_onglet(self, index):
        editeur = self.onglets.widget(index)
        if not isinstance(editeur, EditeurFichier):
            return
        if editeur.modifie():
            reponse = QMessageBox.question(
                self, "Fichier modifié", f"Enregistrer {os.path.basename(editeur.chemin)} avant de le fermer ?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if reponse == QMessageBox.Cancel:
                return
            if reponse == QMessageBox.Save:
                self._enregistrer_fichier(editeur)
        self.onglets.removeTab(index)
        self.surveillant_fichiers.removePath(editeur.chemin)
        del self._editeurs_fichiers[editeur.chemin]
        editeur.deleteLater()
        self._titre()

    def _echec_enregistrement(self, erreur):
        self._journal(f"Enregistrement impossible : {erreur}", True)
        QMessageBox.warning(self, "Enregistrement impossible", str(erreur))
        return False

    def _enregistrer_fichier(self, editeur):
        try:
            editeur.enregistrer()
        except OSError as e:
            return self._echec_enregistrement(e)
        self._journal(f"Fichier enregistré : {editeur.chemin}", source="enregistrement :")
        self._texte_capture = None              # le script lit ce fichier : on le relit
        self.l_apercu.setText("aperçu périmé" if self._apercu_fichier else "")
        self._t_capture.start()
        return True

    def _message(self, texte):
        """Un message bien visible qui s'efface tout seul (en bas à droite de la fenêtre)."""
        if not hasattr(self, "_bulle"):
            self._bulle = QLabel(self)
            self._bulle.setStyleSheet("background: #2f6f4f; color: #ffffff; border-radius: 6px; padding: 8px 14px;")
            self._bulle.setWordWrap(True)
            self._t_bulle = self._minuteur(3500, self._bulle.hide)
        self._bulle.setText(texte)
        self._bulle.setMinimumWidth(380)
        self._bulle.setMaximumWidth(560)
        self._bulle.adjustSize()
        self._bulle.move(self.width() - self._bulle.width() - 16,
                         self.height() - self.statusBar().height() - self._bulle.height() - 12)
        self._bulle.raise_()
        self._bulle.show()
        self._t_bulle.start()

    def _vider_attente(self):
        """Écrit tout de suite dans l'éditeur les retouches du panneau ou de la timeline encore en attente."""
        if self._attente:
            self._t_ecriture.stop()
            self._ecrire()

    def _confirmer_abandon(self, action):
        """Modifications non enregistrées : les enregistrer ? Renvoie False si l'utilisateur annule l'action."""
        self._vider_attente()
        if not self._modifie() and not self._fichiers_modifies():
            return True
        liste = "\n".join(f"  {n} = {s}" for n, _, s in self._reglages_modifies()[:12]) \
            or ("  (modifications dans le texte du script)" if self._modifie() else "")
        liste += "".join(f"\n  fichier {os.path.basename(e.chemin)}" for e in self._fichiers_modifies())
        reponse = QMessageBox.question(
            self, "Modifications non enregistrées",
            f"Le script a des modifications non enregistrées :\n{liste}\n\nLes enregistrer avant de {action} ?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if reponse == QMessageBox.Save:
            return self.enregistrer()
        return reponse == QMessageBox.Discard

    def _occupe(self):
        en_cours = any(t and t.en_cours() for t in (self._apercu, self._export))
        self.a_arreter.setEnabled(en_cours)
        self.a_exporter.setEnabled(not (self._export and self._export.en_cours()))
        if not en_cours:
            self.progression.setVisible(False)

    def _progresser(self, t, total):
        self.progression.setVisible(True)
        if t is None or t <= 0 or not total:
            self.progression.setRange(0, 0)         # indéterminée (ffmpeg calcule le début)
        else:
            self.progression.setRange(0, 1000)
            self.progression.setValue(int(min(1.0, t / total) * 1000))

    # ───── ouverture et lecture du script
    def _choisir_script(self):
        depart = os.path.dirname(self.chemin) if self.chemin else str(chemins.dossier_app())
        chemin = QFileDialog.getOpenFileName(self, "Ouvrir un script de montage", depart, "Scripts Python (*.py)")[0]
        if chemin:
            self.ouvrir(chemin)

    def _nouveau_projet(self):
        depart = os.path.dirname(os.path.dirname(self.chemin)) if self.chemin else os.path.expanduser("~")
        dossier = QFileDialog.getExistingDirectory(
            self, "Nouveau projet : le dossier du film (vidéos, photos, musique ; « Nouveau dossier » pour le créer)",
            depart)
        if not dossier:
            return
        script = projet.chemin_script(dossier)
        if os.path.exists(script):
            if QMessageBox.question(self, "Nouveau projet", f"Ce dossier a déjà son script :\n{script}\n\nL'ouvrir ?",
                                    QMessageBox.Open | QMessageBox.Cancel, QMessageBox.Open) == QMessageBox.Open:
                self.ouvrir(script)
            return
        if self.chemin and not self._confirmer_abandon("créer un nouveau projet"):
            return
        try:
            script = projet.creer(dossier)
        except OSError as e:
            QMessageBox.warning(self, "Nouveau projet", f"Le script n'a pas pu être écrit :\n{e}")
            return
        self._journal(f"Script de départ écrit : {script}", source="nouveau projet :")
        self.ouvrir(script)
        videos, photos, sons = projet.inventaire(dossier)
        if videos or photos or sons:
            self._message(f"Projet « {os.path.basename(dossier)} » créé : {videos} vidéo(s), {photos} photo(s), "
                          f"{sons} musique(s) dans le dossier. Fichiers ajoutés plus tard : F5 pour relire.")
        else:
            self._message(f"Projet « {os.path.basename(dossier)} » créé. Le dossier est vide : ajoutez-y vidéos, "
                          f"photos et musique, puis F5 pour relire.")

    def ouvrir(self, chemin):
        chemin = os.path.abspath(chemin)
        if self.chemin and not self._confirmer_abandon("ouvrir un autre script"):
            return
        for editeur in list(self._editeurs_fichiers.values()):     # les fichiers de l'ancien script
            self.onglets.removeTab(self.onglets.indexOf(editeur))
            self.surveillant_fichiers.removePath(editeur.chemin)
            editeur.deleteLater()
        self._editeurs_fichiers.clear()
        if self.chemin:
            self.surveillant.removePath(self.chemin)
        self.arreter()
        self.chemin = chemin
        self.surveillant.addPath(chemin)
        self.preferences.setValue("dernier", chemin)
        self.lecteur.stop()
        self.lecteur.setSource(QUrl())
        self.vue.set_apercu_present(False)
        self.timeline.set_apercu(None, None)
        self.commandes, self._valeurs_execution = [], {}
        self._texte_courant = self._texte_analyse = self._texte_capture = None
        self._journal(f"Ouverture de {chemin}")
        self.recharger(demander=False)

    def _lire_disque(self):
        """Le script sur le disque, fins de ligne en \\n (sa forme est retenue pour l'enregistrer à l'identique)."""
        texte, self._forme = fichier_texte.lire(self.chemin)
        return texte

    def recharger(self, demander=True):
        """Recharge le script du disque dans l'éditeur (en demandant si des modifications seraient perdues)."""
        if not self.chemin:
            return
        try:
            texte = self._lire_disque()
        except OSError as e:
            self._journal(f"Lecture impossible : {e}", True)
            return
        if demander and self._modifie():
            reponse = QMessageBox.question(
                self, "Recharger le script",
                "Recharger le script depuis le disque ? Les modifications non enregistrées seront perdues.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reponse != QMessageBox.Yes:
                return
        self._texte_courant = texte
        self.editeur.charger(texte)
        self._t_analyse.stop()
        self._analyser_texte()
        if self.bloc and not self.bloc.trouve:
            self._journal("Pas de bloc « # ── RÉGLAGES » : seule l'analyse de la commande ffmpeg sera affichée.")

    def _analyser_texte(self):
        """Le texte de l'éditeur a changé : relire le bloc de réglages, mettre à jour panneau et timeline,
        puis relire le script (commandes ffmpeg) un peu plus tard."""
        texte = self.editeur.texte()
        self._titre()
        if texte == self._texte_analyse:
            return
        bloc = reglages.lire(texte)
        if bloc.erreur:             # on garde l'affichage précédent tant que le script est invalide
            m = re.search(r"ligne (\d+)", bloc.erreur)
            self.editeur.set_erreur(int(m.group(1)) if m else None)
            self._etat(bloc.erreur)
            if self.bloc is None:
                self.panneau.afficher(bloc, "")
            return
        self.editeur.set_erreur(None)
        self._texte_analyse = texte
        self._appliquer_bloc(bloc)
        if texte != self._texte_capture:
            self.l_apercu.setText("aperçu périmé" if self._apercu_fichier else "")
            self._t_capture.start()

    def _appliquer_bloc(self, bloc):
        self.bloc = bloc
        bloc.appliquer_execution(self._valeurs_execution)
        self.panneau.afficher(bloc, self._dossier_base())
        self.timeline.set_bloc(bloc)
        self.editeur.set_reglages(bloc, self.timeline.couleurs_reglages())
        self._suivre_tete()

    def _suivre_tete(self):
        """Surligne dans l'éditeur les réglages des blocs qui sont sous la tête de lecture."""
        self.editeur.suivre(self.timeline.actifs(self.timeline.tete()))
        self._maj_textes()

    def _maj_textes(self):
        """Les poignées de l'aperçu : un texte par piste qui a une position (@Piste.position), avec son apparence
        (@Piste.texte / .police / .taille / .couleur), atténué quand la piste n'est pas sous la tête."""
        if not self.bloc:
            self.vue.set_textes([])
            return
        valeurs = {r.nom: r.valeur for r in self.bloc.tous if r.connu}
        largeur, hauteur = valeurs.get("W"), valeurs.get("H")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (largeur, hauteur)):
            self.vue.set_taille_film(int(largeur), int(hauteur))

        def position(r):
            v = r.valeur
            return r.modifiable and isinstance(v, (list, tuple)) and len(v) == 2 \
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)

        pistes, textes, t = {}, [], self.timeline.tete()
        for r in self.bloc.tous:
            if r.connu:
                for piste, role in r.etiquettes:
                    if role in ("texte", "police", "taille", "couleur", "position"):
                        pistes.setdefault(piste, {})[role] = r
        for piste, roles in pistes.items():
            rp = roles.get("position")
            if rp and position(rp):
                apparence = {role: roles[role].valeur for role in ("texte", "police", "taille", "couleur") if role in roles}
                textes.append({"reglage": rp.nom, "nom": piste.replace("_", " "), "position": tuple(rp.valeur),
                               "actif": self.timeline.piste_active(piste, t), **apparence})
        for r in self.bloc.tous:        # @position seul, sans piste
            if r.choix == "position" and not any(role == "position" for _, role in r.etiquettes) and position(r):
                textes.append({"reglage": r.nom, "nom": r.nom, "position": tuple(r.valeur), "actif": None})
        self.vue.set_textes(textes)

    def _montrer_reglage(self, nom, index):
        """Clic sur un bloc de la timeline : l'éditeur montre sa valeur."""
        r = next((r for r in self.bloc.tous if r.nom == nom), None) if self.bloc else None
        if r:
            self.onglets.setCurrentWidget(self.editeur)
            self.editeur.aller_a(r, index)

    def _dossier_base(self):
        if self.bloc:
            for r in self.bloc.reglages:
                if r.choix == "dossier" and isinstance(r.valeur, str) and os.path.isdir(r.valeur):
                    return r.valeur
        return os.path.dirname(self.chemin) if self.chemin else ""

    def _fichier_change(self, chemin):
        if os.path.exists(chemin) and chemin not in self.surveillant.files():
            self.surveillant.addPath(chemin)          # certains éditeurs remplacent le fichier
        self._t_rechargement.start()

    def _recharger_si_change(self):
        try:
            texte = self._lire_disque()
        except OSError:
            return
        if texte == self._texte_courant:
            return
        if not self._modifie():
            self._journal("Le script a été modifié dans un autre éditeur : rechargement.")
            self.recharger(demander=False)
            return
        reponse = QMessageBox.question(
            self, "Script modifié ailleurs",
            "Le script a été modifié dans un autre éditeur, et la table a des modifications non enregistrées.\n\n"
            "Charger la version du disque (vos modifications seront perdues) ?\n"
            "Non : garder votre version ; l'enregistrer remplacera celle du disque.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reponse == QMessageBox.Yes:
            self.recharger(demander=False)
        else:
            self._texte_courant = texte
            self._titre()

    def _ouvrir_dossier(self):
        if self.chemin:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.chemin)))

    # ───── modifications du panneau ou de la timeline : écrites dans l'éditeur (pas encore dans le fichier)
    def _recalculer(self, remplacements):
        return reglages.recalculer(self.bloc, remplacements) if self.bloc else remplacements

    def _modifier(self, changements):
        if not self.bloc or not self.chemin:
            return
        self._attente.update(changements)
        self._t_ecriture.start()

    def _ecrire(self):
        changements, self._attente = self._attente, {}
        if not self.bloc:
            return
        par_nom = {r.nom: r for r in self.bloc.reglages}
        sources = {n: s for n, v in changements.items() if n in par_nom
                   and (s := reglages.formater(v, par_nom[n].source)) != par_nom[n].source}
        if not sources:
            return
        # une suite rapide de retouches des mêmes réglages (curseur, glissements successifs) : une seule annulation
        noms, heure = self._derniere_retouche
        fusion = tuple(sorted(sources)) == noms and time.time() - heure < 1.5
        try:
            self.editeur.remplacer_valeurs(sources, fusion)
        except ValueError as e:
            self._journal(f"Valeur refusée : {e}", True)
            self._appliquer_bloc(self.bloc)
            return
        self._derniere_retouche = (tuple(sorted(sources)), time.time())
        self._etat("Modifié (non enregistré) : " + ", ".join(f"{n} = {s}" for n, s in sources.items())[:200])
        self._t_analyse.stop()
        self._analyser_texte()

    def _quitter_champ(self):
        """Un champ du panneau en cours de saisie : on le quitte, ce qui valide la valeur tapée (sans Entrée) et
        retire son curseur. La barre d'outils ne prend pas le focus : sans cela, le champ le garderait."""
        champ = QApplication.focusWidget()
        if champ is not None and self.panneau.isAncestorOf(champ):
            champ.clearFocus()

    def enregistrer(self):
        """Écrit le script et les fichiers modifiés dans leurs onglets. Renvoie True si tout est enregistré."""
        self._quitter_champ()
        self._vider_attente()
        fichiers = self._fichiers_modifies()
        if fichiers:
            if not all([self._enregistrer_fichier(e) for e in fichiers]):
                return False
            if not self._modifie():
                noms = ", ".join(os.path.basename(e.chemin) for e in fichiers)
                self._etat(f"Enregistré : {noms}")
                self._message(f"✓  {noms} enregistré\nle script est relu")
                self._titre()
                return True
        if not self.chemin or not self._modifie():
            return True
        texte, avant = self.editeur.texte(), self._texte_courant
        modifies = self._reglages_modifies()
        try:
            fichier_texte.ecrire(self.chemin, texte, self._forme)
        except OSError as e:
            return self._echec_enregistrement(e)
        self._texte_courant = texte
        self.editeur.document().setModified(False)
        self._titre()
        # le résumé : les réglages mis à jour, et les autres lignes modifiées à la main
        lignes_reglages = {k for r in reglages.lire(texte).reglages if r.position
                           for k in range(r.ligne, r.position[2] + 1)}
        changees, supprimees = set(), 0
        for etiquette, i1, i2, j1, j2 in difflib.SequenceMatcher(None, avant.split("\n"), texte.split("\n"),
                                                                 autojunk=False).get_opcodes():
            if etiquette != "equal":
                changees.update(range(j1 + 1, j2 + 1))
                supprimees += max(0, (i2 - i1) - (j2 - j1))
        autres = len(changees - lignes_reglages) + supprimees
        parties = []
        if modifies:
            parties.append(f"{len(modifies)} réglage{'s' if len(modifies) > 1 else ''} mis à jour : "
                           + ", ".join(f"{n} = {s}" for n, _, s in modifies))
        if autres:
            parties.append(f"{autres} autre{'s' if autres > 1 else ''} ligne{'s' if autres > 1 else ''} "
                           f"modifiée{'s' if autres > 1 else ''}")
        resume = " · ".join(parties) or "aucun changement de contenu"
        self._journal(f"Script enregistré : {resume}", source="enregistrement :")
        self._etat("Script enregistré")
        self._message(f"✓  {os.path.basename(self.chemin)} enregistré\n{resume[:400]}")
        return True

    # ───── annuler / rétablir : l'historique de l'éditeur (frappes, panneau et timeline)
    def annuler(self):
        self._vider_attente()
        self._derniere_retouche = ((), 0.0)
        self.editeur.undo()

    def retablir(self):
        self._vider_attente()
        self._derniere_retouche = ((), 0.0)
        self.editeur.redo()

    # ───── capture : le script lancé sans ffmpeg
    def _lancer_capture(self, apercu=False, ensuite=None):
        if not self.chemin:
            return
        self._vider_attente()
        genre = "apercu" if apercu else "normale"
        if self._captures.get(genre):
            self._captures[genre].arreter()
        self._generations[genre] += 1
        generation = self._generations[genre]
        dossier = chemins.dossier_donnees() / "captures"
        dossier.mkdir(exist_ok=True)
        fichier = dossier / f"capture_{genre}_{generation}.json"
        if not apercu:
            self._texte_capture = self.editeur.texte()
        args = chemins.commande_lanceur("capture", self.chemin, fichier, *(["--apercu"] if apercu else []),
                                        *self._option_source())
        tache = Tache(args, cwd=os.path.dirname(self.chemin), env=chemins.environnement(), parent=self)
        tache.ligne.connect(lambda t, err: self._journal(t, err, "script (lecture) :"))
        tache.fini.connect(lambda code: self._capture_finie(code, generation, fichier, apercu, ensuite))
        self._captures[genre] = tache
        self._etat("Lecture du script…")
        tache.lancer()

    def _option_source(self):
        """« --source <fichier> » si le texte de l'éditeur n'est pas enregistré : le lanceur exécute cette version."""
        if not self._modifie():
            return []
        dossier = chemins.dossier_donnees() / "travail"
        dossier.mkdir(exist_ok=True)
        fichier = dossier / os.path.basename(self.chemin)
        fichier.write_text(self.editeur.texte(), encoding="utf-8")
        return ["--source", str(fichier)]

    def _capture_finie(self, code, generation, fichier, apercu, ensuite):
        genre = "apercu" if apercu else "normale"
        if generation != self._generations[genre]:
            return
        self._captures[genre] = None
        try:
            with open(fichier, encoding="utf-8") as f:
                donnees = json.load(f)
            os.remove(fichier)
        except (OSError, ValueError):
            donnees = {"commandes": [], "valeurs": {}}
        if code != 0:
            self._journal(f"Le script s'est arrêté avec une erreur (code {code}).", True)
        commandes = [ffmpeg_analyse.analyser(c["args"], c["cwd"]) for c in donnees["commandes"]]
        if apercu:
            self._etat("")
            if ensuite and commandes:
                ensuite(commandes)
            elif not commandes:
                self._journal("Aucune commande ffmpeg pour l'aperçu.", True)
            return
        self.commandes = commandes
        self._valeurs_execution = donnees.get("valeurs", {})
        ips = self._valeurs_execution.get("IPS")
        self.timeline.pas_image = 1 / ips if isinstance(ips, (int, float)) and ips > 0 else 0.04
        self._appliquer_bloc(reglages.lire(self._texte_analyse or self.editeur.texte()))
        self._afficher_commandes()
        c = commandes[-1] if commandes else None
        self.calcul_son.lancer(son.sources_audio(c) if c else [], chemins.trouver_ffmpeg())
        duree = (c.duree if c and c.duree else None) or self.timeline.duree()
        medias = ffmpeg_analyse.medias(c, duree) if c else []
        courbes = ffmpeg_analyse.courbes(c, duree) if c else []
        self.timeline.set_medias(medias, courbes, ffmpeg_analyse.transitions(c) if c else [])
        self.timeline.set_analyse(c.intervalles() if c else [], c.duree if c else None,
                                  ffmpeg_analyse.noms_lignes(c, courbes) if c else {})
        self._fichiers_script = donnees.get("fichiers", [])
        self.fichiers.afficher(os.path.dirname(self.chemin), self._fichiers_script, c)
        lus = {f["chemin"] for f in self._fichiers_script if "écrit" not in f["acces"] and os.path.exists(f["chemin"])}
        surveilles = set(self.surveillant_fichiers.files())
        if lus - surveilles:            # surveillés : une modification ailleurs fait relire le script
            self.surveillant_fichiers.addPaths(sorted(lus - surveilles))
        if not commandes:
            self._journal("Aucune commande ffmpeg trouvée : le script appelle-t-il ffmpeg par subprocess ?", True)
            self._etat("Aucune commande ffmpeg")
            return
        self._etat(f"{len(commandes)} commande(s) ffmpeg · durée {c.duree:.2f} s" if c.duree else
                   f"{len(commandes)} commande(s) ffmpeg")
        if self.a_auto.isChecked():
            self.lancer_apercu()

    def _afficher_commandes(self):
        self.arbre.clear()
        for k, c in enumerate(self.commandes):
            racine = QTreeWidgetItem(self.arbre, [f"Commande {k + 1}", os.path.basename(c.sortie or "")])
            entrees = QTreeWidgetItem(racine, ["Entrées", str(len(c.entrees))])
            for e in c.entrees:
                item = QTreeWidgetItem(entrees, [f"#{e.index}  {os.path.basename(e.source)[:60]}", " ".join(e.options)])
                item.setToolTip(0, e.source)
            filtres = QTreeWidgetItem(racine, ["Filtres", f"{len(c.chaines)} chaînes"])
            for ch in c.chaines:
                titre = " ".join(f"[{x}]" for x in ch.entrees) + "  →  " + " ".join(f"[{x}]" for x in ch.sorties)
                item = QTreeWidgetItem(filtres, [titre, " → ".join(f.nom for f in ch.filtres)])
                item.setToolTip(1, ch.texte)
                for f in ch.filtres:
                    args = ":".join(f"{cle}={v}" if cle else v for cle, v in f.args)
                    sous = QTreeWidgetItem(item, [f.nom, args[:300]])
                    sous.setToolTip(1, args)
            sortie = QTreeWidgetItem(racine, ["Sortie", c.sortie or "?"])
            sortie.setToolTip(1, c.sortie or "")
            for i in range(0, len(c.options_sortie) - 1, 2):
                QTreeWidgetItem(sortie, [c.options_sortie[i], c.options_sortie[i + 1]])
        if self._valeurs_execution:
            variables = QTreeWidgetItem(self.arbre, ["Variables du script", f"{len(self._valeurs_execution)} (en fin d'exécution)"])
            for nom, v in sorted(self._valeurs_execution.items()):
                texte = repr(v)
                item = QTreeWidgetItem(variables, [nom, texte[:200]])
                item.setToolTip(1, texte[:2000])
        self.arbre.expandToDepth(1)
        if self.arbre.topLevelItemCount():
            self.arbre.topLevelItem(self.arbre.topLevelItemCount() - 1).setExpanded(False)
        self.texte_commande.setPlainText("\n\n".join(ffmpeg_analyse.formater_commande(c) for c in self.commandes))

    # ───── aperçu
    def lancer_apercu(self):
        if not self.chemin:
            return
        self._quitter_champ()
        if self._apercu:
            self._apercu.arreter()
        if self.bloc and any(r.apercu for r in self.bloc.reglages):
            self._etat("Lecture du script avec les valeurs d'aperçu…")
            self._lancer_capture(apercu=True, ensuite=self._calculer_apercu)
        elif self.commandes:
            self._calculer_apercu(self.commandes)
        else:
            self._journal("Pas encore de commande ffmpeg : le script est en cours de lecture.", True)

    def _calculer_apercu(self, commandes):
        c = commandes[-1]
        if not c.sortie:
            self._journal("La dernière commande ffmpeg n'a pas de fichier de sortie reconnaissable.", True)
            return
        ffmpeg = chemins.trouver_ffmpeg()
        etapes = []
        for p in commandes[:-1]:        # commandes préparatoires dont le fichier manque
            if p.sortie and not os.path.exists(os.path.join(p.cwd, p.sortie)):
                if "-" in [p.args[i + 1] for i, a in enumerate(p.args[:-1]) if a == "-i"]:
                    self._journal(f"Commande préparatoire non rejouable (données sur l'entrée standard) : {p.sortie}", True)
                    continue
                etapes.append(([ffmpeg, *p.args[1:]], p.cwd, None))
        _, extrait = MODES_APERCU[self.mode_apercu.currentIndex()]
        debut = self.timeline.tete() if extrait else 0.0
        total = c.duree or self.timeline.duree()
        if extrait and total:
            debut = max(0.0, min(debut, total - 1))
        duree = min(extrait, total - debut) if extrait and total else (extrait or total)
        self._numero_apercu += 1
        dossier = chemins.dossier_donnees() / "apercus"
        dossier.mkdir(exist_ok=True)
        for ancien in dossier.glob("apercu_*"):
            if str(ancien) != self._apercu_fichier:
                try:
                    ancien.unlink()
                except OSError:
                    pass
        sortie = str(dossier / f"apercu_{self._numero_apercu}{os.path.splitext(c.sortie)[1] or '.mp4'}")
        args, note = ffmpeg_analyse.commande_apercu(c.args, sortie, ffmpeg, debut if extrait else 0.0,
                                                    duree if extrait else None, c)
        etapes.append((args, c.cwd, (sortie, debut, duree)))
        self._journal(f"Aperçu de {debut:.1f} à {debut + (duree or 0):.1f} s" + (f" — {note}" if note else "") + "…",
                      source="aperçu :")
        self._enchainer_apercu(etapes, time.time())

    def _enchainer_apercu(self, etapes, depart):
        args, cwd, final = etapes[0]
        tache = Tache(args, cwd=cwd, env=chemins.environnement(), parent=self)
        duree = final[2] if final else None

        def ligne(texte, err):
            t = None if err else temps_progression(texte)
            if t is None:
                self._journal(texte, err, "ffmpeg :")
            elif final and t >= 0:              # les autres lignes de -progress (t = -1) ne changent rien
                self._progresser(t, duree)
                if duree:
                    self.timeline.set_calcul(final[1], final[1] + duree, t / duree)

        def fini(code):
            if tache is self._apercu:
                self.timeline.set_calcul(None, None, None)
            if tache.arretee or tache is not self._apercu:
                self._occupe()
                return
            if code != 0:
                self._journal(f"ffmpeg a échoué (code {code}).", True, "aperçu :")
                self._apercu = None
                self._occupe()
                self._etat("Aperçu en échec : voir le journal")
                self.onglets.setCurrentWidget(self.journal)
                return
            if len(etapes) > 1:
                self._enchainer_apercu(etapes[1:], depart)
                return
            self._apercu = None
            self._occupe()
            self._charger_apercu(*final)
            self._etat(f"Aperçu calculé en {time.time() - depart:.1f} s")

        tache.ligne.connect(ligne)
        tache.fini.connect(fini)
        self._apercu = tache
        self._progresser(0, duree)
        if final and duree:
            self.timeline.set_calcul(final[1], final[1] + duree, 0.0)
        self._etat("Calcul de l'aperçu…")
        tache.lancer()
        self._occupe()

    def _charger_apercu(self, fichier, debut, duree):
        self._position_a_restaurer = max(0.0, self.timeline.tete() - debut)
        self._apercu_debut = debut
        self._apercu_fichier = fichier
        self.lecteur.setSource(QUrl.fromLocalFile(fichier))
        self.vue.set_apercu_present(True)
        self.timeline.set_apercu(debut, debut + (duree or 0))
        self.l_apercu.setText(f"aperçu {debut:.1f} → {debut + (duree or 0):.1f} s")

    def _statut_media(self, statut):
        if statut == QMediaPlayer.LoadedMedia and self._position_a_restaurer is not None:
            self.lecteur.setPosition(int(self._position_a_restaurer * 1000))
            self._position_a_restaurer = None
            self.lecteur.play()
            self.lecteur.pause()

    # ───── lecture
    def _basculer_lecture(self):
        if self.lecteur.source().isEmpty():
            return
        if self.lecteur.playbackState() == QMediaPlayer.PlayingState:
            self.lecteur.pause()
        else:
            self._depart_lecture = self.timeline.tete()
            self.lecteur.play()

    def _sortie_son_changee(self):
        defaut = QMediaDevices.defaultAudioOutput()
        if defaut.id() != self.sortie_audio.device().id():
            self.sortie_audio.setDevice(defaut)
            self._journal(f"Sortie son : {defaut.description()}")

    def _stop(self):
        """Arrête la lecture et revient où elle avait commencé."""
        self.lecteur.pause()
        self._aller_a(self._depart_lecture)

    def _etat_lecture(self, etat):
        self.transport.set_lecture(etat == QMediaPlayer.PlayingState)

    def _position(self, ms):
        t = self._apercu_debut + ms / 1000
        self.timeline.set_tete(t)
        self.transport.set_temps(t)
        self._suivre_tete()

    def keyPressEvent(self, e):
        """Les flèches quand la vidéo a le clavier (les champs de saisie gardent les leurs)."""
        if not self.timeline.touche_tete(e):
            super().keyPressEvent(e)

    def _aller_a(self, t):
        t = max(0.0, min(t, self.timeline.duree()))
        self.timeline.set_tete(t)
        self.transport.set_temps(t)
        self._suivre_tete()
        if self.lecteur.source().isEmpty():
            return
        local = t - self._apercu_debut
        if 0 <= local <= self.lecteur.duration() / 1000:
            self.lecteur.setPosition(int(local * 1000))
        elif self.lecteur.playbackState() == QMediaPlayer.PlayingState:
            self.lecteur.pause()

    # ───── export : le script lancé pour de vrai
    def lancer_export(self):
        if not self.chemin or (self._export and self._export.en_cours()):
            return
        self._quitter_champ()
        if self._attente:
            self._t_ecriture.stop()
            self._ecrire()
        if self._modifie():
            boite = QMessageBox(QMessageBox.Question, "Modifications non enregistrées",
                                "Le script a des modifications non enregistrées. Les enregistrer avant d'exporter ?",
                                parent=self)
            oui = boite.addButton("Enregistrer et exporter", QMessageBox.AcceptRole)
            sans = boite.addButton("Exporter sans enregistrer", QMessageBox.DestructiveRole)
            boite.addButton("Annuler", QMessageBox.RejectRole)
            boite.setDefaultButton(oui)
            boite.exec()
            if boite.clickedButton() is oui:
                if not self.enregistrer():
                    return
            elif boite.clickedButton() is not sans:
                return
        choix = self._choisir_export()
        if choix is None:
            return
        sortie, format_, options = choix
        total = self.commandes[-1].duree if self.commandes and self.commandes[-1].duree else self.timeline.duree()
        tache = Tache(chemins.commande_lanceur("execute", self.chemin, *options, *self._option_source()),
                      cwd=os.path.dirname(self.chemin), env=chemins.environnement(), parent=self)
        depart = time.time()

        def ligne(texte, err):
            t = None if err else temps_progression(texte)
            if t is None:
                self._journal(texte, err, "export :")
            elif t >= 0:
                self._progresser(t, total)
                self.timeline.set_calcul(0.0, total, t / total if total else 0, "Export")
                self._etat(f"Export en cours : {min(100, t / total * 100):.0f} %" if total else "Export en cours…")

        def fini(code):
            self._export = None
            self._occupe()
            self.timeline.set_calcul(None, None, None)
            if tache.arretee:
                self._journal("Export arrêté.", True)
                self._etat("Export arrêté")
            elif code == 0:
                self._journal(f"Export terminé en {time.time() - depart:.0f} s : {sortie}", source="export :")
                self._etat("Export terminé")
                self._message(f"✓  Film exporté en {time.time() - depart:.0f} s\n{os.path.basename(sortie)}\n"
                              f"{os.path.dirname(sortie)}")
            else:
                self._journal(f"L'export a échoué (code {code}).", True, "export :")
                self._etat("Export en échec : voir le journal")
                self.onglets.setCurrentWidget(self.journal)

        tache.ligne.connect(ligne)
        tache.fini.connect(fini)
        self._export = tache
        self._journal(f"Export vers {sortie} ({ffmpeg_analyse.FORMATS[format_][0]}) : lancement du script…",
                      source="export :")
        self._etat("Export en cours…")
        self.onglets.setCurrentWidget(self.journal)
        tache.lancer()
        self._progresser(0, total)
        self.timeline.set_calcul(0.0, total, 0.0, "Export")
        self._occupe()

    def _choisir_export(self):
        """Emplacement, nom et format du film. Renvoie (fichier, format, options du lanceur) ou None (annulé)."""
        prevue = None
        if self.commandes and self.commandes[-1].sortie:
            c = self.commandes[-1]
            prevue = os.path.normpath(os.path.join(c.cwd, c.sortie))
        dossier = self.preferences.value("dossier_export", "") or (os.path.dirname(prevue) if prevue
                                                                   else os.path.dirname(self.chemin))
        nom = os.path.splitext(os.path.basename(prevue))[0] if prevue else \
            os.path.splitext(os.path.basename(self.chemin))[0]
        filtres = {f"{libelle} (*{ext})": cle for cle, (libelle, ext, _) in ffmpeg_analyse.FORMATS.items()}
        dernier = self.preferences.value("format_export", "script")
        filtre_initial = next((f for f, cle in filtres.items() if cle == dernier), next(iter(filtres)))
        ext = ffmpeg_analyse.FORMATS[filtres[filtre_initial]][1]
        chemin, filtre = QFileDialog.getSaveFileName(self, "Exporter le film", os.path.join(dossier, nom + ext),
                                                     ";;".join(filtres), filtre_initial)
        if not chemin:
            return None
        format_ = filtres.get(filtre, "script")
        ext = ffmpeg_analyse.FORMATS[format_][1]
        chemin = os.path.normpath(chemin if chemin.lower().endswith(ext) else os.path.splitext(chemin)[0] + ext)
        self.preferences.setValue("dossier_export", os.path.dirname(chemin))
        self.preferences.setValue("format_export", format_)
        if prevue is None:
            self._journal("La sortie du script n'est pas connue : le film sera écrit là où le script le prévoit.", True)
            return chemin, format_, []
        return chemin, format_, ["--remplace", prevue, "--sortie", chemin, "--format", format_]

    def arreter(self):
        for tache in (self._apercu, self._export):
            if tache:
                tache.arreter()
        self._occupe()

    def closeEvent(self, e):
        if not self._confirmer_abandon("quitter"):
            e.ignore()
            return
        self._sauver_disposition()
        self.arreter()
        for tache in self._captures.values():
            if tache:
                tache.arreter()
        super().closeEvent(e)
