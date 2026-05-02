"""
admin_data.py
=============
Référentiels métier centralisés et ajustables par l'utilisateur.

Toutes les valeurs codées en dur dans ce module sont des HYPOTHÈSES PAR DÉFAUT
issues de la littérature scientifique (Akinade 2015, Densley Tingley 2012,
ADEME, FFB, CycleUp). Elles peuvent être modifiées en runtime via l'interface
admin de la sidebar Streamlit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# =============================================================================
# 1. TAXONOMIE DE CLASSIFICATION (mots-clés enrichis)
# =============================================================================
# Stratégie : le classifieur cherche, dans `Famille` ET `Famille et type`
# (concaténés et normalisés), des motifs caractéristiques de chaque trajectoire.
# L'ordre des règles compte : on évalue REEMPLOI > AUTRES_DECHETS > RECYCLAGE
# (un isolant en laine est déchet avant d'être "matériau béton recyclable").

CLASSIFICATION_KEYWORDS = {
    "Reemploi": [
        # Menuiseries et baies
        "porte", "pp ", "pp(", "fenetre", "vitre", "vitrage", "baie",
        "menuiserie", "huisserie", "int. simple", "int simple",
        "by_str_porte", "by_str_baie", "baielibre",
        # Façades légères et panneaux
        "mur-rideau", "mur rideau", "panneau systeme", "panneau systè",
        "rideau", "meneau", "bardage",
        # Bois lamellé-collé (poutres/poteaux démontables)
        "lamelle-colle", "lamellé-collé", "lamelle colle",
        # Sanitaires et équipements
        "receveur", "sanitaire", "lavabo", "wc", "vasque",
        "robinetterie", "douche", "evier",
        # Mobilier et finitions reemployables
        "mobilier", "banc", "table", "chaise", "armoire",
        # Composants bois structurels (déboulonnables)
        "structure bois", "poteau bois", "poutre bois", "charpente bois",
        # Escaliers métalliques BY_STR (souvent boulonnés/préfab acier)
        "escalier metallique", "escalier acier",
        "by_str_escalier",
        # Garde-corps métalliques (boulonnés)
        "garde-corps", "garde corps",
    ],
    "AutresDechets": [
        # Isolants polluants ou non séparables
        "isolant", "laine de verre", "laine de roche", "polystyrene",
        "pse", "pir", "pur", "polyurethane",
        # Cloisons platre (BA13 abimé après dépose)
        "ba13", "ba 13", "platre", "fermacell",
        # Membranes et étanchéités
        "etancheite", "membrane", "bitume", "epdm",
        # Composites non séparables
        "composite", "stratifie", "sandwich",
        # Plafonds suspendus dégradés
        "plafond", "faux-plafond", "faux plafond",
        # Mobilier spécifique non réemployable
        "escalade", "volume escalade",
        # Cloisons légères non réemployables (TRAA-Cloison...)
        "cloison100", "cloison70", "cloison-",
        # Isolants intégrés dans murs
        "_isolant", "ep14_isolant",
        # Vides et découpes Revit (ne sont pas des matériaux réels)
        "vide_pour_decoupe", "vide_decoupe", "vide existant",
        "decoupe_adaptatif", "_vide_",
    ],
    # Si rien ne matche les deux premières catégories, c'est du recyclage
    # par défaut (béton, brique, métal, parement maçonnerie...).
    # Cette catégorie agit comme "fourre-tout" pour les masses minérales.
}

# Familles structurelles maçonnées/béton qui sont TOUJOURS du recyclage matière
# (jamais réemployables tel quel à cause de leur dépose destructive).
RECYCLAGE_FAMILIES = [
    "mur de base",                   # Murs coulés/maçonnés en place
    "murs",                          # Murs génériques
    "sol",                           # Dalles béton
    "toit de base",                  # Toiture lourde
    "voilebai", "voileba",           # Voiles béton armé
    "by_str_voile",                  # Voiles structuraux Revit
    "by_str_dalle",
    "by_str_poutre",                 # Poutres préfab béton (BY_STR ≠ bois)
    "by_str_poteau",                 # Poteaux préfab béton
    "by_str_semelle",                # Semelles isolées (fondation)
    "escalier coule", "escalier coulé",  # Escalier béton coulé
    "volee monobloc", "volée monobloc", "palier monobloc",
    "rive faitage",                  # Tuiles/zinc de rive (recyclage matière)
]


# =============================================================================
# 2. TABLE D'HYPOTHÈSES BIM-DAS PAR FAMILLE
# =============================================================================
# Variables (cf. Akinade et al. 2015, et livrable ESTP) :
#   dc : ratio de connexions démontables = (Cb+Cd)/(Cb+Cd+Cn+Cf)
#        1.0 = entièrement boulonné/visse, 0.0 = soudé/coulé/collé
#   RP : ratio de préfabrication (part hors-site)
#        1.0 = préfab usine intégral, 0.0 = coulé en place
#   Rs : absence de finitions secondaires (1.0 = brut, 0.0 = peint/enduit lourd)
#   Rx : non-toxicité (1.0 = sain, 0.0 = amiante/PCB/plomb)
#   R1 : potentiel de réemploi (0.0–1.0)
#   R2 : potentiel de recyclage matière (0.0–1.0)
#
# Sources : Akinade 2015 (Tab.3), Densley Tingley 2012, base FDES INIES,
#           retours empiriques CycleUp / Mobius.

@dataclass
class FamilyHypothesis:
    """Hypothèses BIM-DAS pour une famille de composants Revit."""
    dc: float       # Ratio connexions démontables
    rp: float       # Ratio préfabrication
    rs: float       # Absence finitions secondaires
    rx: float       # Non-toxicité
    r1: float       # Potentiel réemploi
    r2: float       # Potentiel recyclage matière
    masse_unit_t: float  # Masse moyenne par élément Revit, en tonnes
    rationale: str  # Justification documentée

# Clé : motif normalisé recherché dans le champ "Famille" (lowercase)
DEFAULT_BIM_DAS_TABLE: dict[str, FamilyHypothesis] = {
    # --- Composants à fort potentiel de réemploi ---
    "mur-rideau": FamilyHypothesis(
        dc=0.90, rp=0.85, rs=1.00, rx=1.00, r1=0.85, r2=0.95,
        masse_unit_t=0.045,
        rationale="Préfab usine, fixations boulonnées, démontage soigné possible (CycleUp)."
    ),
    "panneau systeme": FamilyHypothesis(
        dc=0.85, rp=0.90, rs=1.00, rx=1.00, r1=0.80, r2=0.90,
        masse_unit_t=0.025,
        rationale="Panneaux modulaires clipsés, hautement réemployables."
    ),
    "meneau": FamilyHypothesis(
        dc=0.95, rp=1.00, rs=1.00, rx=1.00, r1=0.85, r2=0.95,
        masse_unit_t=0.008,
        rationale="Profilés aluminium boulonnés, démontables sans dégradation."
    ),
    "int. simple": FamilyHypothesis(
        dc=0.95, rp=0.80, rs=0.85, rx=1.00, r1=0.90, r2=0.40,
        masse_unit_t=0.020,
        rationale="Portes intérieures vissées, dépose simple (Mobius / Backacia)."
    ),
    "by_str_baielibre": FamilyHypothesis(
        dc=0.90, rp=0.95, rs=1.00, rx=1.00, r1=0.85, r2=0.90,
        masse_unit_t=0.030,
        rationale="Système de baie libre préfabriqué Revit, démontable."
    ),

    # --- Composants à fort recyclage matière, faible réemploi ---
    "mur de base": FamilyHypothesis(
        dc=0.10, rp=0.20, rs=0.70, rx=1.00, r1=0.05, r2=0.85,
        masse_unit_t=2.500,
        rationale="Murs maçonnés/coulés en place, dépose destructive, granulats recyclés."
    ),
    "sol": FamilyHypothesis(
        dc=0.10, rp=0.15, rs=0.60, rx=1.00, r1=0.05, r2=0.85,
        masse_unit_t=3.000,
        rationale="Dalle béton coulée en place, recyclage en granulats routiers."
    ),
    "voileba": FamilyHypothesis(
        dc=0.05, rp=0.10, rs=0.80, rx=1.00, r1=0.02, r2=0.90,
        masse_unit_t=4.500,
        rationale="Voile béton armé, monolithique, recyclage matière uniquement."
    ),
    "by_str_voile": FamilyHypothesis(
        dc=0.05, rp=0.10, rs=0.80, rx=1.00, r1=0.02, r2=0.90,
        masse_unit_t=4.500,
        rationale="Voile structurel BA, recyclage matière uniquement."
    ),

    # --- Composants déchets/peu valorisables ---
    "isolant": FamilyHypothesis(
        dc=0.30, rp=0.40, rs=0.50, rx=0.80, r1=0.10, r2=0.30,
        masse_unit_t=0.015,
        rationale="Laines minérales souvent dégradées à la dépose, filière REP partielle."
    ),
    "cloison": FamilyHypothesis(
        dc=0.40, rp=0.30, rs=0.40, rx=0.90, r1=0.10, r2=0.40,
        masse_unit_t=0.080,
        rationale="Cloisons plâtre/BA13 cassantes, recyclage Placo limité aux gisements propres."
    ),
    "plafond": FamilyHypothesis(
        dc=0.50, rp=0.60, rs=0.30, rx=0.90, r1=0.20, r2=0.40,
        masse_unit_t=0.010,
        rationale="Faux-plafonds dalles minérales, réemploi rare (qualité dégradée)."
    ),
    "volume escalade": FamilyHypothesis(
        dc=0.60, rp=0.70, rs=0.50, rx=1.00, r1=0.30, r2=0.40,
        masse_unit_t=0.150,
        rationale="Mobilier sportif spécifique, réemploi possible mais marché restreint."
    ),

    # --- Familles supplémentaires détectées dans les CSV réels ---
    "lamelle-colle": FamilyHypothesis(
        dc=0.85, rp=0.95, rs=0.95, rx=1.00, r1=0.80, r2=0.70,
        masse_unit_t=0.180,
        rationale="Bois lamellé-collé préfab usine, assemblages boulonnés, fort réemploi."
    ),
    "by_str_porte": FamilyHypothesis(
        dc=0.95, rp=0.85, rs=0.90, rx=1.00, r1=0.90, r2=0.40,
        masse_unit_t=0.040,
        rationale="Porte BIM préfab vissée, réemploi direct possible."
    ),
    "by_str_poutre": FamilyHypothesis(
        dc=0.50, rp=0.95, rs=0.85, rx=1.00, r1=0.30, r2=0.85,
        masse_unit_t=1.200,
        rationale="Poutre béton préfab, dépose possible mais réemploi limité (sur mesure)."
    ),
    "by_str_poteau": FamilyHypothesis(
        dc=0.50, rp=0.95, rs=0.85, rx=1.00, r1=0.30, r2=0.85,
        masse_unit_t=0.900,
        rationale="Poteau béton préfab, idem poutre."
    ),
    "by_str_semelle": FamilyHypothesis(
        dc=0.05, rp=0.20, rs=0.80, rx=1.00, r1=0.02, r2=0.85,
        masse_unit_t=2.800,
        rationale="Semelle isolée béton fondation, recyclage matière uniquement."
    ),
    "by_str_escalier": FamilyHypothesis(
        dc=0.85, rp=0.90, rs=0.90, rx=1.00, r1=0.80, r2=0.70,
        masse_unit_t=0.350,
        rationale="Escalier préfab acier/bois ancré, démontable et réemployable."
    ),
    "toit de base": FamilyHypothesis(
        dc=0.30, rp=0.50, rs=0.60, rx=0.95, r1=0.20, r2=0.70,
        masse_unit_t=0.800,
        rationale="Toiture composite, dépose partiellement destructive, recyclage matière."
    ),
    "escalier coule": FamilyHypothesis(
        dc=0.05, rp=0.10, rs=0.70, rx=1.00, r1=0.02, r2=0.85,
        masse_unit_t=2.500,
        rationale="Escalier béton coulé en place, recyclage matière uniquement."
    ),
    "monobloc": FamilyHypothesis(
        dc=0.10, rp=0.80, rs=0.70, rx=1.00, r1=0.10, r2=0.85,
        masse_unit_t=1.800,
        rationale="Volée/palier monobloc préfab béton, dépose possible mais réemploi limité."
    ),
    "rive faitage": FamilyHypothesis(
        dc=0.40, rp=0.90, rs=0.80, rx=1.00, r1=0.15, r2=0.75,
        masse_unit_t=0.012,
        rationale="Pièces de rive zinc/tuile, recyclage matière facile."
    ),
    "garde-corps": FamilyHypothesis(
        dc=0.85, rp=0.90, rs=0.85, rx=1.00, r1=0.75, r2=0.85,
        masse_unit_t=0.025,
        rationale="Garde-corps métallique boulonné, démontable et réemployable."
    ),
    "vide": FamilyHypothesis(
        dc=0.00, rp=0.00, rs=0.00, rx=1.00, r1=0.00, r2=0.00,
        masse_unit_t=0.000,
        rationale="Élément Revit virtuel (découpe, vide), pas de matière réelle."
    ),
}

# Hypothèse par défaut quand aucune famille ne matche
GENERIC_HYPOTHESIS = FamilyHypothesis(
    dc=0.40, rp=0.30, rs=0.60, rx=0.95, r1=0.30, r2=0.50,
    masse_unit_t=0.500,
    rationale="Famille non répertoriée — valeurs moyennes prudentes."
)


# =============================================================================
# 3. RATIOS GLOBAUX (ADEME / études scientifiques)
# =============================================================================
# Tous ajustables dans la sidebar.

@dataclass
class GlobalRatios:
    """Ratios par mètre carré et gains de l'optimisation circulaire."""
    # Valeurs de référence par m² (avant optimisation = scénario standard)
    carbone_kgco2_m2: float = 750.0       # ADEME, neuf hors usage
    dechets_kg_m2: float = 50.0           # ADEME, déchets de chantier
    cout_demolition_eur_m2: float = 800.0  # FFB, coût démolition standard
    cout_depose_soignee_eur_m2: float = 350.0  # FFB / CycleUp, dépose tri
    duree_chantier_jours_m2: float = 0.025  # ~6 mois pour 7400 m²

    # Gains liés à la stratégie circulaire (réductions en %)
    gain_carbone_pct: float = 10.0   # Journal of Cleaner Production
    gain_dechets_pct: float = 20.0   # WRAP UK
    gain_temps_pct: float = 15.0     # CIFE Stanford
    # Gain coût : intrinsèque (différentiel démolition vs dépose soignée + revente)


