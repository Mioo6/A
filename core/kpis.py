"""
kpis.py
=======
Calcul des 5 indicateurs de performance pour le tableau de bord :

  1. Volume de déchets       (tonnes, avant/après)
  2. Empreinte carbone       (kgCO2e, avant/après)
  3. Score BIM-DAS           (0–100, sur le projet final)
  4. Coût total              (€, avant/après)
  5. Durée du chantier       (jours, avant/après)

Sources des hypothèses :
  - Carbone moyen : 750 kgCO2e/m² (ADEME)
  - Volume déchets : 50 kg/m² (ADEME)
  - Gain temps : -15 % (CIFE Stanford)
  - Réduction déchets : -20 % (WRAP UK)
  - Réduction carbone : -10 % (Journal of Cleaner Production)
  - Coûts : 800 €/m² démolition vs 350 €/m² dépose soignée (FFB / CycleUp)
  - Durée chantier : ~6 mois pour 7400 m² → 0.025 j/m²
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .admin_data import GlobalRatios
from .bim_das import (
    BIMDASResult,
    compute_bim_das,
    estimate_mass_by_category,
)


@dataclass
class KPISet:
    """Ensemble des 5 KPIs avant/après."""
    # Volume déchets (tonnes)
    dechets_avant_t: float
    dechets_apres_t: float
    # Carbone (kgCO2e)
    carbone_avant_kg: float
    carbone_apres_kg: float
    # BIM-DAS (0-100, score du projet final optimisé)
    bim_das: float
    # Coût total (€)
    cout_avant_eur: float
    cout_apres_eur: float
    # Durée chantier (jours)
    duree_avant_j: float
    duree_apres_j: float

    # Détail BIM-DAS
    bim_das_detail: BIMDASResult = None

    # Champs annexes
    surface_m2: float = 0.0
    masse_existant_t: float = 0.0

    @property
    def gain_dechets_t(self) -> float:
        return self.dechets_avant_t - self.dechets_apres_t

    @property
    def gain_carbone_kg(self) -> float:
        return self.carbone_avant_kg - self.carbone_apres_kg

    @property
    def gain_cout_eur(self) -> float:
        return self.cout_avant_eur - self.cout_apres_eur

    @property
    def gain_duree_j(self) -> float:
        return self.duree_avant_j - self.duree_apres_j


def compute_all_kpis(
    df_existant_classifie: pd.DataFrame,
    df_projet_classifie: pd.DataFrame,
    surface_m2: float,
    n_reemployes_in_situ: int,
    ratios: GlobalRatios = None,
) -> KPISet:
    """Calcule l'ensemble des 5 KPIs.

    Args:
        df_existant_classifie: DataFrame de l'existant avec colonne 'Categorie'
        df_projet_classifie: DataFrame du projet avec colonne 'Categorie'
        surface_m2: surface du chantier en m²
        n_reemployes_in_situ: nombre d'éléments effectivement réemployés
                              sur place (résultat du matcher)
        ratios: GlobalRatios (par défaut valeurs ADEME/FFB)

    Returns:
        KPISet complet.
    """
    if ratios is None:
        ratios = GlobalRatios()

    # --- 1. Volume de déchets ------------------------------------------------
    # Avant (scénario standard démolition) : on prend la valeur ADEME pure
    # surface × kg/m² → tonnes. C'est la masse totale de déchets générés
    # sur un chantier de cette taille en mode démolition classique.
    dechets_avant_t = surface_m2 * ratios.dechets_kg_m2 / 1000.0

    # Après (avec circularité) : on applique le gain en pourcentage
    dechets_apres_t = dechets_avant_t * (1.0 - ratios.gain_dechets_pct / 100.0)

    # --- 2. Empreinte carbone ------------------------------------------------
    # Avant : valeur de référence ADEME × surface
    carbone_avant_kg = surface_m2 * ratios.carbone_kgco2_m2

    # Après : on retranche le gain en %
    # (Le réemploi évite la fabrication neuve = gros gain ;
    # le recyclage évite l'extraction = gain modéré)
    carbone_apres_kg = carbone_avant_kg * (1.0 - ratios.gain_carbone_pct / 100.0)

    # --- 3. BIM-DAS ----------------------------------------------------------
    # Calculé sur le projet final (= la cible : ce qu'on conçoit pour être
    # déconstructible plus tard). La référence de 'avant' est implicite.
    das_result = compute_bim_das(df_projet_classifie)

    # --- 4. Coût total -------------------------------------------------------
    # Avant : démolition + évacuation totale standard
    cout_avant_eur = surface_m2 * ratios.cout_demolition_eur_m2

    # Après : dépose soignée + recettes du réemploi/revente (estimation
    # forfaitaire ; le détail précis viendra des devis dans la phase 5).
    cout_apres_eur = surface_m2 * ratios.cout_depose_soignee_eur_m2
    # Bonus : recette estimée moyenne par élément réemployé in situ ou revendu
    # (on prend 80 €/élément en moyenne — fourchette CycleUp/Backacia)
    cout_apres_eur -= n_reemployes_in_situ * 80.0

    # --- 5. Durée du chantier ------------------------------------------------
    duree_avant_j = surface_m2 * ratios.duree_chantier_jours_m2
    duree_apres_j = duree_avant_j * (1.0 - ratios.gain_temps_pct / 100.0)

    # --- Annexe : masse de l'existant ---------------------------------------
    masses = estimate_mass_by_category(df_existant_classifie)
    masse_existant_t = sum(masses.values())

    return KPISet(
        dechets_avant_t=dechets_avant_t,
        dechets_apres_t=dechets_apres_t,
        carbone_avant_kg=carbone_avant_kg,
        carbone_apres_kg=carbone_apres_kg,
        bim_das=das_result.das_pct,
        cout_avant_eur=cout_avant_eur,
        cout_apres_eur=cout_apres_eur,
        duree_avant_j=duree_avant_j,
        duree_apres_j=duree_apres_j,
        bim_das_detail=das_result,
        surface_m2=surface_m2,
        masse_existant_t=masse_existant_t,
    )
