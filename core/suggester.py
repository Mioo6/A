"""
suggester.py
============
Système expert de suggestions de réemploi créatif et de modes constructifs
alternatifs, avec fallback optionnel vers l'API Claude (Haiku).

Deux niveaux d'intelligence :

  Niveau 1 — Système expert codé en dur (toujours actif, gratuit)
  ────────────────────────────────────────────────────────────────
  Matrice de compatibilité Famille_existant × Fonction_cible. Inspirée
  du Design for Deconstruction (Akinade 2015) et des retours empiriques
  CycleUp / Mobius / Backacia.

  Niveau 2 — LLM Claude Haiku (optionnel, si clé API fournie)
  ────────────────────────────────────────────────────────────────
  Quand l'utilisateur fournit une clé API, on envoie la liste des
  surplus + la liste des besoins du projet, et Claude génère 3-5
  suggestions créatives supplémentaires en langage naturel.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .classifier import _normalize


# =============================================================================
# Niveau 1 — Système expert : matrice de compatibilité
# =============================================================================

@dataclass
class CreativeSuggestion:
    """Une suggestion de réemploi créatif."""
    source_famille: str         # famille du gisement
    quantite_disponible: int    # nb d'éléments concernés
    usage_cible: str            # nouvelle fonction proposée
    description: str            # justification technique courte
    icone: str = "💡"           # symbole pour l'affichage


# Règles de transfert : si on a X dans le gisement, on peut suggérer Y
# Chaque règle est une liste de tuples (motif_famille, suggestions)
RULES_FROM_FAMILY: dict[str, list[dict]] = {
    # --- Façades légères et menuiseries ---
    "porte": [
        {"usage": "Cloison amovible intérieure",
         "desc": "Une porte intérieure démontée peut servir de panneau de "
                 "cloison légère (R+isolation périphérique). Idéal pour des "
                 "bureaux temporaires ou box techniques."},
        {"usage": "Plateau de table / mobilier",
         "desc": "Vantail de porte poncé et stabilisé en plateau de bureau, "
                 "table de réfectoire, comptoir d'accueil."},
        {"usage": "Bardage extérieur secondaire",
         "desc": "Sur abris de jardin, locaux techniques ou abris à vélos, "
                 "après traitement hydrofuge."},
    ],
    "fenetre": [
        {"usage": "Verrière intérieure / cloison vitrée",
         "desc": "Châssis vitré reposé en cloison séparative entre bureaux, "
                 "apport de lumière naturelle en second jour."},
        {"usage": "Serre / véranda non chauffée",
         "desc": "Assemblage de châssis pour serre pédagogique ou véranda "
                 "non chauffée (jardin, locaux annexes)."},
    ],
    "vitre": [
        {"usage": "Garde-corps vitré",
         "desc": "Vitrage feuilleté reposé en garde-corps de balcon ou "
                 "passerelle (vérification résistance choc obligatoire)."},
        {"usage": "Cloison vitrée / verrière",
         "desc": "Cloison vitrée intérieure pour bureaux ou salles de classe."},
    ],
    "mur-rideau": [
        {"usage": "Façade légère secondaire / abri",
         "desc": "Modules de mur-rideau récupérés intégrables sur extension "
                 "légère, abri vélo couvert, hall d'accueil."},
        {"usage": "Cloison de séparation grande hauteur",
         "desc": "Idéal pour cloisonner des plateaux ouverts (open space, "
                 "halle technique) avec apport visuel."},
    ],
    "panneau systeme": [
        {"usage": "Cloison légère ou bardage",
         "desc": "Panneaux modulaires démontables, parfaits pour cloison "
                 "intérieure ou bardage de modulaire de chantier."},
    ],
    "meneau": [
        {"usage": "Ossature de mur-rideau secondaire",
         "desc": "Profilés alu boulonnés réutilisables pour ossature de "
                 "petit mur-rideau (abri, atrium, sas)."},
        {"usage": "Garde-corps métallique",
         "desc": "Profilés réutilisables comme cadre de garde-corps après "
                 "vérification structurelle."},
    ],
    "int. simple": [
        {"usage": "Porte de remise / locaux annexes",
         "desc": "Réinstallation directe en locaux techniques, vestiaires, "
                 "salles de stockage."},
        {"usage": "Cloison amovible bureau",
         "desc": "Vantail intégré dans un système de cloison amovible "
                 "(open space modulable)."},
    ],

    # --- Maçonnerie et briques ---
    "brique": [
        {"usage": "Mur de gabion / soutènement paysager",
         "desc": "Concassage de briques propres en remplissage de gabions "
                 "métalliques pour murs de soutènement extérieurs ou "
                 "limites de propriété (méthode validée pour ESTP)."},
        {"usage": "Dallage extérieur / sentier",
         "desc": "Briques entières conservées en pavement piéton, allées "
                 "de jardin ou cours de récréation."},
        {"usage": "Mur de jardinière surélevée",
         "desc": "Briques empilées à sec pour jardinières, bacs de "
                 "permaculture, bordures de plates-bandes."},
    ],
    "parement": [
        {"usage": "Bardage de bâtiment annexe",
         "desc": "Plaques de parement déposées et rééquipées sur extension "
                 "légère ou bâtiment secondaire."},
        {"usage": "Mur de gabion remplissage",
         "desc": "Concassage en granulats décoratifs pour gabion."},
    ],
    "voileba": [
        {"usage": "Concassé pour remblai technique",
         "desc": "Béton armé déconstruit → granulats recyclés pour sous-"
                 "couche de chaussée, plate-forme de chantier, drainage."},
    ],

    # --- Sol béton ---
    "sol": [
        {"usage": "Dalle découpée → renfort de balcon ou platelage",
         "desc": "Tronçons de dalle béton découpée à la scie diamant et "
                 "réutilisés en pas japonais, platelage de cour, ou "
                 "renforcement de fondation légère."},
        {"usage": "Concassé routier",
         "desc": "Granulats recyclés pour sous-couche routière (norme "
                 "NF EN 13242 type 0/63)."},
    ],
    "dalle": [
        {"usage": "Pas japonais / dalle de jardin",
         "desc": "Dalles entières ou découpées en cheminement piéton, "
                 "place pavée, terrasse extérieure."},
    ],

    # --- Bois lamellé-collé ---
    "lamelle-colle": [
        {"usage": "Mobilier urbain / bancs d'extérieur",
         "desc": "Tronçons de poutres lamellé-collé poncés et lasurés en "
                 "bancs, tables de pique-nique, signalétique."},
        {"usage": "Bardage rythmé / brise-soleil",
         "desc": "Lamelles débitées en bardage extérieur ou brise-soleil "
                 "pour façade sud."},
        {"usage": "Charpente d'abri secondaire",
         "desc": "Pièces structurelles intactes réintégrées en charpente "
                 "d'abri vélo, préau, terrasse couverte."},
    ],
    "bois": [
        {"usage": "Mobilier extérieur",
         "desc": "Pièces saines réutilisées en mobilier (banc, table, "
                 "jardinière en bois)."},
        {"usage": "Bardage extérieur",
         "desc": "Lames assemblées en bardage ventilé après traitement."},
    ],

    # --- Métaux ---
    "metal": [
        {"usage": "Mobilier urbain métallique",
         "desc": "Profilés réutilisés en piètement de banc, support de "
                 "signalétique, racks à vélos."},
        {"usage": "Garde-corps / passerelle",
         "desc": "Profilés acier reconditionnés pour garde-corps, "
                 "passerelle technique."},
    ],
    "escalier metallique": [
        {"usage": "Reposé ailleurs sur site",
         "desc": "Escalier métallique boulonné démonté et reposé en "
                 "passerelle technique, accès toiture, escalier de secours."},
    ],
    "by_str_escalier": [
        {"usage": "Reposé ailleurs sur site",
         "desc": "Escalier préfabriqué ancré démontable, reposé en "
                 "circulation secondaire ou bâtiment annexe."},
    ],

    # --- Garde-corps ---
    "garde-corps": [
        {"usage": "Reposé sur balcon / mezzanine secondaire",
         "desc": "Modules métalliques boulonnés, redéployables sur tout "
                 "espace nécessitant une protection à la chute."},
    ],
}


# Suggestions de modes constructifs alternatifs (proposées indépendamment
# du contenu, à la première analyse, comme inspirations possibles)
ALTERNATIVE_CONSTRUCTION_MODES = [
    {
        "icone": "🏠",
        "titre": "Mur en pisé à partir des terres de terrassement",
        "description": (
            "Si l'analyse géotechnique des terres excavées sur site "
            "(argile 15–30 %, limon 30–50 %, sable 30–50 %) le permet, "
            "envisager des murs en pisé pour les façades intérieures "
            "ou cloisons épaisses du gymnase. Bilan carbone < 30 kgCO₂/m² "
            "vs 250 kgCO₂/m² pour un mur béton équivalent (FDES INIES)."
        ),
        "condition": "Existence de terrassement sur le projet",
    },
    {
        "icone": "🧱",
        "titre": "Murs de gabion à partir de briques/béton concassé",
        "description": (
            "Les briques de parement et le béton du bâti existant peuvent "
            "être concassés sur place (concasseur mobile) et utilisés en "
            "remplissage de gabions métalliques pour murs de soutènement, "
            "limites de propriété ou aménagements paysagers du campus. "
            "Évite l'évacuation des gravats (gain ~80 €/t en taxe de "
            "décharge ISDI)."
        ),
        "condition": "Présence de béton/brique en quantité suffisante (> 50 t)",
    },
    {
        "icone": "🌱",
        "titre": "Toiture végétalisée extensive",
        "description": (
            "Sur le futur Learning Center, prévoir une toiture végétalisée "
            "extensive (substrat 8–12 cm, sedum) en complément des "
            "panneaux photovoltaïques. Améliore le confort d'été et la "
            "rétention d'eau pluviale (gestion des EP 30–50 mm)."
        ),
        "condition": "Bâtiment avec toiture-terrasse",
    },
    {
        "icone": "🪵",
        "titre": "Structure mixte bois-béton",
        "description": (
            "Pour le gymnase, envisager une charpente lamellé-collé en "
            "remplacement partiel de l'acier ou du béton. La filière bois "
            "est circulaire (déboulonnable, recyclable) et stocke ~250 kg "
            "de CO₂ par m³ (vs +400 kg/m³ pour béton)."
        ),
        "condition": "Phase conception du gymnase",
    },
    {
        "icone": "💧",
        "titre": "Béton bas carbone CEM III ou granulats recyclés",
        "description": (
            "Pour les voiles et dalles structurelles neuves, spécifier un "
            "béton CEM III/A (laitier) ou intégrant 20–30 % de granulats "
            "recyclés issus du concassage de l'existant. Réduction de "
            "30–50 % de l'impact carbone (norme NF EN 206 + NF P 18-545)."
        ),
        "condition": "Présence d'éléments béton structurels neufs",
    },
]


# =============================================================================
# Génération des suggestions niveau 1 (système expert)
# =============================================================================

def suggest_creative_uses(
    matching_result,
    df_existant_classifie: pd.DataFrame,
) -> list[CreativeSuggestion]:
    """Génère les suggestions créatives à partir du surplus du gisement.

    Args:
        matching_result: résultat du matcher (contient df_surplus)
        df_existant_classifie: l'existant complet (pour cas hors réemploi)

    Returns:
        Liste de CreativeSuggestion ordonnées par quantité décroissante.
    """
    suggestions = []
    df_surplus = matching_result.df_surplus

    # --- Pour chaque type en surplus, on cherche des règles applicables ---
    if len(df_surplus):
        for _, row in df_surplus.iterrows():
            fam_norm = _normalize(row["Famille"])
            fet_norm = _normalize(row["Famille et type"])
            qte = int(row["Surplus_a_revendre"])

            for motif, regles in RULES_FROM_FAMILY.items():
                if _normalize(motif) in fam_norm or _normalize(motif) in fet_norm:
                    for r in regles:
                        suggestions.append(CreativeSuggestion(
                            source_famille=row["Famille"],
                            quantite_disponible=qte,
                            usage_cible=r["usage"],
                            description=r["desc"],
                        ))
                    break  # une famille → un seul groupe de règles

    # --- On ajoute aussi les suggestions issues du Recyclage et des Autres
    # déchets qui peuvent avoir une seconde vie créative (briques→gabion,
    # bois→mobilier...) ---
    masse_par_fam = (
        df_existant_classifie.groupby("Famille").size().to_dict()
    )
    for fam, qte in masse_par_fam.items():
        cat = df_existant_classifie.loc[
            df_existant_classifie["Famille"] == fam, "Categorie"
        ].iloc[0]
        if cat == "Reemploi":
            continue  # déjà traité
        fam_norm = _normalize(fam)
        for motif, regles in RULES_FROM_FAMILY.items():
            if _normalize(motif) in fam_norm:
                for r in regles:
                    suggestions.append(CreativeSuggestion(
                        source_famille=fam,
                        quantite_disponible=int(qte),
                        usage_cible=r["usage"],
                        description=r["desc"],
                    ))
                break

    # Tri : on met en premier les surplus de réemploi non utilisés
    suggestions.sort(key=lambda s: -s.quantite_disponible)
    return suggestions


def get_alternative_construction_modes(
    df_existant_classifie: pd.DataFrame,
) -> list[dict]:
    """Renvoie les modes constructifs alternatifs pertinents pour ce projet."""
    # Pour l'instant on retourne tous les modes ; à terme on peut filtrer
    # selon la présence ou non des conditions dans le projet.
    return list(ALTERNATIVE_CONSTRUCTION_MODES)


# =============================================================================
# Niveau 2 — Fallback LLM Claude Haiku
# =============================================================================

def query_claude_for_suggestions(
    api_key: str,
    df_surplus: pd.DataFrame,
    df_demande_externe: pd.DataFrame,
    n_max_suggestions: int = 5,
    timeout_s: int = 30,
) -> tuple[list[dict], Optional[str]]:
    """Interroge Claude Haiku pour des suggestions créatives complémentaires.

    Args:
        api_key: clé API Anthropic (saisie utilisateur, jamais stockée).
        df_surplus: éléments existants en surplus à valoriser.
        df_demande_externe: éléments du projet à acheter en externe.
        n_max_suggestions: nombre cible de suggestions à demander.
        timeout_s: timeout HTTP.

    Returns:
        (liste de dicts {usage_cible, source_famille, description},
         message d'erreur éventuel ou None)
    """
    try:
        import anthropic
    except ImportError:
        return [], "Le package 'anthropic' n'est pas installé."

    if not api_key or not api_key.strip():
        return [], "Aucune clé API fournie."

    # Prépare le contexte concis
    surplus_text = ""
    if len(df_surplus):
        surplus_text = df_surplus.head(30).to_string(index=False, max_colwidth=60)
    else:
        surplus_text = "(aucun surplus identifié)"

    demande_text = ""
    if len(df_demande_externe):
        demande_text = df_demande_externe.head(30).to_string(index=False, max_colwidth=60)
    else:
        demande_text = "(aucun besoin externe)"

    prompt = f"""Tu es un ingénieur expert en économie circulaire du BTP, spécialiste du Design for Deconstruction (Akinade 2015) et du diagnostic PEMD français.

Voici les SURPLUS du bâti existant (composants Revit en réemploi, non utilisables tels quels sur le projet) :
{surplus_text}

Voici les BESOINS du projet final non couverts par le gisement (à acheter en externe) :
{demande_text}

Ta mission : propose {n_max_suggestions} pistes CRÉATIVES de réemploi qui n'apparaissent pas dans une matrice de règles standard. Pense particulièrement à :
  - Croiser surplus et besoins (ex. "porte vitrée → demi-cloison vitrée du bureau")
  - Proposer des modes constructifs alternatifs (pisé, gabion, terre-paille, mortier de chaux)
  - Valoriser ce qui aurait été perdu en déchet (brique cassée → granulat décoratif)
  - Penser aux usages secondaires sur site (mobilier urbain, signalétique, jardins)

Réponds UNIQUEMENT en JSON valide, format strict :
{{
  "suggestions": [
    {{
      "source_famille": "nom de la famille du gisement",
      "usage_cible": "nouvelle fonction proposée (concise)",
      "description": "1 à 2 phrases de justification technique précise"
    }},
    ...
  ]
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s)
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()

        # Parse JSON (robust : on cherche le premier { et le dernier })
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return [], f"Réponse LLM non parsable : {text[:200]}"
        payload = json.loads(text[start:end + 1])
        return payload.get("suggestions", []), None

    except json.JSONDecodeError as e:
        return [], f"JSON invalide : {e}"
    except Exception as e:
        return [], f"Erreur API : {type(e).__name__}: {e}"
