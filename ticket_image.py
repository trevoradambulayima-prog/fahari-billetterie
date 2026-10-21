"""
Génération du ticket Fahari Afrika en PNG et PDF (format téléphone, 1080 x 2400).
Utilisé par billetterie.py ; ne dépend que de Pillow et qrcode.

Polices : si vous placez Outfit-Bold.ttf / Outfit-Regular.ttf (Google Fonts)
dans un dossier « fonts » à côté de ce fichier, elles sont utilisées en priorité.
Sinon : Segoe UI / Arial (Windows), Arial (macOS) ou DejaVu (Linux).
"""

import os
import sys
from PIL import Image, ImageDraw, ImageFont

try:
    import qrcode
except ImportError:
    qrcode = None

# Dossier des ressources (logo, polices) : à côté du script, ou dans l'exécutable .exe
ICI = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(ICI, "logo_fahari.png")

NAVY, CLAY, GOLD, CREAM, SLATE = "#0F2544", "#C9552B", "#D9A441", "#FAF1E2", "#3D5578"
CLAY_CLAIR = "#E07A52"

# Détails de l'événement (identiques aux tickets imprimés)
EVENEMENT = {
    "titre": "LANCEMENT",
    "date": "28 nov. 2026",
    "heure": "6h30",
    "depart": "Rawban 7e rue Limete, Kinshasa",
    "arrivee": "Cosmos Beach",
    "arrivee_ville": "Kinshasa",
    "contact": "0894899463",
}

_POLICES = {
    True: ["fonts/Outfit-Bold.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    False: ["fonts/Outfit-Regular.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def police(taille, gras=False):
    for chemin in _POLICES[gras]:
        p = chemin if os.path.isabs(chemin) else os.path.join(ICI, chemin)
        if os.path.exists(p):
            return ImageFont.truetype(p, taille)
    return ImageFont.load_default(taille)


def _espace(d, xy, texte, f, couleur, esp=0.0):
    """Texte avec espacement des lettres (esp en fraction de la taille)."""
    x, y = xy
    pas = f.size * esp
    for c in texte:
        d.text((x, y), c, font=f, fill=couleur)
        x += d.textlength(c, font=f) + pas
    return x


def _largeur_espacee(d, texte, f, esp):
    return sum(d.textlength(c, font=f) for c in texte) + f.size * esp * (len(texte) - 1)


def _couper(d, texte, f, largeur_max):
    mots, lignes, ligne = texte.split(), [], ""
    for m in mots:
        essai = f"{ligne} {m}".strip()
        if d.textlength(essai, font=f) <= largeur_max:
            ligne = essai
        else:
            lignes.append(ligne)
            ligne = m
    lignes.append(ligne)
    return lignes


def _losange(d, cx, cy, r, couleur):
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=couleur)


def image_qr(contenu, taille):
    if qrcode is None:
        raise RuntimeError("Installez le module qrcode :  pip install qrcode[pil]")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=1)
    qr.add_data(contenu)
    qr.make(fit=True)
    img = qr.make_image(fill_color=NAVY, back_color="white").convert("RGB")
    return img.resize((taille, taille), Image.NEAREST)


