"""
bim_das.py
==========
Calcul du score BIM-DAS (Building Information Modeling — Deconstructability
Assessment Score) selon la formulation d'Akinade et al. (2015), reprise dans
le livrable PIR ESTP.

Formule globale :
    DAS = 0.5 × Dscore + 0.5 × Rscore

Sous-score "Deconstruction Score" (Dscore) :
    Dscore = (tn + dc + RP) / 3
        tn = 1 - (t/n)            # diversité matériaux
        dc = (Cb+Cd)/(Cb+Cd+Cn+Cf) # ratio connexions démontables
        RP                          # ratio préfabrication

Sous-score "Recovery Score" (Rscore) :
    Rscore = (R1 + R2 + Rs + Rx) / 4
        R1 = potentiel réemploi
        R2 = potentiel recyclage
        Rs = absence finitions secondaires
        Rx = non-toxicité

Comme les CSV Revit n'exposent pas directement les types de connexions, les
ratios de préfabrication, etc., on utilise la table d'hypothèses par famille
(admin_data.DEFAULT_BIM_DAS_TABLE), pondérée par le nombre d'éléments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .admin_data import (
    DEFAULT_BIM_DAS_TABLE,
    GENERIC_HYPOTHESIS,
    FamilyHypothesis,
)
from .classifier import _normalize


@dataclass
class BIMDASResult:
    """Résultat détaillé du calcul BIM-DAS."""
    dscore: float       # ∈ [0, 1]
    rscore: float       # ∈ [0, 1]
    das: float          # ∈ [0, 1]
    # Détail des composantes du Dscore
    tn: float
    dc: float
    rp: float
    # Détail des composantes du Rscore
    r1: float
    r2: float
    rs: float
    rx: float
    # Statistiques contextuelles
    n_elements: int
    n_familles: int

    @property
    def das_pct(self) -> float:
        """Score BIM-DAS exprimé en pourcentage [0–100]."""
        return 100.0 * self.das

    def as_breakdown_dict(self) -> dict:
        """Renvoie un dict prêt à afficher dans un st.dataframe."""
        return {
            "Composante": [
                "tn (diversité matériaux)",
                "dc (connexions démontables)",
                "RP (préfabrication)",
                "→ D-score",
                "R1 (potentiel réemploi)",
                "R2 (potentiel recyclage)",
                "Rs (absence finitions secondaires)",
                "Rx (non-toxicité)",
                "→ R-score",
                "★ BIM-DAS global",
            ],
            "Valeur (0–1)": [
                f"{self.tn:.3f}", f"{self.dc:.3f}", f"{self.rp:.3f}",
                f"{self.dscore:.3f}",
                f"{self.r1:.3f}", f"{self.r2:.3f}",
                f"{self.rs:.3f}", f"{self.rx:.3f}",
                f"{self.rscore:.3f}",
                f"{self.das:.3f}",
            ],
        }


def _lookup_hypothesis(famille: str,
                       hypotheses: dict[str, FamilyHypothesis]) -> FamilyHypothesis:
    """Trouve l'hypothèse la plus adaptée pour une famille donnée.

    On cherche la clé du dict qui apparaît dans la famille normalisée. Si
    plusieurs clés matchent (ex. 'mur de base' ET 'mur'), on prend la plus
    longue (la plus spécifique).
    """
    fam_norm = _normalize(famille)
    matches = [k for k in hypotheses.keys() if _normalize(k) in fam_norm]
    if not matches:
        return GENERIC_HYPOTHESIS
    # Priorité au motif le plus long
    best_key = max(matches, key=len)
    return hypotheses[best_key]


def compute_bim_das(
    df: pd.DataFrame,
    hypotheses: Optional[dict[str, FamilyHypothesis]] = None,
) -> BIMDASResult:
    """Calcule le BIM-DAS d'un ensemble d'éléments Revit.

    Args:
        df: DataFrame avec colonnes "Famille" et "Famille et type".
            Peut être un sous-ensemble (ex. uniquement le projet final
            après optimisation circulaire).
        hypotheses: dict famille→FamilyHypothesis, par défaut la table
                    centrale (DEFAULT_BIM_DAS_TABLE). L'admin peut
                    surcharger via la sidebar.

    Returns:
        BIMDASResult avec scores et détail des composantes.
    """
    if hypotheses is None:
        hypotheses = DEFAULT_BIM_DAS_TABLE

    if len(df) == 0:
        return BIMDASResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    n = len(df)
    t = df["Famille et type"].nunique()  # nombre de types distincts

    # tn : diversité = 1 - t/n. Plus t/n est petit (peu de types pour beaucoup
    # d'éléments), plus la déconstruction est efficace (moins de tri).
    tn = max(0.0, min(1.0, 1.0 - t / n))

    # Pour dc, RP, R1, R2, Rs, Rx : moyenne pondérée par le nombre d'éléments
    # de chaque famille (chaque ligne contribue selon l'hypothèse de sa famille).
    dc_acc = rp_acc = r1_acc = r2_acc = rs_acc = rx_acc = 0.0

    for _, row in df.iterrows():
        h = _lookup_hypothesis(row.get("Famille", ""), hypotheses)
        dc_acc += h.dc
        rp_acc += h.rp
        r1_acc += h.r1
        r2_acc += h.r2
        rs_acc += h.rs
        rx_acc += h.rx

    dc = dc_acc / n
    rp = rp_acc / n
    r1 = r1_acc / n
    r2 = r2_acc / n
    rs = rs_acc / n
    rx = rx_acc / n

    dscore = (tn + dc + rp) / 3.0
    rscore = (r1 + r2 + rs + rx) / 4.0
    das = 0.5 * dscore + 0.5 * rscore

    return BIMDASResult(
        dscore=dscore, rscore=rscore, das=das,
        tn=tn, dc=dc, rp=rp,
        r1=r1, r2=r2, rs=rs, rx=rx,
        n_elements=n, n_familles=df["Famille"].nunique(),
    )


# =============================================================================
# Calcul de la masse totale (utilisé par les KPIs déchets/carbone)
# =============================================================================

def estimate_total_mass_tonnes(
    df: pd.DataFrame,
    hypotheses: Optional[dict[str, FamilyHypothesis]] = None,
) -> float:
    """Estime la masse totale en tonnes via les hypothèses de masse unitaire."""
    if hypotheses is None:
        hypotheses = DEFAULT_BIM_DAS_TABLE
    total = 0.0
    for _, row in df.iterrows():
        h = _lookup_hypothesis(row.get("Famille", ""), hypotheses)
        total += h.masse_unit_t
    return total


def estimate_mass_by_category(
    df_classified: pd.DataFrame,
    hypotheses: Optional[dict[str, FamilyHypothesis]] = None,
) -> dict[str, float]:
    """Masse totale par catégorie (Reemploi / Recyclage / AutresDechets)."""
    out = {"Reemploi": 0.0, "Recyclage": 0.0, "AutresDechets": 0.0}
    for cat in out.keys():
        sub = df_classified[df_classified["Categorie"] == cat]
        out[cat] = estimate_total_mass_tonnes(sub, hypotheses)
    return out