# =============================================================================
# 4. BASE DE PRIX INTERNE
# =============================================================================
# Fourchettes [min, médian, max] documentées avec source.
# Toutes les valeurs sont des ESTIMATIONS INDICATIVES et doivent être
# explicitement signalées comme telles à l'utilisateur.

@dataclass
class PriceRange:
    """Fourchette de prix par unité (élément ou tonne)."""
    min: float
    med: float
    max: float
    unit: Literal["unite", "tonne", "m2"]
    source: str

# --- 4.1 Achat de réemploi (€/élément) ---
# Comparaison de fournisseurs : on cherche à acheter du réemploi pour
# combler les besoins du projet non couverts par le gisement existant.
PRIX_ACHAT_REEMPLOI: dict[str, dict[str, PriceRange]] = {
    "porte": {
        "CycleUp":   PriceRange(120, 180, 280, "unite", "CycleUp 2024 (porte intérieure standard)"),
        "Mobius":    PriceRange(150, 220, 350, "unite", "Mobius Réemploi (avec certif technique AQC)"),
        "Mineka":    PriceRange( 80, 130, 200, "unite", "Mineka / réseau associatif local"),
    },
    "fenetre": {
        "CycleUp":   PriceRange(180, 280, 450, "unite", "CycleUp 2024"),
        "Mobius":    PriceRange(220, 340, 520, "unite", "Mobius Réemploi"),
        "Mineka":    PriceRange(120, 200, 320, "unite", "Mineka / réseau local"),
    },
    "mur-rideau": {  # facturé au m² mais on garde l'unité pour cohérence Revit
        "CycleUp":   PriceRange(380, 480, 620, "unite", "CycleUp panneau mur-rideau"),
        "Mobius":    PriceRange(420, 540, 700, "unite", "Mobius (dépose certifiée)"),
        "Mineka":    PriceRange(280, 380, 500, "unite", "Mineka"),
    },
    "panneau systeme": {
        "CycleUp":   PriceRange(180, 240, 320, "unite", "CycleUp panneau modulaire"),
        "Mobius":    PriceRange(200, 270, 360, "unite", "Mobius"),
        "Mineka":    PriceRange(120, 180, 250, "unite", "Mineka"),
    },
    "meneau": {
        "CycleUp":   PriceRange( 25,  40,  65, "unite", "CycleUp profilé alu"),
        "Mobius":    PriceRange( 30,  50,  80, "unite", "Mobius"),
        "Mineka":    PriceRange( 18,  30,  50, "unite", "Mineka"),
    },
    "int. simple": {
        "CycleUp":   PriceRange(110, 160, 240, "unite", "CycleUp porte intérieure simple"),
        "Mobius":    PriceRange(130, 200, 300, "unite", "Mobius"),
        "Mineka":    PriceRange( 70, 120, 180, "unite", "Mineka"),
    },
    # Fallback pour familles non listées : prix moyens "élément réemploi"
    "_default": {
        "CycleUp":   PriceRange( 80, 150, 280, "unite", "CycleUp moyenne tous produits"),
        "Mobius":    PriceRange(100, 180, 320, "unite", "Mobius moyenne"),
        "Mineka":    PriceRange( 50, 100, 200, "unite", "Mineka moyenne"),
    },
}

