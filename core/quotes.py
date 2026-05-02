"""
quotes.py
=========
Génération des 4 devis comparatifs sur les soldes après matching in situ.

Les 4 devis :
  1. ACHAT RÉEMPLOI EXTERNE  — composants du projet non couverts par le
                                gisement (à acheter chez CycleUp/Mobius/Mineka)
  2. REVENTE DU SURPLUS       — éléments en surplus du gisement à revendre
                                (Backacia / CycleUp Marketplace)
  3. RECYCLAGE MATIÈRE        — éléments classés Recyclage de l'existant,
                                par filière matière (béton/brique/métal/bois/plâtre)
                                via Valobat / Paprec / Ecomaison / Placo Recycling
  4. DÉCHETS ULTIMES          — Tri'n'Collect / Veolia / Suez

IMPORTANT : tous les prix sont des ESTIMATIONS INDICATIVES, fourchettes
issues de barèmes publics (ADEME, FFB, CycleUp 2024, prix spot Valobat /
Paprec). À recouper systématiquement avec un devis réel avant engagement.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .admin_data import (
    PRIX_ACHAT_REEMPLOI,
    PRIX_REVENTE_REEMPLOI,
    PRIX_RECYCLAGE,
    PRIX_DECHETS_ULTIMES,
    detect_material,
    DEFAULT_BIM_DAS_TABLE,
    GENERIC_HYPOTHESIS,
)
from .bim_das import _lookup_hypothesis
from .classifier import _normalize


# =============================================================================
# Helpers
# =============================================================================

def _lookup_price_table(famille: str, table: dict) -> dict:
    """Trouve l'entrée de la table de prix correspondant à une famille."""
    fam_norm = _normalize(famille)
    for key in table.keys():
        if key == "_default":
            continue
        if _normalize(key) in fam_norm:
            return table[key]
    return table.get("_default", {})


def _format_eur(amount: float) -> str:
    """Formate un montant en euros avec séparateurs de milliers."""
    if abs(amount) >= 1000:
        return f"{amount:,.0f} €".replace(",", " ")
    return f"{amount:.0f} €"


# =============================================================================
# Devis 1 — Achat réemploi externe
# =============================================================================

def quote_achat_reemploi(matching_result) -> pd.DataFrame:
    """Devis pour les besoins du projet non couverts par le gisement.

    Returns:
        DataFrame avec 1 ligne par type x fournisseur, et colonnes
        Famille | Famille et type | Quantité | Fournisseur | PU min | PU med
        | PU max | Total min | Total med | Total max | Source.
    """
    df = matching_result.df_matching.loc[
        matching_result.df_matching["A_commander_externe"] > 0
    ].copy()

    rows = []
    for _, r in df.iterrows():
        qte = int(r["A_commander_externe"])
        prix_table = _lookup_price_table(r["Famille"], PRIX_ACHAT_REEMPLOI)
        for fournisseur, fourchette in prix_table.items():
            rows.append({
                "Famille": r["Famille"],
                "Famille et type": r["Famille et type"],
                "Quantité": qte,
                "Fournisseur": fournisseur,
                "PU min (€)": fourchette.min,
                "PU med (€)": fourchette.med,
                "PU max (€)": fourchette.max,
                "Total min (€)": qte * fourchette.min,
                "Total med (€)": qte * fourchette.med,
                "Total max (€)": qte * fourchette.max,
                "Source": fourchette.source,
            })
    return pd.DataFrame(rows)


def quote_achat_reemploi_summary(quote_df: pd.DataFrame) -> pd.DataFrame:
    """Synthèse par fournisseur : total cumulé (min/med/max) sur l'ensemble."""
    if len(quote_df) == 0:
        return pd.DataFrame(columns=["Fournisseur", "Total min (€)",
                                      "Total med (€)", "Total max (€)"])
    return (
        quote_df.groupby("Fournisseur")[
            ["Total min (€)", "Total med (€)", "Total max (€)"]
        ].sum().round(0).astype(int).reset_index()
        .sort_values("Total med (€)")
    )


