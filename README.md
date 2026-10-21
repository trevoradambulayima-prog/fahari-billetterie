# Billetterie Fahari Afrika — Lancement

Application de bureau (Python + Tkinter + MySQL) pour la soirée de lancement
Fahari Afrika du **28 novembre 2026** (départ 6h30, Rawban 7e rue Limete → Cosmos Beach, Kinshasa).

## Fonctions
- Enregistrement des acheteurs, numéro de billet automatique
  (`FA-2026-0001`… VIP 50 $, `FA-2026-S0001`… Standard 25 $)
- Ticket PNG + PDF avec QR code anti-fraude
- Impression et envoi sur WhatsApp
- Liste des acheteurs : modifier, supprimer, annuler, export CSV
- Contrôle à l'entrée par scan du QR code

## Installation (Windows + XAMPP)
1. Démarrer MySQL dans XAMPP.
2. `INSTALLER.bat` (installe les paquets Python de `requirements.txt`).
3. `LANCER.bat` → saisir la connexion MySQL (localhost / 3306 / root).
   La base `fahari_billetterie` et ses tables sont créées automatiquement.

Voir `LISEZ-MOI.txt` pour le détail.

## Fichiers
| Fichier | Rôle |
|---|---|
| `billetterie.py` | Application (interface + base de données) |
| `ticket_image.py` | Génération du ticket PNG/PDF |
| `base_billetterie.sql` | Script SQL équivalent (optionnel) |
| `logo_fahari.png` | Logo |
| `CREER_EXE.bat` | Construit `Billetterie.exe` avec PyInstaller |

`config.ini` (mot de passe MySQL) et le dossier `tickets/` ne sont pas publiés.