# --- 4.2 Revente vers d'autres chantiers (€/élément, recettes) ---
# Quand on a du surplus de réemploi sur l'existant qui ne sert pas au projet,
# on peut le vendre. Les marges des plateformes sont déduites.
PRIX_REVENTE_REEMPLOI: dict[str, dict[str, PriceRange]] = {
    "porte": {
        "Backacia":      PriceRange(50, 90, 140, "unite", "Backacia (commission ~20%)"),
        "CycleUp Marketplace": PriceRange(40, 80, 130, "unite", "CycleUp Marketplace"),
    },
    "fenetre": {
        "Backacia":      PriceRange(80, 140, 230, "unite", "Backacia"),
        "CycleUp Marketplace": PriceRange(70, 130, 220, "unite", "CycleUp Marketplace"),
    },
    "mur-rideau": {
        "Backacia":      PriceRange(180, 260, 360, "unite", "Backacia"),
        "CycleUp Marketplace": PriceRange(160, 240, 340, "unite", "CycleUp Marketplace"),
    },
    "panneau systeme": {
        "Backacia":      PriceRange(80, 130, 200, "unite", "Backacia"),
        "CycleUp Marketplace": PriceRange(70, 120, 180, "unite", "CycleUp Marketplace"),
    },
    "meneau": {
        "Backacia":      PriceRange(10, 18,  30, "unite", "Backacia"),
        "CycleUp Marketplace": PriceRange( 8, 15,  25, "unite", "CycleUp Marketplace"),
    },
    "int. simple": {
        "Backacia":      PriceRange(45, 80, 130, "unite", "Backacia"),
        "CycleUp Marketplace": PriceRange(40, 75, 120, "unite", "CycleUp Marketplace"),
    },
    "_default": {
        "Backacia":      PriceRange(30, 70, 130, "unite", "Backacia moyenne"),
        "CycleUp Marketplace": PriceRange(25, 60, 120, "unite", "CycleUp Marketplace moyenne"),
    },
}