# =============================================================================
# Devis 2 — Revente du surplus
# =============================================================================

def quote_revente(matching_result) -> pd.DataFrame:
    """Devis pour la revente du surplus du gisement existant."""
    df = matching_result.df_surplus.copy()
    rows = []
    for _, r in df.iterrows():
        qte = int(r["Surplus_a_revendre"])
        prix_table = _lookup_price_table(r["Famille"], PRIX_REVENTE_REEMPLOI)
        for plateforme, fourchette in prix_table.items():
            rows.append({
                "Famille": r["Famille"],
                "Famille et type": r["Famille et type"],
                "Quantité": qte,
                "Plateforme": plateforme,
                "Recette unit. min (€)": fourchette.min,
                "Recette unit. med (€)": fourchette.med,
                "Recette unit. max (€)": fourchette.max,
                "Recette tot. min (€)": qte * fourchette.min,
                "Recette tot. med (€)": qte * fourchette.med,
                "Recette tot. max (€)": qte * fourchette.max,
                "Source": fourchette.source,
            })
    return pd.DataFrame(rows)


def quote_revente_summary(quote_df: pd.DataFrame) -> pd.DataFrame:
    """Synthèse par plateforme."""
    if len(quote_df) == 0:
        return pd.DataFrame(columns=["Plateforme", "Recette tot. min (€)",
                                      "Recette tot. med (€)", "Recette tot. max (€)"])
    return (
        quote_df.groupby("Plateforme")[
            ["Recette tot. min (€)", "Recette tot. med (€)", "Recette tot. max (€)"]
        ].sum().round(0).astype(int).reset_index()
        .sort_values("Recette tot. med (€)", ascending=False)
    )


# =============================================================================
# Devis 3 — Recyclage matière
# =============================================================================

def quote_recyclage(df_existant_classifie: pd.DataFrame,
                    hypotheses=None) -> pd.DataFrame:
    """Devis recyclage matière à partir des éléments classés Recyclage.

    Le routage se fait via detect_material() qui identifie béton/brique/
    métal/bois/plâtre à partir de la famille et du type Revit.
    """
    if hypotheses is None:
        hypotheses = DEFAULT_BIM_DAS_TABLE

    sub = df_existant_classifie.loc[
        df_existant_classifie["Categorie"] == "Recyclage"
    ].copy()

    # Routage matière + masse cumulée
    rows = []
    masse_par_matiere = {}
    for _, r in sub.iterrows():
        matiere = detect_material(r["Famille"], r["Famille et type"])
        h = _lookup_hypothesis(r["Famille"], hypotheses)
        masse_par_matiere[matiere] = masse_par_matiere.get(matiere, 0) + h.masse_unit_t

    for matiere, masse_t in masse_par_matiere.items():
        prix_table = PRIX_RECYCLAGE.get(matiere, PRIX_RECYCLAGE["_default"])
        for fournisseur, fourchette in prix_table.items():
            # Convention : prix positif = on paye, prix négatif = recette
            cout_min = masse_t * fourchette.min
            cout_med = masse_t * fourchette.med
            cout_max = masse_t * fourchette.max
            rows.append({
                "Matière": matiere,
                "Masse (t)": round(masse_t, 2),
                "Filière": fournisseur,
                "PU min (€/t)": fourchette.min,
                "PU med (€/t)": fourchette.med,
                "PU max (€/t)": fourchette.max,
                "Coût min (€)": round(cout_min, 0),
                "Coût med (€)": round(cout_med, 0),
                "Coût max (€)": round(cout_max, 0),
                "Source": fourchette.source,
            })
    return pd.DataFrame(rows)


