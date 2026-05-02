"""
app.py — Circul'BIM
====================
Application Streamlit d'analyse circulaire de projets BIM Revit.

Usage :
    streamlit run app.py

Workflow :
  1. L'utilisateur charge deux nomenclatures Revit (existant + projet)
  2. Saisit la surface du chantier et ajuste les hypothèses si besoin
  3. (optionnel) fournit une clé API Anthropic pour les suggestions enrichies
  4. Lance l'analyse → 6 onglets de résultats
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Permet à Streamlit de retrouver le package core/
sys.path.insert(0, str(Path(__file__).parent))

from core.admin_data import (
    DEFAULT_BIM_DAS_TABLE, GENERIC_HYPOTHESIS, FamilyHypothesis,
    GlobalRatios, PALETTES,
)
from core.loader import load_revit_nomenclature, get_dataset_summary
from core.classifier import classify_dataframe, summarize_classification
from core.excel_exporter import build_xlsx
from core.bim_das import compute_bim_das
from core.kpis import compute_all_kpis
from core.matcher import match_onsite
from core.suggester import (
    suggest_creative_uses,
    get_alternative_construction_modes,
    query_claude_for_suggestions,
)
from core.quotes import (
    quote_achat_reemploi, quote_achat_reemploi_summary,
    quote_revente, quote_revente_summary,
    quote_recyclage, quote_recyclage_summary,
    quote_dechets_ultimes,
    analyze_best_supplier,
)


# =============================================================================
# Configuration de la page
# =============================================================================

st.set_page_config(
    page_title="Circul'BIM — Analyse circulaire BIM",
    page_icon="♻",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS custom pour les KPI cards
st.markdown("""
<style>
.kpi-card {
    border-radius: 12px;
    padding: 18px 16px;
    margin: 6px 0;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    background: white;
    border: 1px solid #ECEFF1;
}
.kpi-title {
    font-size: 0.85rem;
    color: #607D8B;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 4px;
}
.kpi-after {
    font-size: 1.7rem;
    font-weight: 700;
    color: #1B5E20;
    line-height: 1.1;
}
.kpi-before {
    font-size: 0.95rem;
    color: #B0BEC5;
    text-decoration: line-through;
    margin-top: 2px;
}
.kpi-gain {
    font-size: 0.85rem;
    font-weight: 600;
    color: #2E7D32;
    margin-top: 4px;
}
.kpi-neutral .kpi-after {
    color: #37474F;
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ECEFF1 0%, #FAFAFA 100%);
}
.stTabs [data-baseweb="tab-list"] button {
    font-size: 0.95rem;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Helpers d'affichage
# =============================================================================

def fmt_eur(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e6:
        return f"{sign}{x/1e6:.2f} M€"
    if x >= 1e3:
        return f"{sign}{x/1e3:.0f} k€"
    return f"{sign}{x:.0f} €"


def kpi_card(title: str, after: str, before: str | None = None,
             gain: str | None = None, neutral: bool = False):
    """Affiche une carte KPI stylée."""
    extra_class = " kpi-neutral" if neutral else ""
    parts = [f'<div class="kpi-card{extra_class}">']
    parts.append(f'<div class="kpi-title">{title}</div>')
    parts.append(f'<div class="kpi-after">{after}</div>')
    if before:
        parts.append(f'<div class="kpi-before">avant : {before}</div>')
    if gain:
        parts.append(f'<div class="kpi-gain">{gain}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# =============================================================================
# Sidebar — paramètres et upload
# =============================================================================

with st.sidebar:
    st.markdown("## ♻ Circul'BIM")
    st.caption("Analyse circulaire de projets BIM")
    st.divider()

    st.markdown("### 📂 Fichiers")
    f_existant = st.file_uploader(
        "Nomenclature Revit — **existant** (PEMD)",
        type=["csv"],
        key="upload_existant",
    )
    f_projet = st.file_uploader(
        "Nomenclature Revit — **projet final**",
        type=["csv"],
        key="upload_projet",
    )

    st.divider()
    st.markdown("### 📐 Paramètres du chantier")
    surface_m2 = st.number_input(
        "Surface SHON (m²)",
        min_value=100, max_value=200_000, value=7400, step=100,
        help="Surface hors œuvre nette du chantier. Sert de base pour "
             "les calculs de KPIs au mètre carré (ADEME).",
    )

    st.divider()
    with st.expander("⚙ Ratios globaux (avancé)", expanded=False):
        carbone_ref = st.slider(
            "Carbone neuf de référence (kgCO₂/m²)",
            300.0, 1500.0, 750.0, step=10.0,
            help="ADEME — moyenne neuf hors usage."
        )
        dechets_ref = st.slider(
            "Volume déchets de référence (kg/m²)",
            10.0, 200.0, 50.0, step=1.0,
            help="ADEME — déchets de chantier."
        )
        cout_demol = st.slider(
            "Coût démolition standard (€/m²)",
            300.0, 1500.0, 800.0, step=10.0,
            help="FFB — démolition classique."
        )
        cout_depose = st.slider(
            "Coût dépose soignée (€/m²)",
            100.0, 800.0, 350.0, step=10.0,
            help="FFB / CycleUp — dépose pour réemploi."
        )
        gain_carbone = st.slider(
            "Gain carbone (%)",
            0.0, 50.0, 10.0, step=0.5,
            help="Cleaner Production : -10 % typique."
        )
        gain_dechets = st.slider(
            "Gain déchets (%)",
            0.0, 50.0, 20.0, step=0.5,
            help="WRAP UK : -20 % typique."
        )
        gain_temps = st.slider(
            "Gain temps chantier (%)",
            0.0, 50.0, 15.0, step=0.5,
            help="CIFE Stanford : -15 % typique."
        )

    st.divider()
    with st.expander("🎯 Hypothèses BIM-DAS par famille (avancé)",
                     expanded=False):
        st.caption(
            "Ces valeurs (issues d'Akinade 2015 et de la base FDES INIES) "
            "peuvent être ajustées famille par famille. Cliquez sur une "
            "famille pour modifier ses paramètres."
        )
        # On expose un sélecteur + 6 sliders pour la famille choisie
        fam_options = list(DEFAULT_BIM_DAS_TABLE.keys())
        fam_selected = st.selectbox(
            "Famille à éditer",
            fam_options,
            help="Choisissez une famille pour modifier ses paramètres.",
        )
        h_default = DEFAULT_BIM_DAS_TABLE[fam_selected]
        st.caption(f"_{h_default.rationale}_")

        col_a, col_b = st.columns(2)
        with col_a:
            override_dc = st.slider(
                "dc — connexions démontables", 0.0, 1.0,
                float(h_default.dc), 0.05,
                key=f"dc_{fam_selected}",
            )
            override_rp = st.slider(
                "RP — préfabrication", 0.0, 1.0,
                float(h_default.rp), 0.05,
                key=f"rp_{fam_selected}",
            )
            override_rs = st.slider(
                "Rs — finitions secondaires absentes", 0.0, 1.0,
                float(h_default.rs), 0.05,
                key=f"rs_{fam_selected}",
            )
        with col_b:
            override_rx = st.slider(
                "Rx — non-toxicité", 0.0, 1.0,
                float(h_default.rx), 0.05,
                key=f"rx_{fam_selected}",
            )
            override_r1 = st.slider(
                "R1 — potentiel réemploi", 0.0, 1.0,
                float(h_default.r1), 0.05,
                key=f"r1_{fam_selected}",
            )
            override_r2 = st.slider(
                "R2 — potentiel recyclage", 0.0, 1.0,
                float(h_default.r2), 0.05,
                key=f"r2_{fam_selected}",
            )
        override_masse = st.number_input(
            "Masse moyenne par élément (t)",
            min_value=0.0, max_value=20.0,
            value=float(h_default.masse_unit_t), step=0.05,
            key=f"masse_{fam_selected}",
        )

        # On enregistre les overrides dans st.session_state
        if "hyp_overrides" not in st.session_state:
            st.session_state.hyp_overrides = {}
        st.session_state.hyp_overrides[fam_selected] = FamilyHypothesis(
            dc=override_dc, rp=override_rp, rs=override_rs, rx=override_rx,
            r1=override_r1, r2=override_r2,
            masse_unit_t=override_masse,
            rationale=h_default.rationale + " (modifié par admin)",
        )

    st.divider()
    with st.expander("🤖 Suggestions enrichies par IA (optionnel)",
                     expanded=False):
        st.caption(
            "Si vous fournissez une clé API Anthropic, le système expert "
            "sera complété par 5 suggestions générées par Claude Haiku. "
            "Votre clé n'est jamais stockée."
        )
        api_key = st.text_input(
            "Clé API Anthropic",
            type="password",
            key="api_key",
            help="Format : sk-ant-...",
        )

    st.divider()
    run_btn = st.button("🚀 Lancer l'analyse", type="primary",
                        use_container_width=True,
                        disabled=not (f_existant and f_projet))


# =============================================================================
# Page principale
# =============================================================================

st.title("♻ Circul'BIM")
st.caption(
    "Analyse circulaire d'un projet BIM Revit — tri PEMD, calcul BIM-DAS, "
    "matching in situ, suggestions de réemploi créatif et devis comparatifs."
)

if not (f_existant and f_projet):
    st.info(
        "👈 **Démarrer** : chargez vos deux nomenclatures Revit dans la "
        "barre latérale (existant + projet final), puis cliquez sur "
        "« Lancer l'analyse »."
    )
    with st.expander("ℹ Format CSV attendu", expanded=False):
        st.markdown("""
        Les fichiers doivent être des **nomenclatures multicatégorie**
        exportées depuis Revit, avec les colonnes :

        - `Type`
        - `Niveau`
        - `Famille`
        - `Famille et type`
        - `Identifiant`

        Le fichier de l'**existant** peut contenir une colonne `Price`
        supplémentaire (estimation diagnostiqueur), pas le projet final.

        L'application gère automatiquement le BOM UTF-8, les lignes vides,
        et les variations de séparateur (`,` `;` ou `tab`).
        """)
    st.stop()


# --- Si on n'a pas encore lancé, on affiche juste un aperçu rapide ---
if not run_btn and "results" not in st.session_state:
    st.info(
        "📁 Fichiers chargés. Cliquez sur « 🚀 Lancer l'analyse » dans la "
        "barre latérale pour démarrer le traitement."
    )
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Existant chargé :**")
        try:
            df_preview = load_revit_nomenclature(f_existant)
            f_existant.seek(0)  # reset pour réutilisation
            summ = get_dataset_summary(df_preview)
            st.write(f"- {summ['n_elements']} éléments")
            st.write(f"- {summ['n_familles']} familles distinctes")
            st.write(f"- {summ['n_niveaux']} niveaux")
        except Exception as e:
            st.error(f"Erreur de lecture : {e}")
    with col2:
        st.markdown("**Projet chargé :**")
        try:
            df_preview = load_revit_nomenclature(f_projet)
            f_projet.seek(0)
            summ = get_dataset_summary(df_preview)
            st.write(f"- {summ['n_elements']} éléments")
            st.write(f"- {summ['n_familles']} familles distinctes")
            st.write(f"- {summ['n_niveaux']} niveaux")
        except Exception as e:
            st.error(f"Erreur de lecture : {e}")
    st.stop()


# =============================================================================
# Lancement de l'analyse
# =============================================================================

if run_btn:
    with st.spinner("Analyse en cours…"):
        # 1) Lecture
        df_existant = load_revit_nomenclature(f_existant)
        df_projet = load_revit_nomenclature(f_projet)

        # 2) Classification
        df_ex_cl = classify_dataframe(df_existant, drop_excluded=True)
        df_pr_cl = classify_dataframe(df_projet, drop_excluded=True)

        # 3) Hypothèses : on merge les overrides utilisateur
        active_hyp = dict(DEFAULT_BIM_DAS_TABLE)
        if "hyp_overrides" in st.session_state:
            active_hyp.update(st.session_state.hyp_overrides)

        # 4) Ratios
        ratios = GlobalRatios(
            carbone_kgco2_m2=carbone_ref,
            dechets_kg_m2=dechets_ref,
            cout_demolition_eur_m2=cout_demol,
            cout_depose_soignee_eur_m2=cout_depose,
            gain_carbone_pct=gain_carbone,
            gain_dechets_pct=gain_dechets,
            gain_temps_pct=gain_temps,
        )

        # 5) Matching
        mr = match_onsite(df_ex_cl, df_pr_cl)

        # 6) KPIs
        kpis = compute_all_kpis(
            df_existant_classifie=df_ex_cl,
            df_projet_classifie=df_pr_cl,
            surface_m2=surface_m2,
            n_reemployes_in_situ=mr.n_reemployes_in_situ,
            ratios=ratios,
        )

        # 7) Excel
        xlsx_existant = build_xlsx(df_ex_cl,
                                   "SYNTHÈSE — TRI DES ÉLÉMENTS DU BÂTI EXISTANT")
        xlsx_projet = build_xlsx(df_pr_cl,
                                 "SYNTHÈSE — TRI DES ÉLÉMENTS DU PROJET FINAL")

        # 8) Suggestions niveau 1
        suggestions_expert = suggest_creative_uses(mr, df_ex_cl)
        modes_alternatifs = get_alternative_construction_modes(df_ex_cl)

        # 9) Suggestions niveau 2 (LLM) si clé API fournie
        suggestions_llm = []
        llm_error = None
        if api_key and api_key.strip():
            df_demande_externe = mr.df_matching.loc[
                mr.df_matching["A_commander_externe"] > 0
            ]
            suggestions_llm, llm_error = query_claude_for_suggestions(
                api_key=api_key.strip(),
                df_surplus=mr.df_surplus,
                df_demande_externe=df_demande_externe,
            )

        # 10) Devis
        q_achat = quote_achat_reemploi(mr)
        q_achat_sum = quote_achat_reemploi_summary(q_achat)
        q_revente = quote_revente(mr)
        q_revente_sum = quote_revente_summary(q_revente)
        q_recyclage = quote_recyclage(df_ex_cl, active_hyp)
        q_recyclage_sum = quote_recyclage_summary(q_recyclage)
        q_dechets = quote_dechets_ultimes(df_ex_cl, active_hyp)

        # On stocke tout en session pour ne pas tout recalculer
        st.session_state.results = {
            "df_ex_cl": df_ex_cl,
            "df_pr_cl": df_pr_cl,
            "kpis": kpis,
            "matching": mr,
            "xlsx_existant": xlsx_existant,
            "xlsx_projet": xlsx_projet,
            "suggestions_expert": suggestions_expert,
            "modes_alternatifs": modes_alternatifs,
            "suggestions_llm": suggestions_llm,
            "llm_error": llm_error,
            "q_achat": q_achat,
            "q_achat_sum": q_achat_sum,
            "q_revente": q_revente,
            "q_revente_sum": q_revente_sum,
            "q_recyclage": q_recyclage,
            "q_recyclage_sum": q_recyclage_sum,
            "q_dechets": q_dechets,
        }


# =============================================================================
# Affichage des résultats
# =============================================================================

if "results" not in st.session_state:
    st.stop()

R = st.session_state.results
kpis = R["kpis"]
mr = R["matching"]

# Tabs principaux
tab_kpi, tab_excel, tab_match, tab_sugg, tab_devis, tab_das = st.tabs([
    "📊 Tableau de bord",
    "📁 Tri PEMD",
    "🔄 Matching in situ",
    "💡 Suggestions créatives",
    "💰 Devis comparatifs",
    "🎯 BIM-DAS détaillé",
])


# --- Onglet 1 : Tableau de bord ---
with tab_kpi:
    st.markdown("### 5 indicateurs clés — avant/après optimisation circulaire")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        kpi_card(
            "♻ Volume déchets",
            after=f"{kpis.dechets_apres_t:.0f} t",
            before=f"{kpis.dechets_avant_t:.0f} t",
            gain=f"−{kpis.gain_dechets_t:.0f} t évités",
        )
    with col2:
        kpi_card(
            "🌱 Empreinte carbone",
            after=f"{kpis.carbone_apres_kg/1000:.0f} t CO₂e",
            before=f"{kpis.carbone_avant_kg/1000:.0f} t CO₂e",
            gain=f"−{kpis.gain_carbone_kg/1000:.0f} t CO₂e évités",
        )
    with col3:
        kpi_card(
            "🎯 Score BIM-DAS",
            after=f"{kpis.bim_das:.1f} / 100",
            gain="Projet final déconstructible",
            neutral=True,
        )
    with col4:
        kpi_card(
            "💰 Coût total",
            after=fmt_eur(kpis.cout_apres_eur),
            before=fmt_eur(kpis.cout_avant_eur),
            gain=f"−{fmt_eur(kpis.gain_cout_eur)} économisés",
        )
    with col5:
        kpi_card(
            "⏱ Durée chantier",
            after=f"{kpis.duree_apres_j:.0f} j",
            before=f"{kpis.duree_avant_j:.0f} j",
            gain=f"−{kpis.gain_duree_j:.0f} j gagnés",
        )

    st.divider()

    st.markdown("### Composition du gisement")
    summ_ex = summarize_classification(R["df_ex_cl"])
    summ_pr = summarize_classification(R["df_pr_cl"])

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Bâti existant (PEMD)**")
        df_breakdown = pd.DataFrame({
            "Catégorie": ["♻ Réemploi", "🔄 Recyclage", "🗑 Autres déchets"],
            "Nombre": [summ_ex.n_reemploi, summ_ex.n_recyclage, summ_ex.n_dechets],
            "Proportion": [
                f"{summ_ex.pct_reemploi:.1f} %",
                f"{summ_ex.pct_recyclage:.1f} %",
                f"{summ_ex.pct_dechets:.1f} %",
            ],
        })
        st.dataframe(df_breakdown, use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**Projet final (PRO)**")
        df_breakdown_pr = pd.DataFrame({
            "Catégorie": ["♻ Réemploi", "🔄 Recyclage", "🗑 Autres déchets"],
            "Nombre": [summ_pr.n_reemploi, summ_pr.n_recyclage, summ_pr.n_dechets],
            "Proportion": [
                f"{summ_pr.pct_reemploi:.1f} %",
                f"{summ_pr.pct_recyclage:.1f} %",
                f"{summ_pr.pct_dechets:.1f} %",
            ],
        })
        st.dataframe(df_breakdown_pr, use_container_width=True, hide_index=True)

    st.divider()
    st.caption(
        f"_Surface chantier : {kpis.surface_m2:,.0f} m²".replace(",", " ")
        + f" • Masse existant : {kpis.masse_existant_t:.0f} t  • "
        f"Réemploi in situ : {mr.n_reemployes_in_situ} éléments_"
    )


# --- Onglet 2 : Tri PEMD (téléchargement Excel) ---
with tab_excel:
    st.markdown("### Téléchargement des nomenclatures triées")
    st.caption(
        "Deux fichiers Excel, un pour chaque nomenclature, avec une feuille "
        "de synthèse et trois feuilles détaillées colorées par catégorie."
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Tri du bâti existant")
        st.write(
            f"{summarize_classification(R['df_ex_cl']).total} éléments classés "
            "selon leur trajectoire de fin de vie."
        )
        st.download_button(
            "📥 Télécharger Tri_Existant.xlsx",
            data=R["xlsx_existant"],
            file_name="Tri_Existant.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    with col2:
        st.markdown("#### Tri du projet final")
        st.write(
            f"{summarize_classification(R['df_pr_cl']).total} éléments classés "
            "pour la conception circulaire du projet."
        )
        st.download_button(
            "📥 Télécharger Tri_Projet.xlsx",
            data=R["xlsx_projet"],
            file_name="Tri_Projet.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

    st.divider()
    st.markdown("#### Aperçu — onglet « ♻ Réemploi » du fichier existant")
    df_re = R["df_ex_cl"][R["df_ex_cl"]["Categorie"] == "Reemploi"]
    st.dataframe(
        df_re[["Famille", "Famille et type", "Type", "Niveau"]].head(20),
        use_container_width=True, hide_index=True,
    )


# --- Onglet 3 : Matching in situ ---
with tab_match:
    st.markdown("### Matching in situ — gisement existant ↔ besoins projet")

    col1, col2, col3 = st.columns(3)
    with col1:
        kpi_card("Réemploi in situ exact",
                 f"{mr.n_reemployes_in_situ}",
                 gain="éléments à reposer sur place",
                 neutral=True)
    with col2:
        kpi_card("À approvisionner externe",
                 f"{mr.n_a_acheter_externe}",
                 gain="à commander en filière réemploi",
                 neutral=True)
    with col3:
        kpi_card("Surplus à revendre",
                 f"{mr.n_surplus_revente}",
                 gain="à valoriser via marketplace",
                 neutral=True)

    st.divider()

    st.markdown("#### Détail des besoins du projet")
    st.caption(
        "Pour chaque type Revit demandé par le projet final, on vérifie si "
        "le gisement de l'existant en contient. Le matching est exact "
        "(même famille et même type)."
    )
    st.dataframe(mr.df_matching, use_container_width=True, hide_index=True)

    if len(mr.df_surplus):
        st.divider()
        st.markdown("#### Surplus de l'existant à valoriser")
        st.caption(
            "Éléments réemployables présents dans l'existant mais non "
            "demandés à l'identique par le projet → à revendre via "
            "Backacia / CycleUp Marketplace OU à transformer (voir "
            "« 💡 Suggestions créatives »)."
        )
        st.dataframe(mr.df_surplus, use_container_width=True, hide_index=True)


# --- Onglet 4 : Suggestions créatives ---
with tab_sugg:
    st.markdown("### Suggestions de réemploi créatif")
    st.caption(
        "Le système expert propose pour chaque famille en surplus des usages "
        "alternatifs validés (système expert) ; si vous fournissez une clé "
        "API Anthropic, Claude Haiku enrichit ces suggestions avec des idées "
        "complémentaires contextuelles."
    )

    expert = R["suggestions_expert"]
    if expert:
        st.markdown(f"#### 🛠 Système expert — {len(expert)} suggestions")
        for s in expert:
            with st.container(border=True):
                st.markdown(
                    f"**{s.icone} {s.source_famille}**  "
                    f"<span style='color:#607D8B'>· {s.quantite_disponible} unités</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"→ **{s.usage_cible}**")
                st.caption(s.description)
    else:
        st.info("Aucune suggestion : le matching est complet ou le gisement vide.")

    st.divider()

    st.markdown("#### 🏗 Modes constructifs alternatifs proposés")
    for m in R["modes_alternatifs"]:
        with st.container(border=True):
            st.markdown(f"**{m['icone']} {m['titre']}**")
            st.caption(m["description"])
            st.caption(f"_Condition : {m['condition']}_")

    st.divider()

    if R["suggestions_llm"]:
        st.markdown(f"#### 🤖 Suggestions enrichies par IA — {len(R['suggestions_llm'])} idées")
        for s in R["suggestions_llm"]:
            with st.container(border=True):
                st.markdown(
                    f"**🤖 {s.get('source_famille', 'Suggestion')}** "
                    f"→ **{s.get('usage_cible', '')}**"
                )
                st.caption(s.get("description", ""))
    elif R["llm_error"]:
        st.warning(f"⚠ Suggestions IA non disponibles : {R['llm_error']}")
    else:
        st.info(
            "💡 Astuce : fournissez une clé API Anthropic dans la sidebar "
            "(« 🤖 Suggestions enrichies par IA ») pour obtenir 5 idées "
            "supplémentaires générées par Claude Haiku."
        )


# --- Onglet 5 : Devis comparatifs ---
with tab_devis:
    st.markdown("### Devis comparatifs sur les soldes après matching in situ")
    st.caption(
        "Tous les prix sont des **estimations indicatives** issues de "
        "barèmes publics (ADEME, FFB, CycleUp 2024, Valobat, Paprec). "
        "À recouper systématiquement avec un devis ferme."
    )

    sub_a, sub_r, sub_rec, sub_d = st.tabs([
        "🛒 Achat réemploi externe",
        "💵 Revente surplus",
        "🔄 Recyclage matière",
        "🗑 Déchets ultimes",
    ])

    with sub_a:
        st.markdown("#### Achat externe pour combler les besoins du projet")
        st.write(f"**{mr.n_a_acheter_externe} éléments** à approvisionner.")
        if len(R["q_achat_sum"]):
            col1, col2 = st.columns([2, 3])
            with col1:
                st.markdown("**Synthèse fournisseurs**")
                st.dataframe(R["q_achat_sum"], use_container_width=True,
                             hide_index=True)
            with col2:
                st.markdown(analyze_best_supplier(
                    R["q_achat_sum"], "Total med (€)", "minimize"
                ))
            with st.expander("📋 Détail ligne par ligne"):
                st.dataframe(R["q_achat"], use_container_width=True,
                             hide_index=True)
        else:
            st.info("Aucun achat externe nécessaire (tous besoins couverts).")

    with sub_r:
        st.markdown("#### Revente du surplus du gisement")
        st.write(f"**{mr.n_surplus_revente} éléments** disponibles à la revente.")
        if len(R["q_revente_sum"]):
            col1, col2 = st.columns([2, 3])
            with col1:
                st.markdown("**Synthèse plateformes**")
                st.dataframe(R["q_revente_sum"], use_container_width=True,
                             hide_index=True)
            with col2:
                st.markdown(analyze_best_supplier(
                    R["q_revente_sum"], "Recette tot. med (€)", "maximize"
                ))
            with st.expander("📋 Détail ligne par ligne"):
                st.dataframe(R["q_revente"], use_container_width=True,
                             hide_index=True)
        else:
            st.info("Aucun surplus identifié.")

    with sub_rec:
        st.markdown("#### Recyclage matière — éléments classés Recyclage")
        if len(R["q_recyclage_sum"]):
            col1, col2 = st.columns([2, 3])
            with col1:
                st.markdown("**Synthèse filières**")
                st.dataframe(R["q_recyclage_sum"], use_container_width=True,
                             hide_index=True)
            with col2:
                st.markdown(analyze_best_supplier(
                    R["q_recyclage_sum"], "Coût med (€)", "minimize"
                ))
            with st.expander("📋 Détail par matière"):
                st.dataframe(R["q_recyclage"], use_container_width=True,
                             hide_index=True)
        else:
            st.info("Aucun élément à recycler.")

    with sub_d:
        st.markdown("#### Déchets ultimes — éléments classés Autres déchets")
        if len(R["q_dechets"]):
            col1, col2 = st.columns([2, 3])
            with col1:
                st.dataframe(R["q_dechets"], use_container_width=True,
                             hide_index=True)
            with col2:
                st.markdown(analyze_best_supplier(
                    R["q_dechets"], "Coût med (€)", "minimize"
                ))
        else:
            st.info("Aucun déchet ultime — bravo !")

    # Bilan financier global
    st.divider()
    st.markdown("#### 💼 Bilan financier circulaire (estimation médiane)")
    total_achat = R["q_achat_sum"]["Total med (€)"].min() if len(R["q_achat_sum"]) else 0
    total_revente = R["q_revente_sum"]["Recette tot. med (€)"].max() if len(R["q_revente_sum"]) else 0
    total_recyclage = R["q_recyclage_sum"]["Coût med (€)"].min() if len(R["q_recyclage_sum"]) else 0
    total_dechets = R["q_dechets"]["Coût med (€)"].min() if len(R["q_dechets"]) else 0
    bilan_net = total_achat + total_recyclage + total_dechets - total_revente

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Achat réemploi", fmt_eur(total_achat))
    with col2:
        st.metric("Revente surplus", fmt_eur(-total_revente),
                  delta="recette", delta_color="inverse")
    with col3:
        st.metric("Recyclage matière", fmt_eur(total_recyclage))
    with col4:
        st.metric("Déchets ultimes", fmt_eur(total_dechets))
    with col5:
        st.metric("**Bilan net**", fmt_eur(bilan_net),
                  delta="vs démolition standard")
    st.caption(
        "_Bilan optimisé en choisissant le fournisseur le moins coûteux par "
        "poste et la plateforme la plus rémunératrice pour la revente._"
    )


# --- Onglet 6 : BIM-DAS détaillé ---
with tab_das:
    st.markdown("### Score BIM-DAS — analyse détaillée")
    st.caption(
        "Le BIM-DAS (Building Information Modeling — Deconstructability "
        "Assessment Score) suit la formulation d'Akinade et al. (2015). "
        "Il évalue le potentiel de déconstruction et de récupération du "
        "projet final."
    )

    das = kpis.bim_das_detail

    col1, col2, col3 = st.columns(3)
    with col1:
        kpi_card("D-score (déconstruction)",
                 f"{das.dscore:.3f}",
                 gain="moyenne tn / dc / RP",
                 neutral=True)
    with col2:
        kpi_card("R-score (récupération)",
                 f"{das.rscore:.3f}",
                 gain="moyenne R1 / R2 / Rs / Rx",
                 neutral=True)
    with col3:
        kpi_card("★ BIM-DAS global",
                 f"{das.das_pct:.1f} / 100",
                 gain="0.5 × D + 0.5 × R",
                 neutral=True)

    st.divider()

    st.markdown("#### Décomposition par composante")
    df_breakdown = pd.DataFrame(das.as_breakdown_dict())
    st.dataframe(df_breakdown, use_container_width=True, hide_index=True)

    with st.expander("ℹ Glossaire des composantes"):
        st.markdown("""
        - **tn** : diversité matériaux = `1 - t/n`. Plus la diversité est
          réduite, plus la déconstruction et le tri sont efficaces.
        - **dc** : ratio de connexions démontables (boulonnées, vissées,
          clipsées) sur le total. 1.0 = entièrement déboulonnable, 0.0 =
          entièrement coulé/soudé.
        - **RP** : ratio de préfabrication (part hors-site).
        - **R1** : potentiel de réemploi (réutilisation telle quelle).
        - **R2** : potentiel de recyclage matière.
        - **Rs** : absence de finitions secondaires (peinture, enduit
          collé) qui contaminent le tri.
        - **Rx** : non-toxicité (absence d'amiante, plomb, PCB).

        > Source : Akinade O.O. et al. (2015), _A BIM-based deconstruction
        > assessment for sustainable design_, Resources, Conservation and
        > Recycling.
        """)

    st.divider()
    st.markdown(f"_Calcul effectué sur **{das.n_elements} éléments** "
                f"répartis en **{das.n_familles} familles**._")