def creer_ticket(billet, contenu_qr, dossier="tickets"):
    """
    billet : dict avec numero, categorie ('VIP'/'STANDARD'), nom, prenom, prix_usd
    Renvoie (chemin_png, chemin_pdf).
    """
    W, H = 1080, 2400
    vip = billet["categorie"].upper() == "VIP"
    accent = GOLD if vip else CLAY
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    M = 80  # marge

    # ---------- En-tête bleu nuit ----------
    d.rectangle([0, 0, W, 640], fill=NAVY)
    pal = [GOLD, CLAY, CREAM, SLATE]
    n = 12
    for i in range(n):
        cx = M + 18 + i * (W - 2 * M - 36) / (n - 1)
        _losange(d, cx, 80, 18, pal[i % 4])

    _espace(d, (M, 160), "FAHARI ", police(42, True), CREAM, 0.3)
    x = M + _largeur_espacee(d, "FAHARI ", police(42, True), 0.3) + 42 * 0.3
    x = _espace(d, (x, 160), "A", police(42, True), GOLD, 0.3)
    _espace(d, (x + 42 * 0.3, 160), "FRIKA", police(42, True), CREAM, 0.3)
    f = police(32, True)
    w = _largeur_espacee(d, "E-TICKET", f, 0.2)
    _espace(d, (W - M - w, 168), "E-TICKET", f, GOLD, 0.2)

    _espace(d, (M, 300), EVENEMENT["titre"], police(40, True), CLAY_CLAIR, 0.26)
    titre = "PASS VIP" if vip else "PASS STANDARD"
    taille = 118
    while d.textlength(titre, font=police(taille, True)) > W - 2 * M - 240 and taille > 40:
        taille -= 4
    d.text((M, 360 + (118 - taille) // 2), titre, font=police(taille, True), fill=CREAM)
    d.text((M, 520), "Tourisme · Gastronomie · Art africain", font=police(34), fill="#B9C3D6")

    if os.path.exists(LOGO):
        logo = Image.open(LOGO).convert("RGBA")
        logo.thumbnail((150, 180))
        pastille = Image.new("RGBA", (200, 220), (0, 0, 0, 0))
        ImageDraw.Draw(pastille).rounded_rectangle([0, 0, 199, 219], 28, fill=CREAM)
        pastille.alpha_composite(logo, ((200 - logo.width) // 2, (220 - logo.height) // 2))
        img.paste(pastille, (W - M - 200, 290), pastille)

    # ---------- Informations ----------
    col2 = W // 2 + 20
    larg_col = W // 2 - M - 40
    fl, fv, fs = police(28, True), police(48, True), police(38)

    def champ(x, y, libelle, valeur, couleur=NAVY, sous=None):
        _espace(d, (x, y), libelle, fl, SLATE, 0.2)
        yy = y + 48
        for ligne in _couper(d, valeur, fv, larg_col):
            d.text((x, yy), ligne, font=fv, fill=couleur)
            yy += 60
        if sous:
            d.text((x, yy + 2), sous, font=fs, fill=NAVY)
            yy += 50
        return yy

    y = 720
    champ(M, y, "DATE", EVENEMENT["date"])
    champ(col2, y, "HEURE", EVENEMENT["heure"])
    y = 900
    y1 = champ(M, y, "LIEU DE DÉPART", EVENEMENT["depart"])
    y2 = champ(col2, y, "LIEU D'ARRIVÉE", EVENEMENT["arrivee"], CLAY, EVENEMENT["arrivee_ville"])
    y = max(y1, y2) + 50

    d.line([M, y, W - M, y], fill=NAVY, width=3)
    y += 40
    _espace(d, (M, y), "NOM", fl, SLATE, 0.2)
    nom = f"{billet['nom']} {billet.get('prenom') or ''}".strip().upper()
    d.text((M, y + 48), nom, font=police(64, True), fill=NAVY)
    prix = f"{float(billet['prix_usd']):.0f} $"
    d.text((M, y + 130), f"{'Pass VIP' if vip else 'Pass Standard'} · {prix}", font=police(44, True), fill=CLAY)

    # ---------- Ligne de découpe ----------
    yd = y + 260
    for xx in range(40, W - 40, 36):
        d.line([xx, yd, xx + 18, yd], fill="#B5B9C2", width=5)

    # ---------- QR code ----------
    t = 560
    qx, qy = (W - t) // 2, yd + 60
    d.rounded_rectangle([qx - 30, qy - 30, qx + t + 30, qy + t + 30], 36, fill="white", outline=accent, width=10)
    img.paste(image_qr(contenu_qr, t), (qx, qy))

    fnum = police(54, True)
    wn = _largeur_espacee(d, f"N° {billet['numero']}", fnum, 0.1)
    _espace(d, ((W - wn) / 2, qy + t + 70), f"N° {billet['numero']}", fnum, NAVY, 0.1)
    for i, ligne in enumerate(["Montrez ce QR code à l'entrée · valable pour 1 personne",
                               f"Contact {EVENEMENT['contact']}"]):
        ff = police(32, i == 1)
        d.text(((W - d.textlength(ligne, font=ff)) / 2, qy + t + 160 + i * 50), ligne, font=ff,
               fill=SLATE if i == 0 else CLAY)

    img = img.crop((0, 0, W, min(H, qy + t + 290)))

    # ---------- Enregistrement ----------
    os.makedirs(dossier, exist_ok=True)
    base = os.path.join(dossier, f"Ticket_{billet['numero']}")
    img.save(base + ".png", optimize=True)
    img.save(base + ".pdf", "PDF", resolution=300)
    return base + ".png", base + ".pdf"


if __name__ == "__main__":  # test rapide sans base de données
    exemple = {"numero": "FA-2026-0001", "categorie": "VIP", "nom": "ADAM", "prenom": "", "prix_usd": 50}
    print(creer_ticket(exemple, "FAHARI-AFRIKA|LANCEMENT|VIP|28-11-2026|FA-2026-0001|TEST"))
