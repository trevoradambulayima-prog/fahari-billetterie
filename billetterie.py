"""
Fahari Afrika — Billetterie « Lancement » (28 novembre 2026)
Application de bureau : enregistrement des acheteurs, numéro de billet
généré automatiquement, ticket PNG/PDF avec QR code, impression,
envoi WhatsApp, modification / suppression, contrôle à l'entrée.

Au premier lancement, une fenêtre demande les accès MySQL, puis crée
automatiquement la base « fahari_billetterie » et ses tables.
Les réglages sont enregistrés dans config.ini (à côté de l'application).
"""

import configparser
import csv
import os
import platform
import secrets
import subprocess
import sys
import tkinter as tk
import urllib.parse
import webbrowser
from tkinter import ttk, messagebox, filedialog

import mysql.connector
from mysql.connector import Error

from ticket_image import creer_ticket, EVENEMENT

# ---------------------------------------------------------------------
# Dossiers et réglages
# ---------------------------------------------------------------------
# Dossier de travail : à côté du script, ou à côté du .exe si l'application est compilée
DOSSIER_APP = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
               else os.path.dirname(os.path.abspath(__file__)))
FICHIER_CONFIG = os.path.join(DOSSIER_APP, "config.ini")
DOSSIER_TICKETS = os.path.join(DOSSIER_APP, "tickets")

NOM_BASE = "fahari_billetterie"
DATE_QR = "28-11-2026"
INDICATIF_PAYS = "243"           # RDC : 0894899463 -> 243894899463

NAVY, CLAY, GOLD, CREAM = "#0F2544", "#C9552B", "#D9A441", "#FAF1E2"
SYSTEME = platform.system()      # 'Windows', 'Darwin' (macOS) ou 'Linux'

CATEGORIES = [("VIP", "Pass VIP", 50.00, "FA-2026-"),
              ("STANDARD", "Pass Standard", 25.00, "FA-2026-S")]
PAIEMENTS = ["Cash", "Mobile Money", "Carte", "Virement"]


def lire_config():
    cfg = configparser.ConfigParser(interpolation=None)
    if os.path.exists(FICHIER_CONFIG):
        cfg.read(FICHIER_CONFIG, encoding="utf-8")
    if "mysql" not in cfg:
        return None
    m = cfg["mysql"]
    return {"host": m.get("host", "localhost"), "port": m.getint("port", 3306),
            "user": m.get("user", "root"), "password": m.get("password", ""),
            "database": NOM_BASE}


def ecrire_config(c):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["mysql"] = {"host": c["host"], "port": str(c["port"]), "user": c["user"], "password": c["password"]}
    with open(FICHIER_CONFIG, "w", encoding="utf-8") as fh:
        cfg.write(fh)


# ---------------------------------------------------------------------
# Création automatique de la base (identique à base_billetterie.sql)
# ---------------------------------------------------------------------
SCHEMA = [
    f"CREATE DATABASE IF NOT EXISTS {NOM_BASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
    f"USE {NOM_BASE}",
    """CREATE TABLE IF NOT EXISTS categories (
        code VARCHAR(20) PRIMARY KEY,
        libelle VARCHAR(50) NOT NULL,
        prix_usd DECIMAL(8,2) NOT NULL,
        prefixe VARCHAR(20) NOT NULL,
        dernier_num INT UNSIGNED NOT NULL DEFAULT 0,
        places_max INT UNSIGNED NULL
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS billets (
        id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        numero VARCHAR(30) NOT NULL UNIQUE,
        categorie VARCHAR(20) NOT NULL,
        nom VARCHAR(80) NOT NULL,
        prenom VARCHAR(80) NULL,
        telephone VARCHAR(30) NOT NULL,
        email VARCHAR(120) NULL,
        prix_usd DECIMAL(8,2) NOT NULL,
        mode_paiement ENUM('Cash','Mobile Money','Carte','Virement') NOT NULL DEFAULT 'Cash',
        code_secret CHAR(16) NOT NULL UNIQUE,
        statut ENUM('VALIDE','UTILISE','ANNULE') NOT NULL DEFAULT 'VALIDE',
        date_achat DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        date_entree DATETIME NULL,
        CONSTRAINT fk_billet_categorie FOREIGN KEY (categorie) REFERENCES categories(code),
        INDEX idx_nom (nom),
        INDEX idx_tel (telephone)
    ) ENGINE=InnoDB""",
    "DROP PROCEDURE IF EXISTS vendre_billet",
    """CREATE PROCEDURE vendre_billet(
        IN p_categorie VARCHAR(20), IN p_nom VARCHAR(80), IN p_prenom VARCHAR(80),
        IN p_telephone VARCHAR(30), IN p_email VARCHAR(120), IN p_paiement VARCHAR(20),
        IN p_secret CHAR(16), OUT p_numero VARCHAR(30))
    BEGIN
        DECLARE v_num INT UNSIGNED;
        DECLARE v_prefix VARCHAR(20);
        DECLARE v_prix DECIMAL(8,2);
        DECLARE v_max INT UNSIGNED;
        DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
        START TRANSACTION;
        SELECT dernier_num + 1, prefixe, prix_usd, places_max
          INTO v_num, v_prefix, v_prix, v_max
          FROM categories WHERE code = p_categorie FOR UPDATE;
        IF v_prefix IS NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Catégorie inconnue';
        END IF;
        IF v_max IS NOT NULL AND v_num > v_max THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Plus de places disponibles dans cette catégorie';
        END IF;
        SET p_numero = CONCAT(v_prefix, LPAD(v_num, 4, '0'));
        UPDATE categories SET dernier_num = v_num WHERE code = p_categorie;
        INSERT INTO billets (numero, categorie, nom, prenom, telephone, email, prix_usd, mode_paiement, code_secret)
        VALUES (p_numero, p_categorie, p_nom, p_prenom, p_telephone, NULLIF(p_email, ''), v_prix, p_paiement, p_secret);
        COMMIT;
    END""",
    """CREATE OR REPLACE VIEW bilan_ventes AS
       SELECT c.libelle AS categorie, COUNT(b.id) AS billets_vendus,
              COALESCE(SUM(b.prix_usd), 0) AS total_usd,
              SUM(b.statut = 'UTILISE') AS entrees_validees
         FROM categories c
         LEFT JOIN billets b ON b.categorie = c.code AND b.statut <> 'ANNULE'
        GROUP BY c.code, c.libelle""",
]