# --- 4.3 Recyclage matière (€/tonne, coût négatif = recette) ---
# Filières REP gratuites pour gisements triés à la source.
PRIX_RECYCLAGE: dict[str, dict[str, PriceRange]] = {
    "beton": {
        "Valobat":   PriceRange(  0,   0,  15, "tonne", "Valobat REP, gratuit si tri à la source"),
        "Paprec":    PriceRange( 25,  45,  80, "tonne", "Paprec Chantiers (mixte)"),
        "Ecomaison": PriceRange(  5,  15,  30, "tonne", "Ecomaison (granulats recyclés)"),
    },
    "brique": {
        "Valobat":   PriceRange(  0,  10,  25, "tonne", "Valobat REP"),
        "Paprec":    PriceRange( 30,  55,  90, "tonne", "Paprec Chantiers"),
        "Ecomaison": PriceRange( 10,  25,  45, "tonne", "Ecomaison"),
    },
    "metal": {
        # Recettes : on est PAYÉ pour donner du métal recyclable
        "Valobat":   PriceRange(-180, -120, -60, "tonne", "Valobat (recette ferraille mixte)"),
        "Paprec":    PriceRange(-200, -140, -80, "tonne", "Paprec (recette acier propre)"),
        "Ecomaison": PriceRange(-150, -100, -50, "tonne", "Ecomaison"),
    },
    "bois": {
        "Valobat":   PriceRange( 20,  40,  70, "tonne", "Valobat"),
        "Paprec":    PriceRange( 35,  60,  95, "tonne", "Paprec"),
        "Ecomaison": PriceRange( 15,  35,  60, "tonne", "Ecomaison (filière bois reconstitué)"),
    },
    "platre": {
        "Placo Recycling": PriceRange( 30, 60, 100, "tonne",
                                        "Placo Recycling (gisement propre uniquement)"),
        "Paprec":          PriceRange( 80, 120, 180, "tonne",
                                        "Paprec (mélangé, plus cher)"),
    },
    "_default": {
        "Valobat":   PriceRange( 20,  50, 100, "tonne", "Valobat moyenne tous flux"),
        "Paprec":    PriceRange( 50, 100, 180, "tonne", "Paprec moyenne"),
        "Ecomaison": PriceRange( 25,  60, 120, "tonne", "Ecomaison moyenne"),
    },
}

