"""
loader.py
=========
Lecture robuste des nomenclatures Revit exportées en CSV.

Spécificités gérées :
  - BOM UTF-8 (caractère ﻿ en début de fichier)
  - Ligne 1 = titre Revit générique ("Nomenclature multicatégorie...")
  - Ligne 2 = en-têtes
  - Ligne 3 = ligne vide parasite
  - Détection automatique du séparateur (, ; ou tab)
  - Variations de colonnes selon export (avec/sans "Price")
"""
from __future__ import annotations

import io
import pandas as pd

# Colonnes qu'on s'attend à trouver. La présence de "Price" est optionnelle.
EXPECTED_COLUMNS = {
    "Type",
    "Niveau",
    "Famille",
    "Famille et type",
    "Identifiant",
}


def load_revit_nomenclature(file_obj_or_path) -> pd.DataFrame:
    """
    Charge un CSV Revit et renvoie un DataFrame propre.

    Args:
        file_obj_or_path: chemin str/Path OU objet file-like (uploader Streamlit).

    Returns:
        pd.DataFrame avec au minimum les colonnes Type, Niveau, Famille,
        "Famille et type", Identifiant. Les lignes vides sont supprimées.

    Raises:
        ValueError si la structure du fichier n'est pas reconnue.
    """
    # --- 1. Lecture brute en mémoire pour analyser la structure ---
    if hasattr(file_obj_or_path, "read"):
        raw_bytes = file_obj_or_path.read()
        # Reset le curseur pour permettre relecture éventuelle
        if hasattr(file_obj_or_path, "seek"):
            file_obj_or_path.seek(0)
    else:
        with open(file_obj_or_path, "rb") as f:
            raw_bytes = f.read()

    # Décodage en gérant le BOM UTF-8
    raw_text = raw_bytes.decode("utf-8-sig")

    # --- 2. Lecture avec pandas, en sautant la ligne 1 (titre Revit) ---
    # On utilise sep=None + engine='python' pour auto-détecter le séparateur.
    df = pd.read_csv(
        io.StringIO(raw_text),
        sep=None,
        engine="python",
        skiprows=1,           # saute "Nomenclature multicatégorie..."
        skip_blank_lines=False,  # on supprime nous-mêmes après
        dtype=str,
    )

    # --- 3. Nettoyage des lignes parasites ---
    # On enlève toutes les lignes où TOUTES les colonnes sont vides/NaN
    df = df.dropna(how="all").reset_index(drop=True)

    # On enlève aussi les lignes où "Famille" ET "Famille et type" sont vides
    # (lignes de séparation parfois insérées par Revit dans les exports)
    if "Famille" in df.columns and "Famille et type" in df.columns:
        mask_empty = (
            df["Famille"].isna() | (df["Famille"].astype(str).str.strip() == "")
        ) & (
            df["Famille et type"].isna()
            | (df["Famille et type"].astype(str).str.strip() == "")
        )
        df = df.loc[~mask_empty].reset_index(drop=True)

    # --- 4. Validation des colonnes attendues ---
    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"Colonnes manquantes dans le CSV Revit : {missing}. "
            f"Colonnes trouvées : {list(df.columns)}"
        )

    # --- 5. Normalisation : tout est string, NaN → chaîne vide ---
    for col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def get_dataset_summary(df: pd.DataFrame) -> dict:
    """Statistiques rapides utiles pour l'affichage utilisateur."""
    return {
        "n_elements": len(df),
        "n_familles": df["Famille"].nunique() if "Famille" in df.columns else 0,
        "n_types": df["Famille et type"].nunique() if "Famille et type" in df.columns else 0,
        "n_niveaux": df["Niveau"].replace("", pd.NA).dropna().nunique()
                     if "Niveau" in df.columns else 0,
        "has_price": "Price" in df.columns,
    }