def installer_base(c):
    """Se connecte au serveur MySQL (sans base), crée la base si besoin."""
    serveur = {k: v for k, v in c.items() if k != "database"}
    cnx = mysql.connector.connect(**serveur)
    try:
        cur = cnx.cursor()
        for sql in SCHEMA:
            cur.execute(sql)
        for code, libelle, prix, prefixe in CATEGORIES:
            cur.execute("""INSERT INTO categories (code, libelle, prix_usd, prefixe) VALUES (%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE libelle=VALUES(libelle), prix_usd=VALUES(prix_usd)""",
                        (code, libelle, prix, prefixe))
            # Les billets déjà enregistrés prennent aussi le prix actuel de leur catégorie
            cur.execute("UPDATE billets SET prix_usd=%s WHERE categorie=%s AND prix_usd<>%s",
                        (prix, code, prix))
        cnx.commit()
        cur.close()
    finally:
        cnx.close()


# ---------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------
class Database:
    def __init__(self, config):
        self.config = config

    def _connect(self):
        return mysql.connector.connect(**self.config)

    def categories(self):
        with self._connect() as cnx, cnx.cursor(dictionary=True) as cur:
            cur.execute("SELECT code, libelle, prix_usd FROM categories ORDER BY prix_usd DESC")
            return cur.fetchall()

    def vendre(self, categorie, nom, prenom, telephone, email, paiement):
        """Appelle la procédure stockée ; renvoie le numéro généré."""
        secret = secrets.token_hex(8).upper()  # 16 caractères, anti-fraude
        with self._connect() as cnx, cnx.cursor() as cur:
            args = cur.callproc(
                "vendre_billet",
                (categorie, nom, prenom, telephone, email, paiement, secret, ""),
            )
            cnx.commit()
            return args[7]

    def modifier(self, numero, nom, prenom, telephone, email, paiement):
        with self._connect() as cnx, cnx.cursor() as cur:
            cur.execute("""UPDATE billets SET nom=%s, prenom=%s, telephone=%s, email=NULLIF(%s,''),
                                  mode_paiement=%s WHERE numero=%s""",
                        (nom, prenom, telephone, email, paiement, numero))
            cnx.commit()
            return cur.rowcount >= 0

    def supprimer(self, numero):
        with self._connect() as cnx, cnx.cursor() as cur:
            cur.execute("DELETE FROM billets WHERE numero=%s", (numero,))
            cnx.commit()
            return cur.rowcount == 1

    def lister(self, recherche=""):
        sql = """SELECT numero, categorie, nom, prenom, telephone, prix_usd,
                        mode_paiement, statut, DATE_FORMAT(date_achat, '%d/%m %H:%i')
                   FROM billets"""
        params = ()
        if recherche:
            sql += " WHERE numero LIKE %s OR nom LIKE %s OR prenom LIKE %s OR telephone LIKE %s"
            like = f"%{recherche}%"
            params = (like, like, like, like)
        sql += " ORDER BY id DESC"
        with self._connect() as cnx, cnx.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def billet(self, numero):
        with self._connect() as cnx, cnx.cursor(dictionary=True) as cur:
            cur.execute("SELECT * FROM billets WHERE numero = %s", (numero,))
            return cur.fetchone()

    def valider_entree(self, contenu_scan):
        """Accepte le texte complet du QR ou juste le numéro. Renvoie (ok, message)."""
        morceaux = contenu_scan.strip().split("|")
        if len(morceaux) >= 6:
            numero, secret = morceaux[4], morceaux[5]
        else:
            numero, secret = contenu_scan.strip(), None

        with self._connect() as cnx, cnx.cursor(dictionary=True) as cur:
            cur.execute("SELECT * FROM billets WHERE numero = %s FOR UPDATE", (numero,))
            b = cur.fetchone()
            if not b:
                return False, f"Billet {numero} introuvable."
            if secret is not None and secret != b["code_secret"]:
                return False, f"QR code invalide pour {numero} (faux billet ?)."
            if b["statut"] == "ANNULE":
                return False, f"Billet {numero} ANNULÉ."
            if b["statut"] == "UTILISE":
                return False, f"Billet {numero} DÉJÀ UTILISÉ le {b['date_entree']:%d/%m à %H:%M}."
            cur.execute(
                "UPDATE billets SET statut='UTILISE', date_entree=NOW() WHERE id=%s", (b["id"],)
            )
            cnx.commit()
            nom = f"{b['nom']} {b['prenom'] or ''}".strip()
            return True, f"ENTRÉE VALIDÉE — {nom} · {b['categorie']} · {numero}"

    def annuler(self, numero):
        with self._connect() as cnx, cnx.cursor() as cur:
            cur.execute(
                "UPDATE billets SET statut='ANNULE' WHERE numero=%s AND statut='VALIDE'", (numero,)
            )
            cnx.commit()
            return cur.rowcount == 1

    def bilan(self):
        with self._connect() as cnx, cnx.cursor() as cur:
            cur.execute("SELECT * FROM bilan_ventes")
            return cur.fetchall()