# --- 4.4 Déchets ultimes (€/tonne, coût toujours positif) ---
PRIX_DECHETS_ULTIMES: dict[str, PriceRange] = {
    "Tri'n'Collect": PriceRange(120, 180, 250, "tonne",
                                "Tri à la source Lean, réduit drastiquement DIB"),
    "Veolia":        PriceRange(180, 250, 350, "tonne",
                                "Centre de tri massif"),
    "Suez":          PriceRange(170, 240, 340, "tonne",
                                "Centre de tri massif"),
}


# =============================================================================
# 5. TAXONOMIE DES MATÉRIAUX (pour le routage vers les filières recyclage)
# =============================================================================
# Pour un élément classé "Recyclage" : à quel matériau de filière l'orienter ?

MATERIAL_FROM_KEYWORDS = {
    "beton":   ["beton", "voileba", "voile_ba", "by_str_voile", "dalle"],
    "brique":  ["brique", "parement"],
    "metal":   ["acier", "metal", "aluminium", "alu", "ferraille"],
    "bois":    ["bois", "ossature_bois", "charpente_bois"],
    "platre":  ["platre", "ba13", "ba 13", "fermacell", "cloison100", "cloison70"],
}

def detect_material(famille: str, type_str: str) -> str:
    """Renvoie la clé matière (beton/brique/metal/bois/platre) ou '_default'."""
    text = (famille + " " + type_str).lower()
    for material, keywords in MATERIAL_FROM_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return material
    return "_default"


