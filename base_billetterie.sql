-- =====================================================================
--  Fahari Afrika — Billetterie « Lancement » (28 novembre 2026)
--  Base de données MySQL (8.0+ / MariaDB 10.5+)
--  Exécution :  mysql -u root -p < base_billetterie.sql
-- =====================================================================

CREATE DATABASE IF NOT EXISTS fahari_billetterie
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE fahari_billetterie;

-- ---------------------------------------------------------------------
-- 1. Catégories de billets (prix + préfixe du numéro)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    code          VARCHAR(20)   PRIMARY KEY,          -- 'VIP', 'STANDARD'
    libelle       VARCHAR(50)   NOT NULL,
    prix_usd      DECIMAL(8,2)  NOT NULL,
    prefixe       VARCHAR(20)   NOT NULL,              -- 'FA-2026-' / 'FA-2026-S'
    dernier_num   INT UNSIGNED  NOT NULL DEFAULT 0,    -- compteur pour la numérotation automatique
    places_max    INT UNSIGNED  NULL                   -- NULL = illimité
) ENGINE=InnoDB;

INSERT INTO categories (code, libelle, prix_usd, prefixe, places_max) VALUES
    ('VIP',      'Pass VIP',      50.00, 'FA-2026-',  NULL),
    ('STANDARD', 'Pass Standard', 25.00, 'FA-2026-S', NULL)
ON DUPLICATE KEY UPDATE libelle = VALUES(libelle), prix_usd = VALUES(prix_usd);

-- ---------------------------------------------------------------------
-- 2. Acheteurs / billets vendus
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS billets (
    id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    numero         VARCHAR(30)   NOT NULL UNIQUE,      -- ex. FA-2026-0001, FA-2026-S0001
    categorie      VARCHAR(20)   NOT NULL,
    nom            VARCHAR(80)   NOT NULL,
    prenom         VARCHAR(80)   NULL,
    telephone      VARCHAR(30)   NOT NULL,
    email          VARCHAR(120)  NULL,
    prix_usd       DECIMAL(8,2)  NOT NULL,
    mode_paiement  ENUM('Cash','Mobile Money','Carte','Virement') NOT NULL DEFAULT 'Cash',
    code_secret    CHAR(16)      NOT NULL UNIQUE,      -- inclus dans le QR : empêche les faux billets
    statut         ENUM('VALIDE','UTILISE','ANNULE') NOT NULL DEFAULT 'VALIDE',
    date_achat     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_entree    DATETIME      NULL,                 -- rempli au scan à l'entrée
    CONSTRAINT fk_billet_categorie FOREIGN KEY (categorie) REFERENCES categories(code),
    INDEX idx_nom (nom),
    INDEX idx_tel (telephone)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. Procédure : vendre un billet (numéro généré automatiquement)
--    Le verrou FOR UPDATE garantit deux numéros différents même si
--    deux guichets vendent en même temps.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS vendre_billet;
DELIMITER $$
CREATE PROCEDURE vendre_billet(
    IN  p_categorie VARCHAR(20),
    IN  p_nom       VARCHAR(80),
    IN  p_prenom    VARCHAR(80),
    IN  p_telephone VARCHAR(30),
    IN  p_email     VARCHAR(120),
    IN  p_paiement  VARCHAR(20),
    IN  p_secret    CHAR(16),
    OUT p_numero    VARCHAR(30)
)
BEGIN
    DECLARE v_num    INT UNSIGNED;
    DECLARE v_prefix VARCHAR(20);
    DECLARE v_prix   DECIMAL(8,2);
    DECLARE v_max    INT UNSIGNED;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT dernier_num + 1, prefixe, prix_usd, places_max
      INTO v_num, v_prefix, v_prix, v_max
      FROM categories
     WHERE code = p_categorie
     FOR UPDATE;

    IF v_prefix IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Catégorie inconnue';
    END IF;

    IF v_max IS NOT NULL AND v_num > v_max THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Plus de places disponibles dans cette catégorie';
    END IF;

    SET p_numero = CONCAT(v_prefix, LPAD(v_num, 4, '0'));

    UPDATE categories SET dernier_num = v_num WHERE code = p_categorie;

    INSERT INTO billets (numero, categorie, nom, prenom, telephone, email,
                         prix_usd, mode_paiement, code_secret)
    VALUES (p_numero, p_categorie, p_nom, p_prenom, p_telephone, NULLIF(p_email, ''),
            v_prix, p_paiement, p_secret);

    COMMIT;
END$$
DELIMITER ;

-- ---------------------------------------------------------------------
-- 4. Vue : bilan des ventes par catégorie
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW bilan_ventes AS
SELECT  c.libelle                                   AS categorie,
        COUNT(b.id)                                 AS billets_vendus,
        COALESCE(SUM(b.prix_usd), 0)                AS total_usd,
        SUM(b.statut = 'UTILISE')                   AS entrees_validees
FROM categories c
LEFT JOIN billets b ON b.categorie = c.code AND b.statut <> 'ANNULE'
GROUP BY c.code, c.libelle;

-- ---------------------------------------------------------------------
-- 5. (Recommandé) Utilisateur dédié à l'application
--    Remplacez le mot de passe avant d'exécuter.
-- ---------------------------------------------------------------------
-- CREATE USER IF NOT EXISTS 'billetterie'@'localhost' IDENTIFIED BY 'ChangezMoi!2026';
-- GRANT SELECT, INSERT, UPDATE, EXECUTE ON fahari_billetterie.* TO 'billetterie'@'localhost';
-- FLUSH PRIVILEGES;

-- ---------------------------------------------------------------------
-- 6. Aligner le prix des billets déjà vendus sur le prix de leur catégorie
--    (ex. Standard passé de 30 $ à 25 $)
-- ---------------------------------------------------------------------
UPDATE billets b JOIN categories c ON b.categorie = c.code
   SET b.prix_usd = c.prix_usd
 WHERE b.prix_usd <> c.prix_usd;