# ---------------------------------------------------------------------
# Ticket, impression, WhatsApp
# ---------------------------------------------------------------------
def contenu_qr(b):
    """Même format que sur les tickets imprimés, + code secret anti-fraude."""
    return f"FAHARI-AFRIKA|{EVENEMENT['titre']}|{b['categorie']}|{DATE_QR}|{b['numero']}|{b['code_secret']}"


def fabriquer_ticket(b):
    """Crée (ou recrée) Ticket_<numero>.png et .pdf ; renvoie (png, pdf)."""
    return creer_ticket(b, contenu_qr(b), DOSSIER_TICKETS)


def supprimer_fichiers_ticket(numero):
    for ext in (".png", ".pdf"):
        chemin = os.path.join(DOSSIER_TICKETS, f"Ticket_{numero}{ext}")
        try:
            os.remove(chemin)
        except OSError:
            pass


def ouvrir(chemin):
    chemin = os.path.abspath(chemin)
    if SYSTEME == "Windows":
        os.startfile(chemin)
    elif SYSTEME == "Darwin":
        subprocess.Popen(["open", chemin])
    else:
        subprocess.Popen(["xdg-open", chemin])


def imprimer(chemin_pdf):
    chemin_pdf = os.path.abspath(chemin_pdf)
    if SYSTEME == "Windows":
        os.startfile(chemin_pdf, "print")      # imprimante par défaut de Windows
    else:
        subprocess.Popen(["lp", chemin_pdf])   # macOS / Linux (CUPS)


def montrer_dans_dossier(chemin):
    chemin = os.path.abspath(chemin)
    if SYSTEME == "Windows":
        subprocess.Popen(["explorer", "/select,", chemin])
    elif SYSTEME == "Darwin":
        subprocess.Popen(["open", "-R", chemin])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(chemin)])


def copier_image_presse_papiers(chemin_png):
    """Windows : copie l'image du ticket pour un simple Ctrl+V dans WhatsApp."""
    if SYSTEME != "Windows":
        return False
    chemin = os.path.abspath(chemin_png).replace("'", "''")
    script = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
              f"[System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{chemin}'))")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                           capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def numero_whatsapp(telephone):
    """0894899463 -> 243894899463 ; +243 89... -> 24389..."""
    chiffres = "".join(c for c in str(telephone) if c.isdigit())
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if chiffres.startswith("0"):
        chiffres = INDICATIF_PAYS + chiffres[1:]
    elif len(chiffres) == 9:
        chiffres = INDICATIF_PAYS + chiffres
    return chiffres


def envoyer_whatsapp(b, chemin_png):
    """Ouvre la discussion WhatsApp de l'acheteur avec un message prêt.
    Le ticket est copié (Windows) pour être collé avec Ctrl+V,
    sinon son dossier est ouvert pour le glisser dans la discussion."""
    nom = f"{b['prenom'] or ''} {b['nom']}".strip()
    message = (
        f"Bonjour {nom},\n"
        f"Merci pour votre achat ! Voici votre billet Fahari Afrika – {EVENEMENT['titre']}.\n"
        f"N° {b['numero']} · {b['categorie']} · {float(b['prix_usd']):.0f} $\n"
        f"Le {EVENEMENT['date']} à {EVENEMENT['heure']}\n"
        f"Départ : {EVENEMENT['depart']}\n"
        f"Arrivée : {EVENEMENT['arrivee']}, {EVENEMENT['arrivee_ville']}\n"
        f"Présentez le QR code à l'entrée. Contact : {EVENEMENT['contact']}"
    )
    tel = numero_whatsapp(b["telephone"])
    texte = urllib.parse.quote(message)

    copie = copier_image_presse_papiers(chemin_png)
    if not copie:
        montrer_dans_dossier(chemin_png)

    ouvert = False
    if SYSTEME == "Windows":                 # WhatsApp Desktop installé
        try:
            os.startfile(f"whatsapp://send?phone={tel}&text={texte}")
            ouvert = True
        except OSError:
            pass
    if not ouvert:                           # WhatsApp Web via le navigateur
        webbrowser.open(f"https://wa.me/{tel}?text={texte}")
    return copie