# =============================================================================
# 6. PALETTES DE COULEURS (cohérentes avec le fichier Excel de référence)
# =============================================================================

PALETTES = {
    "Reemploi": {
        "primary":   "1B5E20",  # vert foncé
        "secondary": "388E3C",  # vert moyen
        "soft":      "C8E6C9",  # vert clair
        "icon":      "♻",
        "label":     "RÉEMPLOI",
        "subtitle":  "Éléments réutilisables en l'état",
    },
    "Recyclage": {
        "primary":   "0D47A1",  # bleu foncé
        "secondary": "1565C0",  # bleu moyen
        "soft":      "BBDEFB",  # bleu clair
        "icon":      "🔄",
        "label":     "RECYCLAGE",
        "subtitle":  "Éléments valorisables par recyclage matière",
    },
    "AutresDechets": {
        "primary":   "B71C1C",  # rouge foncé
        "secondary": "C62828",  # rouge moyen
        "soft":      "FFCDD2",  # rouge clair
        "icon":      "🗑",
        "label":     "AUTRES DÉCHETS",
        "subtitle":  "Éléments à éliminer en déchèterie",
    },
    "Synthese": {
        "primary":   "37474F",  # gris bleuté foncé
        "secondary": "455A64",  # gris bleuté moyen
        "soft":      "ECEFF1",  # gris bleuté clair
    },
}