def quote_recyclage_summary(quote_df: pd.DataFrame) -> pd.DataFrame:
    """Synthèse par filière (somme algébrique : recettes - coûts)."""
    if len(quote_df) == 0:
        return pd.DataFrame(columns=["Filière", "Coût min (€)",
                                      "Coût med (€)", "Coût max (€)"])
    return (
        quote_df.groupby("Filière")[
            ["Coût min (€)", "Coût med (€)", "Coût max (€)"]
        ].sum().round(0).astype(int).reset_index()
        .sort_values("Coût med (€)")  # le moins cher (ou la plus grosse recette) en premier
    )


# =============================================================================
# Devis 4 — Déchets ultimes
# =============================================================================

def quote_dechets_ultimes(df_existant_classifie: pd.DataFrame,
                          hypotheses=None) -> pd.DataFrame:
    """Devis pour les éléments classés Autres déchets."""
    if hypotheses is None:
        hypotheses = DEFAULT_BIM_DAS_TABLE

    sub = df_existant_classifie.loc[
        df_existant_classifie["Categorie"] == "AutresDechets"
    ].copy()

    masse_t = sum(
        _lookup_hypothesis(r["Famille"], hypotheses).masse_unit_t
        for _, r in sub.iterrows()
    )

    rows = []
    for fournisseur, fourchette in PRIX_DECHETS_ULTIMES.items():
        rows.append({
            "Filière": fournisseur,
            "Masse (t)": round(masse_t, 2),
            "PU min (€/t)": fourchette.min,
            "PU med (€/t)": fourchette.med,
            "PU max (€/t)": fourchette.max,
            "Coût min (€)": round(masse_t * fourchette.min, 0),
            "Coût med (€)": round(masse_t * fourchette.med, 0),
            "Coût max (€)": round(masse_t * fourchette.max, 0),
            "Source": fourchette.source,
        })
    return pd.DataFrame(rows)


# =============================================================================
# Analyse / recommandation IA (heuristique)
# =============================================================================

def analyze_best_supplier(quote_summary: pd.DataFrame,
                          col_med: str,
                          objectif: str = "minimize") -> str:
    """Génère un texte d'analyse comparatif des fournisseurs.

    Args:
        quote_summary: DataFrame de synthèse (1 ligne par fournisseur).
        col_med: nom de la colonne de coût médian.
        objectif: 'minimize' pour minimiser le coût, 'maximize' pour
                  maximiser la recette (revente).

    Returns:
        Texte formaté Markdown avec recommandation.
    """
    if len(quote_summary) == 0:
        return "Aucune donnée à comparer."

    df = quote_summary.copy().reset_index(drop=True)
    name_col = df.columns[0]  # 'Fournisseur', 'Plateforme' ou 'Filière'

    if objectif == "minimize":
        best_idx = df[col_med].idxmin()
        worst_idx = df[col_med].idxmax()
        verb = "le moins coûteux"
        verb_inv = "le plus coûteux"
    else:
        best_idx = df[col_med].idxmax()
        worst_idx = df[col_med].idxmin()
        verb = "le plus rémunérateur"
        verb_inv = "le moins rémunérateur"

    best = df.iloc[best_idx]
    worst = df.iloc[worst_idx]
    delta = abs(best[col_med] - worst[col_med])

    lines = [
        f"**Recommandation : {best[name_col]}**",
        "",
        f"- **{best[name_col]}** ressort comme l'option {verb} avec "
        f"un montant médian estimé à **{_format_eur(best[col_med])}**.",
    ]
    if len(df) > 1:
        lines.append(
            f"- À l'inverse, **{worst[name_col]}** est {verb_inv} "
            f"({_format_eur(worst[col_med])}), soit un écart d'environ "
            f"**{_format_eur(delta)}** sur le périmètre étudié."
        )
    lines.extend([
        "",
        "_⚠ Ces estimations reposent sur des fourchettes publiques "
        "(ADEME, FFB, CycleUp 2024, prix spot Valobat/Paprec). "
        "À recouper avec un devis ferme avant engagement._",
    ])
    return "\n".join(lines)