# ---------------------------------------------------------------------
# Fenêtre de connexion MySQL (premier lancement ou erreur de connexion)
# ---------------------------------------------------------------------
def demander_connexion(racine, actuelle=None, erreur=None):
    """Affiche le formulaire de connexion ; renvoie la config valide ou None."""
    c = actuelle or {"host": "localhost", "port": 3306, "user": "root", "password": ""}
    resultat = {}

    fen = tk.Toplevel(racine)
    fen.title("Connexion à MySQL")
    fen.configure(bg=CREAM, padx=24, pady=20)
    fen.resizable(False, False)
    fen.grab_set()

    tk.Label(fen, text="Connexion au serveur MySQL", bg=CREAM, fg=NAVY,
             font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(fen, text="La base « fahari_billetterie » sera créée automatiquement.\n"
                       "Avec XAMPP / WAMP : utilisateur root, mot de passe souvent vide.",
             bg=CREAM, fg="#3D5578", justify="left", font=("Segoe UI", 10)).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(4, 12))

    vars_ = {}
    for i, (cle, lib) in enumerate([("host", "Serveur"), ("port", "Port"),
                                     ("user", "Utilisateur"), ("password", "Mot de passe")], start=2):
        tk.Label(fen, text=lib, bg=CREAM, fg=NAVY, font=("Segoe UI", 11)).grid(row=i, column=0, sticky="w", pady=4)
        v = tk.StringVar(value=str(c.get(cle, "")))
        e = ttk.Entry(fen, textvariable=v, width=30, show="•" if cle == "password" else "")
        e.grid(row=i, column=1, sticky="w", pady=4, padx=(12, 0))
        vars_[cle] = v

    msg = tk.Label(fen, text=erreur or "", bg=CREAM, fg="#B42318", wraplength=380, justify="left",
                   font=("Segoe UI", 10))
    msg.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def valider():
        try:
            port = int(vars_["port"].get().strip() or 3306)
        except ValueError:
            msg.config(text="Le port doit être un nombre (3306 par défaut).")
            return
        essai = {"host": vars_["host"].get().strip() or "localhost", "port": port,
                 "user": vars_["user"].get().strip() or "root", "password": vars_["password"].get(),
                 "database": NOM_BASE}
        msg.config(text="Connexion en cours…", fg="#3D5578")
        fen.update_idletasks()
        try:
            installer_base(essai)
        except Error as e:
            msg.config(text=f"Connexion impossible : {e.msg if hasattr(e, 'msg') else e}\n"
                            "Vérifiez que MySQL est démarré (XAMPP : bouton Start à côté de MySQL).",
                       fg="#B42318")
            return
        ecrire_config(essai)
        resultat["config"] = essai
        fen.destroy()

    ttk.Button(fen, text="Se connecter", command=valider).grid(row=7, column=1, sticky="e", pady=(14, 0))
    fen.bind("<Return>", lambda _: valider())
    fen.protocol("WM_DELETE_WINDOW", fen.destroy)
    racine.wait_window(fen)
    return resultat.get("config")


