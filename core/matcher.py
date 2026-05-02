"""
matcher.py
==========
Matching in situ entre le gisement existant et les besoins du projet.

Stratégie :
  1. On ne considère que les éléments classés 'Reemploi' des deux côtés
     (les autres catégories ne peuvent pas être remontées telles quelles).
  2. Pour chaque type de composant requis par le projet, on cherche une
     correspondance EXACTE dans le gisement existant après normalisation
     du texte (insensible à la casse, aux espaces, accents).
  3. Le nombre d'éléments réemployables in situ est : min(besoin, dispo).
  4. Le solde du besoin est à acheter en réemploi externe.
  5. Le solde du gisement (offre > demande) est à revendre vers d'autres
     chantiers — c'est l'input du devis 'revente'.

Cette logique est volontairement simple et déterministe : elle sert de
SOCLE quantitatif, sur lequel le suggester créatif (4.2) viendra ajouter
des recommandations qualitatives.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .classifier import _normalize


@dataclass
class MatchingResult:
    """Résultat du matching in situ."""
    df_matching: pd.DataFrame   # 1 ligne par type Revit du projet
    df_surplus: pd.DataFrame    # éléments existants en surplus (à revendre)
    n_reemployes_in_situ: int   # total d'éléments réemployés sur place
    n_a_acheter_externe: int    # total d'éléments à commander en réemploi externe
    n_surplus_revente: int      # total d'éléments existants à revendre


def match_onsite(
    df_existant_classifie: pd.DataFrame,
    df_projet_classifie: pd.DataFrame,
) -> MatchingResult:
    """Calcule le matching exact entre offre (existant) et demande (projet).

    Args:
        df_existant_classifie: existant avec colonne 'Categorie'
        df_projet_classifie: projet avec colonne 'Categorie'

    Returns:
        MatchingResult avec les détails ligne à ligne et les agrégats.
    """
    # --- 1. On filtre les Reemploi des deux côtés ---
    offre = df_existant_classifie.loc[
        df_existant_classifie["Categorie"] == "Reemploi"
    ].copy()
    demande = df_projet_classifie.loc[
        df_projet_classifie["Categorie"] == "Reemploi"
    ].copy()

    # --- 2. Clé de matching normalisée ---
    offre["_key"] = offre["Famille et type"].apply(_normalize)
    demande["_key"] = demande["Famille et type"].apply(_normalize)

    # --- 3. Groupage par type ---
    offre_counts = (
        offre.groupby(["_key", "Famille", "Famille et type"])
        .size().reset_index(name="Disponibles")
    )
    demande_counts = (
        demande.groupby(["_key", "Famille", "Famille et type"])
        .size().reset_index(name="Besoin_Projet")
    )

    # --- 4. Fusion sur la clé normalisée (left = projet, on conserve toute la demande) ---
    matching = pd.merge(
        demande_counts,
        offre_counts[["_key", "Disponibles"]],
        on="_key",
        how="left",
    )
    matching["Disponibles"] = matching["Disponibles"].fillna(0).astype(int)

    matching["Reemployes_sur_place"] = matching.apply(
        lambda r: int(min(r["Besoin_Projet"], r["Disponibles"])), axis=1
    )
    matching["A_commander_externe"] = (
        matching["Besoin_Projet"] - matching["Reemployes_sur_place"]
    ).astype(int)

    # On garde les colonnes utiles dans un ordre lisible
    matching_out = matching[[
        "Famille", "Famille et type",
        "Besoin_Projet", "Disponibles",
        "Reemployes_sur_place", "A_commander_externe",
    ]].sort_values(
        by=["Reemployes_sur_place", "Besoin_Projet"],
        ascending=[False, False],
    ).reset_index(drop=True)

    # --- 5. Surplus de l'existant (à revendre) ---
    # Pour chaque type existant, dispo - utilisé in situ = surplus
    surplus_rows = []
    used_per_key = matching.set_index("_key")["Reemployes_sur_place"].to_dict()
    for _, row in offre_counts.iterrows():
        used = used_per_key.get(row["_key"], 0)
        surplus = int(row["Disponibles"] - used)
        if surplus > 0:
            surplus_rows.append({
                "Famille": row["Famille"],
                "Famille et type": row["Famille et type"],
                "Surplus_a_revendre": surplus,
            })
    df_surplus = pd.DataFrame(surplus_rows).sort_values(
        by="Surplus_a_revendre", ascending=False
    ).reset_index(drop=True) if surplus_rows else pd.DataFrame(
        columns=["Famille", "Famille et type", "Surplus_a_revendre"]
    )

    # --- 6. Agrégats ---
    n_reemployes_in_situ = int(matching_out["Reemployes_sur_place"].sum())
    n_a_acheter_externe = int(matching_out["A_commander_externe"].sum())
    n_surplus_revente = int(df_surplus["Surplus_a_revendre"].sum()) if len(df_surplus) else 0

    return MatchingResult(
        df_matching=matching_out,
        df_surplus=df_surplus,
        n_reemployes_in_situ=n_reemployes_in_situ,
        n_a_acheter_externe=n_a_acheter_externe,
        n_surplus_revente=n_surplus_revente,
    )
