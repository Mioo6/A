"""
classifier.py
=============
Classifieur expert hiérarchisé pour la trajectoire de fin de vie d'un
composant Revit (Réemploi / Recyclage / Autres déchets).

Algorithme :
  Étape A (priorité haute) : élément virtuel Revit → ignoré (catégorie 'Exclu')
  Étape B : indices forts de Réemploi dans Famille ou Type
  Étape C : indices d'Autres déchets (isolants, plâtre, composites)
  Étape D : famille forcée en Recyclage (béton coulé, voiles, semelles)
  Étape E : fallback → Recyclage (matières minérales par défaut)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from .admin_data import (
    CLASSIFICATION_KEYWORDS,
    RECYCLAGE_FAMILIES,
)

# Catégories possibles
CATEGORIES = ["Reemploi", "Recyclage", "AutresDechets", "Exclu"]


def _normalize(text: str) -> str:
    """Normalise une chaîne pour la recherche de motifs.

    - lowercase
    - décompose les accents (é → e)
    - écrase les espaces multiples
    """
    text = (text or "").lower()
    # Suppression des accents
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Espaces multiples
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_row(famille: str, famille_et_type: str, type_str: str = "") -> str:
    """Classifie un seul élément Revit selon les règles hiérarchisées.

    Args:
        famille: champ "Famille" du CSV Revit.
        famille_et_type: champ "Famille et type" du CSV.
        type_str: champ "Type" optionnel.

    Returns:
        Une des valeurs de CATEGORIES.
    """
    fam_norm = _normalize(famille)
    full_norm = _normalize(f"{famille} {famille_et_type} {type_str}")

    # --- Étape A : éléments virtuels Revit (vides, découpes) ---
    virtual_markers = ["vide ", "vide_", "_vide_", "decoupe_adaptatif",
                       "vide_pour_decoupe", "vide existant"]
    if any(m in full_norm for m in virtual_markers):
        return "Exclu"

    # --- Étape B : indices forts de Réemploi ---
    # On cherche un motif EXACT de mot-clé Réemploi dans le texte normalisé
    for kw in CLASSIFICATION_KEYWORDS["Reemploi"]:
        if _normalize(kw) in full_norm:
            return "Reemploi"

    # --- Étape C : indices d'Autres déchets ---
    for kw in CLASSIFICATION_KEYWORDS["AutresDechets"]:
        if _normalize(kw) in full_norm:
            return "AutresDechets"

    # --- Étape D : famille forcée en Recyclage ---
    for forced_fam in RECYCLAGE_FAMILIES:
        if _normalize(forced_fam) in fam_norm:
            return "Recyclage"

    # --- Étape E : fallback ---
    return "Recyclage"


def classify_dataframe(df: pd.DataFrame, drop_excluded: bool = True) -> pd.DataFrame:
    """Applique la classification à tout un DataFrame.

    Args:
        df: DataFrame issu de `loader.load_revit_nomenclature`.
        drop_excluded: si True, retire les lignes classées 'Exclu'
                       (vides Revit) du résultat.

    Returns:
        Une copie du DataFrame avec une nouvelle colonne `Categorie` ∈
        {Reemploi, Recyclage, AutresDechets [, Exclu]}.
    """
    df = df.copy()
    df["Categorie"] = df.apply(
        lambda row: classify_row(
            row.get("Famille", ""),
            row.get("Famille et type", ""),
            row.get("Type", ""),
        ),
        axis=1,
    )
    if drop_excluded:
        df = df.loc[df["Categorie"] != "Exclu"].reset_index(drop=True)
    return df


# =============================================================================
# Diagnostic et synthèse
# =============================================================================

@dataclass
class ClassificationSummary:
    """Synthèse statistique d'une classification."""
    total: int
    n_reemploi: int
    n_recyclage: int
    n_dechets: int
    n_exclus: int = 0

    @property
    def pct_reemploi(self) -> float:
        return 100 * self.n_reemploi / self.total if self.total else 0.0

    @property
    def pct_recyclage(self) -> float:
        return 100 * self.n_recyclage / self.total if self.total else 0.0

    @property
    def pct_dechets(self) -> float:
        return 100 * self.n_dechets / self.total if self.total else 0.0


def summarize_classification(df_classified: pd.DataFrame) -> ClassificationSummary:
    """Compte les éléments par catégorie."""
    counts = df_classified["Categorie"].value_counts().to_dict()
    return ClassificationSummary(
        total=len(df_classified),
        n_reemploi=counts.get("Reemploi", 0),
        n_recyclage=counts.get("Recyclage", 0),
        n_dechets=counts.get("AutresDechets", 0),
        n_exclus=counts.get("Exclu", 0),
    )


def get_unclassified_diagnostic(df: pd.DataFrame) -> pd.DataFrame:
    """Pour debug : renvoie les familles tombées dans le fallback recyclage
    sans correspondance explicite dans aucune liste, pour aider à enrichir
    la taxonomie."""
    fams = df[df["Categorie"] == "Recyclage"]["Famille"].unique()
    diag = []
    for fam in fams:
        fam_norm = _normalize(fam)
        explicit = any(_normalize(f) in fam_norm for f in RECYCLAGE_FAMILIES)
        if not explicit:
            diag.append({"Famille": fam, "Statut": "Fallback (à examiner)"})
        else:
            diag.append({"Famille": fam, "Statut": "Forcé recyclage"})
    return pd.DataFrame(diag)