# ---------------------------------------------------------------------
# Fenêtre « Modifier un acheteur »
# ---------------------------------------------------------------------
class FenetreModifier(tk.Toplevel):
    def __init__(self, app, billet):
        super().__init__(app)
        self.app, self.b = app, billet
        self.title(f"Modifier le billet {billet['numero']}")
        self.configure(bg=CREAM, padx=24, pady=20)
        self.resizable(False, False)
        self.grab_set()

        tk.Label(self, text=f"Billet {billet['numero']} · {billet['categorie']} · "
                            f"{float(billet['prix_usd']):.0f} $",
                 bg=CREAM, fg=NAVY, font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2,
                                                                        sticky="w", pady=(0, 12))
        self.v = {
            "nom": tk.StringVar(value=billet["nom"]),
            "prenom": tk.StringVar(value=billet["prenom"] or ""),
            "telephone": tk.StringVar(value=billet["telephone"]),
            "email": tk.StringVar(value=billet["email"] or ""),
            "paiement": tk.StringVar(value=billet["mode_paiement"]),
        }
        lignes = [("Nom *", ttk.Entry(self, textvariable=self.v["nom"], width=34)),
                  ("Prénom", ttk.Entry(self, textvariable=self.v["prenom"], width=34)),
                  ("Téléphone *", ttk.Entry(self, textvariable=self.v["telephone"], width=34)),
                  ("E-mail", ttk.Entry(self, textvariable=self.v["email"], width=34)),
                  ("Paiement", ttk.Combobox(self, textvariable=self.v["paiement"], values=PAIEMENTS,
                                            state="readonly", width=31))]
        for i, (lib, w) in enumerate(lignes, start=1):
            tk.Label(self, text=lib, bg=CREAM, fg=NAVY, font=("Segoe UI", 11)).grid(row=i, column=0, sticky="w", pady=5)
            w.grid(row=i, column=1, sticky="w", pady=5, padx=(12, 0))
        tk.Label(self, text="La catégorie et le numéro ne changent pas. Pour changer de catégorie,\n"
                            "supprimez ce billet et enregistrez-en un nouveau.",
                 bg=CREAM, fg="#3D5578", justify="left", font=("Segoe UI", 9)).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        boutons = ttk.Frame(self)
        boutons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(boutons, text="Annuler", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(boutons, text="Enregistrer les modifications", style="Accent.TButton",
                   command=self.enregistrer).pack(side="left")

    def enregistrer(self):
        nom = self.v["nom"].get().strip().upper()
        tel = self.v["telephone"].get().strip()
        if not nom or not tel:
            messagebox.showwarning("Champs manquants", "Nom et téléphone sont obligatoires.", parent=self)
            return
        try:
            self.app.db.modifier(self.b["numero"], nom, self.v["prenom"].get().strip(), tel,
                                 self.v["email"].get().strip(), self.v["paiement"].get())
            fabriquer_ticket(self.app.db.billet(self.b["numero"]))   # ticket mis à jour
        except Exception as e:
            messagebox.showerror("Erreur", f"Modification impossible :\n{e}", parent=self)
            return
        self.destroy()
        self.app.rafraichir_liste()
        self.app.flash(f"Billet {self.b['numero']} modifié — ticket PNG/PDF mis à jour.")


# ---------------------------------------------------------------------
# Interface principale
# ---------------------------------------------------------------------
class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fahari Afrika — Billetterie Lancement")
        self.geometry("1150x700")
        self.minsize(980, 620)
        self.configure(bg=CREAM)
        self._styles()
        self.dernier = None          # (billet, png, pdf) de la dernière vente

        # Connexion : config.ini, sinon fenêtre de connexion
        self.withdraw()
        config = lire_config()
        erreur = None
        if config:
            try:
                installer_base(config)          # vérifie la connexion + met la base à jour
            except Error as e:
                erreur = f"Connexion impossible : {getattr(e, 'msg', e)}"
                config = None
        if not config:
            config = demander_connexion(self, lire_config(), erreur)
        if not config:
            self.destroy()
            return
        self.db = Database(config)
        self.deiconify()

        entete = tk.Frame(self, bg=NAVY, height=60)
        entete.pack(fill="x")
        tk.Label(entete, text="FAHARI AFRIKA", bg=NAVY, fg=CREAM,
                 font=("Segoe UI", 18, "bold")).pack(side="left", padx=20, pady=12)
        tk.Label(entete, text="Billetterie · Lancement · 28 novembre 2026", bg=NAVY, fg=GOLD,
                 font=("Segoe UI", 12)).pack(side="left")
        tk.Button(entete, text="Connexion MySQL", bg=NAVY, fg=CREAM, relief="flat", bd=0,
                  activebackground="#1B355E", activeforeground=CREAM, font=("Segoe UI", 9),
                  command=self.changer_connexion).pack(side="right", padx=16)

        onglets = ttk.Notebook(self)
        onglets.pack(fill="both", expand=True, padx=12, pady=12)
        self.onglet_vente = ttk.Frame(onglets, padding=16)
        self.onglet_liste = ttk.Frame(onglets, padding=16)
        self.onglet_entree = ttk.Frame(onglets, padding=16)
        onglets.add(self.onglet_vente, text="  Vendre un billet  ")
        onglets.add(self.onglet_liste, text="  Liste des acheteurs  ")
        onglets.add(self.onglet_entree, text="  Contrôle à l'entrée  ")

        self._construire_vente()
        self._construire_liste()
        self._construire_entree()
        self.rafraichir_liste()
        self.champ_nom.focus_set()

    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=CREAM)
        s.configure("TLabel", background=CREAM, foreground=NAVY, font=("Segoe UI", 11))
        s.configure("Titre.TLabel", font=("Segoe UI", 15, "bold"))
        s.configure("TNotebook", background=CREAM)
        s.configure("TNotebook.Tab", font=("Segoe UI", 11, "bold"), padding=(10, 6))
        s.configure("Accent.TButton", font=("Segoe UI", 11, "bold"),
                    background=CLAY, foreground="white", padding=8)
        s.map("Accent.TButton", background=[("active", NAVY)])
        s.configure("WhatsApp.TButton", font=("Segoe UI", 10, "bold"),
                    background="#1F8F4E", foreground="white", padding=6)
        s.map("WhatsApp.TButton", background=[("active", "#166B3A")])
        s.configure("Danger.TButton", font=("Segoe UI", 10, "bold"),
                    background="#B42318", foreground="white", padding=6)
        s.map("Danger.TButton", background=[("active", "#7F1D1D")])
        s.configure("TButton", font=("Segoe UI", 10), padding=6)
        s.configure("Treeview", font=("Segoe UI", 10), rowheight=26)
        s.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def changer_connexion(self):
        config = demander_connexion(self, lire_config())
        if config:
            self.db = Database(config)
            self.rafraichir_liste()

    # ---------------- Onglet 1 : vente ----------------
    def _construire_vente(self):
        f = self.onglet_vente
        ttk.Label(f, text="Nouvel acheteur", style="Titre.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))

        try:
            self.cats = self.db.categories()
        except Error as e:
            messagebox.showerror("MySQL", f"Lecture des catégories impossible :\n{e}")
            self.cats = []
        self.libelles = [f"{c['libelle']} — {c['prix_usd']:.0f} $" for c in self.cats]

        self.v_nom, self.v_prenom = tk.StringVar(), tk.StringVar()
        self.v_tel, self.v_email = tk.StringVar(), tk.StringVar()
        self.v_cat = tk.StringVar(value=self.libelles[0] if self.libelles else "")
        self.v_paie = tk.StringVar(value="Cash")

        self.champ_nom = ttk.Entry(f, textvariable=self.v_nom, width=40)
        champs = [
            ("Nom *", self.champ_nom),
            ("Prénom", ttk.Entry(f, textvariable=self.v_prenom, width=40)),
            ("Téléphone (WhatsApp) *", ttk.Entry(f, textvariable=self.v_tel, width=40)),
            ("E-mail", ttk.Entry(f, textvariable=self.v_email, width=40)),
            ("Catégorie *", ttk.Combobox(f, textvariable=self.v_cat, values=self.libelles,
                                         state="readonly", width=37)),
            ("Paiement *", ttk.Combobox(f, textvariable=self.v_paie, state="readonly", width=37,
                                        values=PAIEMENTS)),
        ]
        for i, (lib, w) in enumerate(champs, start=1):
            ttk.Label(f, text=lib).grid(row=i, column=0, sticky="w", pady=6, padx=(0, 16))
            w.grid(row=i, column=1, sticky="w", pady=6)
            if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox):
                w.bind("<Return>", lambda _: self.enregistrer())

        ttk.Button(f, text="Enregistrer et générer le ticket", style="Accent.TButton",
                   command=self.enregistrer).grid(row=8, column=1, sticky="w", pady=18)

        # Zone « ticket prêt » (apparaît après une vente)
        self.zone_ticket = ttk.Frame(f)
        self.zone_ticket.grid(row=9, column=0, columnspan=2, sticky="w")
        self.resultat = tk.Label(self.zone_ticket, text="", bg=CREAM, fg=CLAY, justify="left",
                                 font=("Segoe UI", 12, "bold"))
        self.resultat.pack(anchor="w", pady=(0, 10))
        self.boutons_ticket = ttk.Frame(self.zone_ticket)
        ttk.Button(self.boutons_ticket, text="Voir le ticket (PNG)",
                   command=lambda: self._action_derniere("png")).pack(side="left")
        ttk.Button(self.boutons_ticket, text="Ouvrir le PDF",
                   command=lambda: self._action_derniere("pdf")).pack(side="left", padx=8)
        ttk.Button(self.boutons_ticket, text="Imprimer",
                   command=lambda: self._action_derniere("imprimer")).pack(side="left")
        ttk.Button(self.boutons_ticket, text="Envoyer sur WhatsApp", style="WhatsApp.TButton",
                   command=lambda: self._action_derniere("whatsapp")).pack(side="left", padx=8)

        self.apercu = tk.Label(f, bg=CREAM)
        self.apercu.grid(row=0, column=2, rowspan=10, sticky="ne", padx=(40, 0))
        f.columnconfigure(2, weight=1)

    def enregistrer(self):
        nom, tel = self.v_nom.get().strip(), self.v_tel.get().strip()
        if not nom or not tel or not self.v_cat.get():
            messagebox.showwarning("Champs manquants", "Nom, téléphone et catégorie sont obligatoires.")
            return
        code_cat = self.cats[self.libelles.index(self.v_cat.get())]["code"]
        try:
            numero = self.db.vendre(code_cat, nom.upper(), self.v_prenom.get().strip(), tel,
                                    self.v_email.get().strip(), self.v_paie.get())
            billet = self.db.billet(numero)
        except Error as e:
            messagebox.showerror("Erreur", f"Le billet n'a pas été enregistré :\n{getattr(e, 'msg', e)}")
            return

        try:
            png, pdf = fabriquer_ticket(billet)
        except Exception as e:
            messagebox.showerror("Ticket", f"Billet {numero} enregistré, mais le ticket "
                                           f"n'a pas pu être créé :\n{e}")
            png = pdf = None

        self.dernier = (billet, png, pdf)
        self.resultat.config(text=f"✔ Billet {numero} créé pour {nom.upper()} ({code_cat})"
                                  + (f"\nTicket : {os.path.abspath(png)}" if png else ""))
        if png:
            self.boutons_ticket.pack(anchor="w")
            self._afficher_apercu(png)

        # Formulaire vidé pour le prochain acheteur (catégorie et paiement gardés)
        for v in (self.v_nom, self.v_prenom, self.v_tel, self.v_email):
            v.set("")
        self.champ_nom.focus_set()
        self.rafraichir_liste()

    def _afficher_apercu(self, png):
        try:
            from PIL import Image, ImageTk
            img = Image.open(png)
            img.thumbnail((260, 580))
            self._apercu_img = ImageTk.PhotoImage(img)
            self.apercu.config(image=self._apercu_img)
        except Exception:
            pass

    def _action_derniere(self, action):
        if not self.dernier or not self.dernier[1]:
            return
        billet = self.db.billet(self.dernier[0]["numero"])
        if not billet:
            messagebox.showinfo("Billet supprimé", "Ce billet a été supprimé.")
            return
        png, pdf = fabriquer_ticket(billet)
        self._action_ticket(action, billet, png, pdf)

    def _action_ticket(self, action, billet, png, pdf):
        try:
            if action == "png":
                ouvrir(png)
            elif action == "pdf":
                ouvrir(pdf)
            elif action == "imprimer":
                imprimer(pdf)
            elif action == "whatsapp":
                copie = envoyer_whatsapp(billet, png)
                astuce = ("Le ticket est copié : dans la discussion WhatsApp, faites Ctrl+V puis Envoyer."
                          if copie else
                          "Le dossier du ticket est ouvert : glissez le fichier PNG (ou PDF) "
                          "dans la discussion WhatsApp, puis Envoyer.")
                messagebox.showinfo("WhatsApp",
                                    f"Discussion ouverte avec +{numero_whatsapp(billet['telephone'])}.\n\n{astuce}")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    # ---------------- Onglet 2 : liste ----------------
    def _construire_liste(self):
        f = self.onglet_liste
        barre = ttk.Frame(f)
        barre.pack(fill="x", pady=(0, 6))
        ttk.Label(barre, text="Rechercher :").pack(side="left")
        self.v_recherche = tk.StringVar()
        e = ttk.Entry(barre, textvariable=self.v_recherche, width=24)
        e.pack(side="left", padx=8)
        e.bind("<Return>", lambda _: self.rafraichir_liste())
        ttk.Button(barre, text="Chercher", command=self.rafraichir_liste).pack(side="left")
        ttk.Button(barre, text="Exporter CSV", command=self.exporter_csv).pack(side="right")

        actions = ttk.Frame(f)
        actions.pack(fill="x", pady=(0, 10))
        ttk.Button(actions, text="Modifier", command=self.modifier_selection).pack(side="left")
        ttk.Button(actions, text="Supprimer", style="Danger.TButton",
                   command=self.supprimer_selection).pack(side="left", padx=(6, 18))
        ttk.Button(actions, text="Voir le ticket", command=lambda: self._action_selection("png")).pack(side="left")
        ttk.Button(actions, text="Imprimer", command=lambda: self._action_selection("imprimer")).pack(side="left", padx=6)
        ttk.Button(actions, text="WhatsApp", style="WhatsApp.TButton",
                   command=lambda: self._action_selection("whatsapp")).pack(side="left")
        ttk.Button(actions, text="Annuler le billet", command=self.annuler_selection).pack(side="left", padx=6)

        cadre = ttk.Frame(f)
        cadre.pack(fill="both", expand=True)
        cols = ("Numéro", "Catégorie", "Nom", "Prénom", "Téléphone", "Prix $", "Paiement", "Statut", "Achat")
        largeurs = (120, 90, 150, 120, 120, 60, 110, 80, 90)
        self.table = ttk.Treeview(cadre, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, largeurs):
            self.table.heading(c, text=c)
            self.table.column(c, width=w, anchor="w")
        self.table.tag_configure("UTILISE", foreground="#3D5578")
        self.table.tag_configure("ANNULE", foreground="#999999")
        defil = ttk.Scrollbar(cadre, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=defil.set)
        self.table.pack(side="left", fill="both", expand=True)
        defil.pack(side="right", fill="y")
        self.table.bind("<Double-1>", lambda _: self.modifier_selection())
        self.table.bind("<Delete>", lambda _: self.supprimer_selection())

        self.lbl_bilan = ttk.Label(f, text="", font=("Segoe UI", 11, "bold"))
        self.lbl_bilan.pack(anchor="w", pady=(10, 0))
        self.lbl_flash = ttk.Label(f, text="", foreground=CLAY)
        self.lbl_flash.pack(anchor="w")

    def flash(self, texte):
        self.lbl_flash.config(text=texte)
        self.after(6000, lambda: self.lbl_flash.config(text=""))

    def rafraichir_liste(self):
        try:
            lignes = self.db.lister(self.v_recherche.get().strip())
            bilan = self.db.bilan()
        except Error as e:
            self.lbl_bilan.config(text=f"Base de données inaccessible : {getattr(e, 'msg', e)}")
            return
        self.table.delete(*self.table.get_children())
        for l in lignes:
            self.table.insert("", "end", iid=l[0], values=l, tags=(l[7],))
        self.lbl_bilan.config(text="   |   ".join(
            f"{cat} : {int(n)} vendus · {float(t):.0f} $ · {int(e or 0)} entrés" for cat, n, t, e in bilan))

    def _billet_selectionne(self):
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo("Sélection", "Cliquez d'abord sur un acheteur dans la liste.")
            return None
        return self.db.billet(sel[0])

    def modifier_selection(self):
        b = self._billet_selectionne()
        if b:
            FenetreModifier(self, b)

    def supprimer_selection(self):
        b = self._billet_selectionne()
        if not b:
            return
        nom = f"{b['nom']} {b['prenom'] or ''}".strip()
        if not messagebox.askyesno(
                "Supprimer",
                f"Supprimer définitivement le billet {b['numero']} de {nom} ?\n\n"
                "Cette action efface l'acheteur de la base et son ticket.\n"
                "Le numéro ne sera pas réutilisé.\n\n"
                "(Pour garder une trace, utilisez plutôt « Annuler le billet ».)",
                icon="warning"):
            return
        try:
            self.db.supprimer(b["numero"])
        except Error as e:
            messagebox.showerror("Erreur", f"Suppression impossible :\n{getattr(e, 'msg', e)}")
            return
        supprimer_fichiers_ticket(b["numero"])
        self.rafraichir_liste()
        self.flash(f"Billet {b['numero']} supprimé.")

    def _action_selection(self, action):
        b = self._billet_selectionne()
        if not b:
            return
        if b["statut"] == "ANNULE" and action != "png":
            messagebox.showwarning("Billet annulé", f"Le billet {b['numero']} est annulé.")
            return
        png, pdf = fabriquer_ticket(b)
        self._action_ticket(action, b, png, pdf)

    def annuler_selection(self):
        b = self._billet_selectionne()
        if b and messagebox.askyesno("Annuler", f"Annuler le billet {b['numero']} ?\n"
                                                "Il reste dans la liste mais sera refusé à l'entrée."):
            if self.db.annuler(b["numero"]):
                self.rafraichir_liste()
            else:
                messagebox.showwarning("Impossible", "Seul un billet VALIDE peut être annulé.")

    def exporter_csv(self):
        chemin = filedialog.asksaveasfilename(defaultextension=".csv",
                                              initialfile="acheteurs_lancement.csv")
        if not chemin:
            return
        with open(chemin, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([self.table.heading(c)["text"] for c in self.table["columns"]])
            for item in self.table.get_children():
                w.writerow(self.table.item(item)["values"])
        messagebox.showinfo("Export", f"Liste exportée :\n{chemin}")

    # ---------------- Onglet 3 : entrée ----------------
    def _construire_entree(self):
        f = self.onglet_entree
        ttk.Label(f, text="Scannez le QR code ou tapez le numéro du billet",
                  style="Titre.TLabel").pack(anchor="w")
        ttk.Label(f, text="Un lecteur QR USB tape le texte puis « Entrée » automatiquement.").pack(
            anchor="w", pady=(4, 14))
        self.v_scan = tk.StringVar()
        champ = ttk.Entry(f, textvariable=self.v_scan, width=70, font=("Segoe UI", 13))
        champ.pack(anchor="w")
        champ.bind("<Return>", lambda _: self.verifier())
        ttk.Button(f, text="Valider l'entrée", style="Accent.TButton",
                   command=self.verifier).pack(anchor="w", pady=12)
        self.lbl_entree = tk.Label(f, text="", bg=CREAM, font=("Segoe UI", 18, "bold"),
                                   wraplength=900, justify="left")
        self.lbl_entree.pack(anchor="w", pady=20)
        self.champ_scan = champ

    def verifier(self):
        texte = self.v_scan.get().strip()
        if not texte:
            return
        try:
            ok, msg = self.db.valider_entree(texte)
        except Error as e:
            ok, msg = False, f"Erreur base de données : {getattr(e, 'msg', e)}"
        self.lbl_entree.config(text=msg, fg="#1B7F3B" if ok else "#B42318")
        self.v_scan.set("")
        self.champ_scan.focus_set()
        self.rafraichir_liste()


if __name__ == "__main__":
    app = Application()
    try:
        if app.winfo_exists():
            app.mainloop()
    except tk.TclError:
        pass    # fenêtre fermée avant la connexion
