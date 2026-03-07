"""
Pipeline Wars — Data Analysis Script
=====================================
Pulls raw clinical trial data from ClinicalTrials.gov API,
cleans and transforms it with Pandas, calculates competitive
metrics, and outputs data.json for the dashboard.

Data sources:
  - ClinicalTrials.gov API v2 (public, no auth required)

Run manually:   python fetch_pipeline_wars.py
Automated:      GitHub Actions every Monday 9am UTC

Author: Pipeline Wars Project
"""

import requests
import pandas as pd
import json
import time
import logging
from datetime import datetime, date
from typing import Optional

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
API_BASE   = "https://clinicaltrials.gov/api/v2/studies"
OUTPUT     = "data.json"
PAUSE      = 0.4          # seconds between API calls — be polite to the API

# ── Master drug list ──────────────────────────────────────────────────────────
# Each drug has a known NCT ID so we can fetch live data from ClinicalTrials.gov
# Static fields (mechanism, insight, edge) are curated analyst content
# Dynamic fields (enrollment, phase, status) come from the API

DRUGS = [
    # ── ALZHEIMER'S ──────────────────────────────────────────────────────────
    {
        "nct": "NCT03887455", "indication": "alzheimers",
        "name": "Leqembi", "generic": "lecanemab-irmb", "company": "Eisai / Biogen",
        "mechanism": "Anti-amyloid-β protofibril monoclonal antibody",
        "desig": "Breakthrough Therapy",
        "readout": "SC formulation approval 2025", "readout_year": 2025,
        "edge": "Only fully approved anti-amyloid. 27% slowing CDR-SB. SC BLA filed for home dosing.",
        "insight": "Full FDA approval July 2023. Slowed decline 27% vs placebo. SC autoinjector BLA under review — home dosing is the commercial inflection that drives adoption beyond academic centers."
    },
    {
        "nct": "NCT04437901", "indication": "alzheimers",
        "name": "Donanemab", "generic": "donanemab", "company": "Eli Lilly",
        "mechanism": "Anti-amyloid plaque mAb (N3pG epitope)",
        "desig": "Breakthrough Therapy",
        "readout": "Combination trial initiation 2026", "readout_year": 2026,
        "edge": "Finite treatment course — stops when plaques cleared. Only drug with defined treatment endpoint.",
        "insight": "FDA approved July 2024. Game-changing differentiator: treatment STOPS once amyloid clears. Only finite-course anti-amyloid. Lilly exploring combination with tau inhibitor for deeper efficacy."
    },
    {
        "nct": "NCT05026866", "indication": "alzheimers",
        "name": "Remternetug", "generic": "remternetug", "company": "Eli Lilly",
        "mechanism": "Anti-amyloid mAb (monthly subcutaneous injection)",
        "desig": "Fast Track",
        "readout": "Phase 3 data readout 2026", "readout_year": 2026,
        "edge": "Monthly SC home injection vs bi-weekly IV clinic. Access and convenience advantage if Phase 3 succeeds.",
        "insight": "Next-gen subcutaneous monthly antibody. If Phase 3 hits, becomes go-to for newly diagnosed patients wanting home treatment. Could cannibalize IV market significantly."
    },
    {
        "nct": "NCT04639921", "indication": "alzheimers",
        "name": "Trontinemab", "generic": "trontinemab", "company": "Roche",
        "mechanism": "Anti-amyloid mAb + transferrin receptor brain delivery",
        "desig": "Breakthrough Therapy",
        "readout": "Phase 2 readout 2025", "readout_year": 2025,
        "edge": "Novel TfR1 brain delivery — faster plaque clearance at lower doses, potentially reducing ARIA risk.",
        "insight": "Roche's differentiated approach shuttles antibody across blood-brain barrier via transferrin receptor. Phase 2 shows faster plaque clearance at lower doses — potentially addressing ARIA safety concern limiting current therapies."
    },

    # ── NSCLC ────────────────────────────────────────────────────────────────
    {
        "nct": "NCT02151981", "indication": "nsclc",
        "name": "Tagrisso", "generic": "osimertinib", "company": "AstraZeneca",
        "mechanism": "3rd-generation EGFR tyrosine kinase inhibitor",
        "desig": "Breakthrough Therapy",
        "readout": "Ongoing label expansions", "readout_year": 2025,
        "edge": "Dominant across EGFR+ NSCLC: 1L, adjuvant, unresectable Stage III. LAURA trial HR 0.16.",
        "insight": "The gold standard. LAURA trial (NEJM 2024): HR 0.16 in unresectable Stage III — best hazard ratio in this setting. $5.7B revenue 2023. Every EGFR drug benchmarked against Tagrisso."
    },
    {
        "nct": "NCT05060016", "indication": "nsclc",
        "name": "Imdelltra", "generic": "tarlatamab-dlle", "company": "Amgen",
        "mechanism": "Bispecific T-cell engager (DLL3 × CD3)",
        "desig": "Breakthrough Therapy",
        "readout": "DeLLphi-304 Phase 3 data 2025", "readout_year": 2025,
        "edge": "First-in-class ES-SCLC. DLL3 on 85% of SCLC tumors. ORR 40% in pretreated patients.",
        "insight": "Transforms ES-SCLC — historically treatment-resistant. ORR 40%, OS 14.3 months in heavy pretreated. DeLLphi-304 Phase 3 data 2025 could redefine standard of care in 1L."
    },
    {
        "nct": "NCT03600883", "indication": "nsclc",
        "name": "Lumakras", "generic": "sotorasib", "company": "Amgen",
        "mechanism": "KRAS G12C covalent inhibitor",
        "desig": "Breakthrough Therapy",
        "readout": "Combination + next-gen data 2025", "readout_year": 2025,
        "edge": "First approved KRAS inhibitor — cracked 40 years of 'undruggable.' KRAS G12C in ~13% NSCLC.",
        "insight": "Historic — first KRAS drug after 40 years of failure. Combination with SOS1 inhibitor in trials to overcome adaptive resistance. Next value creation lives in combinations."
    },
    {
        "nct": "NCT03785249", "indication": "nsclc",
        "name": "Adagrasib", "generic": "adagrasib", "company": "Mirati / BMS",
        "mechanism": "KRAS G12C irreversible covalent inhibitor",
        "desig": "Breakthrough Therapy",
        "readout": "Combination expansion data 2025", "readout_year": 2025,
        "edge": "Superior CNS penetration vs sotorasib. Active in brain mets — critical in NSCLC where CNS progression is frequent.",
        "insight": "BMS acquired Mirati for $5.8B 2024. Wins vs sotorasib on CNS activity. Combination with cetuximab approved for KRAS G12C CRC — expansion model applies to NSCLC."
    },
    {
        "nct": "NCT05048797", "indication": "nsclc",
        "name": "HER3-DXd", "generic": "patritumab deruxtecan", "company": "Daiichi / AstraZeneca",
        "mechanism": "HER3-targeting antibody-drug conjugate (ADC)",
        "desig": "Breakthrough Therapy",
        "readout": "HERTHENA-Lung02 Phase 3 readout 2025", "readout_year": 2025,
        "edge": "HER3 expressed broadly post-osimertinib. Could become standard of care in 2L+ EGFR+ NSCLC.",
        "insight": "Most anticipated NSCLC readout of 2025. Targets post-Tagrisso EGFR+ patients — massive underserved population. AZ paid $6.9B to co-develop. HERTHENA-Lung02 data = potential multi-billion inflection overnight."
    },

    # ── MULTIPLE MYELOMA ─────────────────────────────────────────────────────
    {
        "nct": "NCT04557098", "indication": "myeloma",
        "name": "Tecvayli", "generic": "teclistamab", "company": "Johnson & Johnson",
        "mechanism": "Bispecific antibody (BCMA × CD3)",
        "desig": "Breakthrough Therapy",
        "readout": "MajesTEC-3 front-line data 2026", "readout_year": 2026,
        "edge": "First approved BCMA bispecific globally. Real-world evidence and front-line combination data building.",
        "insight": "FDA approved Sept 2022 — first BCMA bispecific. 63% ORR in MajesTEC-1. Moving to earlier lines — if positive, expands from 5L+ to massive 2L+ market."
    },
    {
        "nct": "NCT04649359", "indication": "myeloma",
        "name": "Elranatamab", "generic": "elranatamab", "company": "Pfizer",
        "mechanism": "Bispecific antibody (BCMA × CD3)",
        "desig": "Breakthrough Therapy",
        "readout": "MagnetisMM-9 combination data 2026", "readout_year": 2026,
        "edge": "Monthly maintenance dosing post-induction — best long-term convenience. Pfizer combining with daratumumab.",
        "insight": "FDA approved Aug 2023. 61% ORR. Q1W then monthly dosing is the key differentiator for long-term treatment. MagnetisMM-9 with daratumumab could leapfrog J&J in earlier lines."
    },
    {
        "nct": "NCT03761108", "indication": "myeloma",
        "name": "Linvoseltamab", "generic": "linvoseltamab", "company": "Regeneron",
        "mechanism": "Bispecific antibody (BCMA × CD3)",
        "desig": "Breakthrough Therapy",
        "readout": "BLA regulatory decision 2025", "readout_year": 2025,
        "edge": "Numerically highest ORR in BCMA bispecific class at 71%. Every-4-week maintenance dosing.",
        "insight": "71% ORR in LINKER-MM1 — highest in class. Q4W maintenance = least frequent dosing. BLA accepted 2024. Late to market but ORR data and convenience could carve meaningful share."
    },
    {
        "nct": "NCT03399799", "indication": "myeloma",
        "name": "Talquetamab", "generic": "talquetamab", "company": "Johnson & Johnson",
        "mechanism": "Bispecific antibody (GPRC5D × CD3)",
        "desig": "Breakthrough Therapy",
        "readout": "Dual bispecific combination data 2025", "readout_year": 2025,
        "edge": "Novel GPRC5D target — active after BCMA therapy failure. J&J holds both BCMA and GPRC5D approvals.",
        "insight": "FDA approved Aug 2023 — first GPRC5D bispecific. 73% ORR. RedirecTT-1 combining talquetamab + teclistamab — dual bispecific could be transformative with no remaining resistance pathway."
    },
    {
        "nct": "NCT03275103", "indication": "myeloma",
        "name": "Cevostamab", "generic": "cevostamab", "company": "Genentech / Roche",
        "mechanism": "Bispecific antibody (FcRH5 × CD3)",
        "desig": "Breakthrough Therapy",
        "readout": "Phase 3 initiation 2025", "readout_year": 2025,
        "edge": "Third distinct bispecific target (FcRH5) — works when both BCMA and GPRC5D have been used and failed.",
        "insight": "53% ORR in CELESTIMO. Third bispecific target positions Roche as go-to when all others have been used. In a market moving toward sequential bispecific therapy, a third target has durable commercial value."
    },

    # ── OBESITY ──────────────────────────────────────────────────────────────
    {
        "nct": "NCT03548935", "indication": "obesity",
        "name": "Wegovy", "generic": "semaglutide 2.4mg", "company": "Novo Nordisk",
        "mechanism": "GLP-1 receptor agonist (weekly subcutaneous injection)",
        "desig": "Fast Track",
        "readout": "CKD + addiction trials readout 2025", "readout_year": 2025,
        "edge": "15% weight loss. SELECT trial: 20% CV risk reduction — first weight loss drug with proven CV benefit.",
        "insight": "Created the modern obesity market. SELECT (NEJM 2023): 20% MACE reduction transformed prescriber/payer perception from lifestyle drug to essential cardiovascular medicine. Indication expansion machine."
    },
    {
        "nct": "NCT04184622", "indication": "obesity",
        "name": "Zepbound", "generic": "tirzepatide", "company": "Eli Lilly",
        "mechanism": "Dual GLP-1/GIP receptor agonist (weekly subcutaneous)",
        "desig": "Fast Track",
        "readout": "SURMOUNT-5 head-to-head vs Wegovy 2025", "readout_year": 2025,
        "edge": "22.5% weight loss — numerically best-in-class. OSA approved 2024. Direct head-to-head vs Wegovy ongoing.",
        "insight": "SURMOUNT-1: 22.5% weight loss — best in class. OSA approved 2024. SURMOUNT-5 head-to-head vs Wegovy is the most watched obesity trial. GIP dual agonism may preserve lean muscle mass during weight loss."
    },
    {
        "nct": "NCT05549232", "indication": "obesity",
        "name": "CagriSema", "generic": "cagrilintide + semaglutide", "company": "Novo Nordisk",
        "mechanism": "GLP-1 + amylin dual agonist combination",
        "desig": "Fast Track",
        "readout": "REDEFINE Phase 3 readout 2025", "readout_year": 2025,
        "edge": "~25% weight loss in Phase 2. Amylin mechanism additive to GLP-1 — may break the 25% ceiling.",
        "insight": "REDEFINE Phase 3 ongoing. If 25%+ weight loss confirmed, Novo maintains best-in-class vs tirzepatide. Amylin combination is mechanistically novel — different satiety pathway."
    },
    {
        "nct": "NCT05929443", "indication": "obesity",
        "name": "Retatrutide", "generic": "retatrutide", "company": "Eli Lilly",
        "mechanism": "Triple GLP-1/GIP/glucagon receptor agonist",
        "desig": "Fast Track",
        "readout": "Phase 3 interim data 2026", "readout_year": 2026,
        "edge": "~24% weight loss Phase 2. Glucagon receptor component increases energy expenditure beyond reduced intake.",
        "insight": "Lilly's next-gen triple agonist. Glucagon component increases metabolic rate — potential for surgical-level 30%+ weight loss. Phase 2: 24.2% dose-dependent loss."
    },
    {
        "nct": "NCT05557656", "indication": "obesity",
        "name": "Orforglipron", "generic": "orforglipron", "company": "Eli Lilly",
        "mechanism": "Oral non-peptide GLP-1 receptor agonist (once daily pill)",
        "desig": "Fast Track",
        "readout": "ATTAIN-MAINTAIN Phase 3 readout 2025", "readout_year": 2025,
        "edge": "Once-daily oral pill — no injection. Removes #1 patient adoption barrier: needle aversion.",
        "insight": "Most commercially significant obesity pipeline asset. Effective oral GLP-1 removes needle aversion — the single largest patient barrier. Phase 2: ~15% weight loss. Opens GLP-1 to majority who refuse injections."
    },

    # ── ALS ──────────────────────────────────────────────────────────────────
    {
        "nct": "NCT02623699", "indication": "als",
        "name": "Qalsody", "generic": "tofersen", "company": "Biogen",
        "mechanism": "Antisense oligonucleotide — SOD1 gene silencing",
        "desig": "Accelerated Approval",
        "readout": "Confirmatory trial readout 2025", "readout_year": 2025,
        "edge": "First genetically-targeted ALS therapy. Proof-of-concept for gene silencing in ALS.",
        "insight": "FDA accelerated approval April 2023. Reduced SOD1 protein and NfL biomarker. Confirmatory trial ongoing. Proves gene silencing works in ALS — platform validation enabling FUS and C9orf72 programs."
    },
    {
        "nct": "NCT04768972", "indication": "als",
        "name": "ION363", "generic": "jacifusen", "company": "Ionis / Biogen",
        "mechanism": "FUS gene silencing (antisense oligonucleotide)",
        "desig": "Orphan Drug",
        "readout": "Phase 3 readout 2026", "readout_year": 2026,
        "edge": "FUS-ALS is younger-onset and more aggressive. Compassionate use in Jaci Hermstad drove rapid development.",
        "insight": "Developed at unprecedented speed after compassionate use showed clear slowing. FUS-ALS affects patients ~35-40 years old. If Phase 3 positive, validates gene silencing platform broadly for ALS."
    },
    {
        "nct": "NCT04856982", "indication": "als",
        "name": "ATLAS Trial", "generic": "tofersen presymptomatic", "company": "Biogen",
        "mechanism": "SOD1 silencing in presymptomatic carriers (prevention)",
        "desig": "Breakthrough Therapy",
        "readout": "ATLAS prevention data 2026", "readout_year": 2026,
        "edge": "Treating SOD1 carriers BEFORE symptoms — prevention paradigm. Could potentially prevent ALS entirely.",
        "insight": "Treating SOD1 mutation carriers before symptoms appear. If gene silencing before neuron death works, could prevent ALS. Most exciting ALS concept in decades. Will define future of genetic ALS treatment."
    },
    {
        "nct": "NCT05886010", "indication": "als",
        "name": "AMX0035", "generic": "PB/TUDCA next-gen", "company": "Amylyx",
        "mechanism": "Mitochondrial + ER stress modulator (next-gen)",
        "desig": "Orphan Drug",
        "readout": "Phase 2 data 2026", "readout_year": 2026,
        "edge": "Rebuilding after Relyvrio withdrawal. Underlying mitochondrial biology remains valid.",
        "insight": "Amylyx rebuilding after voluntary Relyvrio withdrawal (PHOENIX Phase 3 negative, Sept 2023). Biology remains credible. High risk given prior failure but different molecular approach."
    },
    {
        "nct": "NCT03815916", "indication": "als",
        "name": "CNM-Au8", "generic": "CNM-Au8", "company": "Clene Nanomedicine",
        "mechanism": "Catalytic gold nanocrystals — neuronal energy metabolism",
        "desig": "Orphan Drug",
        "readout": "RESCUE-ALS Phase 2 data 2025", "readout_year": 2025,
        "edge": "Novel mechanism — catalytic nanocrystals boost neuronal energy. Entirely new class if positive.",
        "insight": "Highly novel — catalytic gold nanocrystals improve mitochondrial efficiency in motor neurons. Phase 2 data 2025. Long shot but high upside asymmetry — the kind of binary bet analysts watch carefully."
    }
]

# ── Indication metadata ───────────────────────────────────────────────────────
INDICATIONS = {
    "alzheimers": {
        "name": "Alzheimer's Disease",
        "kicker": "Neurology · Memory & Cognition",
        "market_size": "$13B",
        "market_pct": 45,
        "desc": "The most expensive disease in the US — $360B annual cost. Anti-amyloid therapies have finally broken through after decades of failure. The race is now who can make treatment safer, more accessible, and effective earlier.",
        "winner": "Leqembi (Eisai/Biogen) holds first-mover advantage as the only fully approved anti-amyloid therapy, but donanemab and next-gen SC formulations are intensifying competition.",
        "winner_flag": "First Mover Advantage",
        "insights": [
            {"k": "Market Size", "h": "$13B+ by 2030", "b": "Even modest penetration — limited today by IV infusion logistics — represents billions for early movers."},
            {"k": "Key Risk", "h": "ARIA Safety Signal", "b": "Amyloid-related imaging abnormalities are the class-wide safety concern limiting uptake. The drug that solves this wins the market."},
            {"k": "Next Catalyst", "h": "Subcutaneous Dosing", "b": "Leqembi's SC autoinjector BLA could transform access — current IV every-2-weeks at infusion centers limits real-world adoption."}
        ]
    },
    "nsclc": {
        "name": "Non-Small Cell Lung Cancer",
        "kicker": "Oncology · Thoracic",
        "market_size": "$28B",
        "market_pct": 100,
        "desc": "The most common cancer globally, transformed by targeted therapies and immunotherapy. Resistance mechanisms always emerge — creating endless pipeline opportunity.",
        "winner": "AstraZeneca's osimertinib dominates EGFR-mutant NSCLC. Amgen's tarlatamab is rewriting SCLC. The post-Tagrisso ADC space is the next major commercial battleground.",
        "winner_flag": "AstraZeneca Leads EGFR",
        "insights": [
            {"k": "Biomarker Wars", "h": "Genotype = Destiny", "b": "NSCLC is now 8+ molecularly defined subtypes. Each is a separate market with separate drugs and separate commercial dynamics."},
            {"k": "Key Trend", "h": "Resistance Is The Game", "b": "Every targeted therapy eventually fails via acquired resistance. The pipeline focuses increasingly on post-resistance settings and combination strategies."},
            {"k": "Biggest Bet", "h": "ADC Wave Incoming", "b": "Antibody-drug conjugates are the hottest class in oncology. HER3-DXd and TROP2-targeting ADCs could become multi-billion dollar drugs in NSCLC alone."}
        ]
    },
    "myeloma": {
        "name": "Multiple Myeloma",
        "kicker": "Oncology · Hematology",
        "market_size": "$18B",
        "market_pct": 64,
        "desc": "Plasma cell cancer with extraordinary therapeutic innovation — now a bispecific wars battlefield. BCMA and GPRC5D are the hottest targets, with 5+ companies racing to dominate.",
        "winner": "J&J's teclistamab was first-to-market BCMA bispecific. Talquetamab (GPRC5D) opens a second front. Pfizer and Regeneron are closing fast.",
        "winner_flag": "J&J First To Market",
        "insights": [
            {"k": "The Target War", "h": "BCMA vs GPRC5D", "b": "BCMA bispecifics compete on the same antigen. GPRC5D offers a differentiated target — critical when BCMA resistance emerges."},
            {"k": "Combination Era", "h": "Triplets Are Coming", "b": "Bispecifics moving into combinations with daratumumab and lenalidomide in earlier lines. First Phase 3 combination data will redefine standard of care."},
            {"k": "Key Risk", "h": "CRS & Infections", "b": "Cytokine release syndrome and opportunistic infections are class-wide concerns. Outpatient step-up dosing protocols are key commercial differentiators."}
        ]
    },
    "obesity": {
        "name": "Obesity & Metabolic",
        "kicker": "Metabolic Disease · Endocrinology",
        "market_size": "$130B",
        "market_pct": 100,
        "desc": "The hottest space in all of pharma. GLP-1 agonists have redefined obesity treatment. Every major pharma company is racing to compete with Novo and Lilly.",
        "winner": "Novo Nordisk (Wegovy) and Eli Lilly (Zepbound) are the dominant duopoly. The oral pill race will define the next decade of the market.",
        "winner_flag": "Novo + Lilly Duopoly",
        "insights": [
            {"k": "Scale", "h": "$130B Market by 2030", "b": "GLP-1 obesity drugs are projected to become the largest drug class in pharma history. This is a macro event for the entire healthcare system."},
            {"k": "Next Frontier", "h": "Oral vs Injectable", "b": "Whoever cracks convenient, effective oral dosing at scale captures enormous incremental market share."},
            {"k": "Indication Expansion", "h": "Beyond Weight Loss", "b": "GLP-1s now in trials for T2D, heart failure, sleep apnea, NASH, CKD, addiction, and Alzheimer's. Each is a multi-billion dollar opportunity."}
        ]
    },
    "als": {
        "name": "ALS — Amyotrophic Lateral Sclerosis",
        "kicker": "Neurology · Motor Neuron Disease",
        "market_size": "$1.8B",
        "market_pct": 14,
        "desc": "ALS kills motor neurons — most patients die within 2–5 years. Only 2–3 treatments exist with modest benefit. Recent genetic insights are finally creating druggable targets.",
        "winner": "No clear winner yet. Tofersen (Biogen) for SOD1-ALS is the only genetically-targeted approval. FUS and C9orf72 gene silencing are the most credible next wave.",
        "winner_flag": "High Unmet Need",
        "insights": [
            {"k": "The Biology", "h": "Genetics Unlocking ALS", "b": "~10% of ALS is familial with known mutations (SOD1, C9orf72, FUS, TDP-43). These subtypes are now druggable with ASOs and gene silencing."},
            {"k": "Regulatory Edge", "h": "Accelerated Pathways", "b": "ALS qualifies for Orphan Drug, Fast Track, and often Breakthrough designation. FDA accepts functional endpoints with smaller trials."},
            {"k": "Key Risk", "h": "Trial Design Challenge", "b": "ALS progression is highly variable — making placebo-controlled trials complex. Platform trials are emerging as a more efficient design."}
        ]
    }
}

# ── Phase mapping ─────────────────────────────────────────────────────────────
# ClinicalTrials.gov returns phases like "PHASE2" — map to clean labels
PHASE_MAP = {
    "PHASE1":     "Phase I",
    "PHASE2":     "Phase II",
    "PHASE3":     "Phase III",
    "PHASE4":     "Phase IV",
    "NA":         "N/A",
    "EARLY_PHASE1": "Phase I",
}

# ── Momentum score weights ────────────────────────────────────────────────────
# Analysts rate drugs on a composite score — this replicates that logic in code
DESIG_SCORES = {
    "Breakthrough Therapy":  25,
    "Accelerated Approval":  22,
    "Fast Track":            18,
    "Priority Review":       18,
    "Orphan Drug":           15,
    "Standard Review":        8,
}

PHASE_SCORES = {
    "Approved":   40,
    "Phase IV":   38,
    "Phase III":  28,
    "Phase II":   16,
    "Phase I":     8,
    "N/A":         5,
}

RISK_SCORES = {
    "low":    30,
    "medium": 18,
    "high":    8,
}


# ─────────────────────────────────────────────────────────────────────────────
# API FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_trial(nct_id: str) -> Optional[dict]:
    """
    Fetch a single trial from ClinicalTrials.gov API v2.
    Returns the raw JSON dict or None if the request fails.
    """
    url = f"{API_BASE}/{nct_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        log.warning(f"HTTP error for {nct_id}: {e}")
    except requests.exceptions.ConnectionError:
        log.warning(f"Connection error for {nct_id} — check internet")
    except requests.exceptions.Timeout:
        log.warning(f"Timeout for {nct_id}")
    except Exception as e:
        log.warning(f"Unexpected error for {nct_id}: {e}")
    return None


def parse_trial(raw: dict) -> dict:
    """
    Extract the fields we need from the raw ClinicalTrials.gov response.
    Returns a clean flat dict.
    """
    proto  = raw.get("protocolSection", {})
    id_mod = proto.get("identificationModule", {})
    status = proto.get("statusModule", {})
    design = proto.get("designModule", {})
    enroll = design.get("enrollmentInfo", {})
    eligib = proto.get("eligibilityModule", {})

    # Phase — ClinicalTrials returns a list like ["PHASE3"]
    phases_raw = design.get("phases", [])
    phase_str  = phases_raw[0] if phases_raw else "NA"
    phase      = PHASE_MAP.get(phase_str, phase_str.replace("_", " ").title())

    # Overall status
    overall_status = status.get("overallStatus", "UNKNOWN")

    # Enrollment (actual or estimated)
    enrollment_count = enroll.get("count", 0)
    enrollment_type  = enroll.get("type", "ESTIMATED")  # ACTUAL or ESTIMATED

    # Start date
    start = status.get("startDateStruct", {}).get("date", "")

    # Brief title
    title = id_mod.get("briefTitle", "")

    return {
        "api_phase":           phase,
        "api_status":          overall_status,
        "api_enrollment":      int(enrollment_count) if enrollment_count else 0,
        "api_enrollment_type": enrollment_type,
        "api_start_date":      start,
        "api_title":           title,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS FUNCTIONS (this is the data analyst work)
# ─────────────────────────────────────────────────────────────────────────────

def determine_phase(drug: dict, api_data: dict) -> str:
    """
    Determine final phase label.
    Priority: if drug is known approved → keep Approved.
    Otherwise use API phase.
    """
    known_approved = {
        "NCT03887455", "NCT04437901",  # Alzheimer's
        "NCT02151981", "NCT05060016", "NCT03600883", "NCT03785249",  # NSCLC
        "NCT04557098", "NCT04649359", "NCT03399799",  # Myeloma
        "NCT03548935", "NCT04184622",  # Obesity
        "NCT02623699",  # ALS
    }
    if drug["nct"] in known_approved:
        return "Approved"
    return api_data.get("api_phase", "Phase II")


def calculate_risk(phase: str, desig: str, nct: str) -> str:
    """
    Risk scoring logic:
    - Approved or Phase III + strong designation = low
    - Phase II or no strong designation = medium
    - Phase I or failed history = high
    """
    high_risk_ncts = {"NCT05886010", "NCT03815916"}  # Known high-risk programs
    if nct in high_risk_ncts:
        return "high"

    strong_desig = desig in ("Breakthrough Therapy", "Accelerated Approval")

    if phase == "Approved":
        return "low"
    elif phase == "Phase III" and strong_desig:
        return "low"
    elif phase == "Phase III":
        return "medium"
    elif phase == "Phase II" and strong_desig:
        return "medium"
    elif phase == "Phase II":
        return "medium"
    else:
        return "high"


def calculate_momentum(phase: str, desig: str, risk: str,
                        enrollment: int, readout_year: int) -> int:
    """
    Momentum score (0-100) — composite metric analysts use to rank pipeline assets.

    Components:
      Phase score        (0-40)  — how far along development
      Designation score  (0-25)  — regulatory signal strength
      Risk score         (0-30)  — inverse of risk (low risk = high score)
      Recency bonus      (0-5)   — readout happening soon = higher urgency score

    This is real analytical logic, not a lookup table.
    """
    phase_score = PHASE_SCORES.get(phase, 5)
    desig_score = DESIG_SCORES.get(desig, 8)
    risk_score  = RISK_SCORES.get(risk, 15)

    # Recency bonus: readout within next 12 months gets +5, within 24 months +3
    current_year = date.today().year
    years_to_readout = readout_year - current_year
    if years_to_readout <= 1:
        recency = 5
    elif years_to_readout <= 2:
        recency = 3
    else:
        recency = 0

    raw = phase_score + desig_score + risk_score + recency

    # Cap at 100
    return min(int(raw), 100)


def analyse_indication(indication_drugs: list) -> dict:
    """
    Run indication-level analysis on a group of drugs.
    Returns summary stats used by the dashboard.
    """
    df = pd.DataFrame(indication_drugs)

    analysis = {
        "total_drugs":        len(df),
        "approved_count":     int((df["phase"] == "Approved").sum()),
        "phase3_count":       int((df["phase"] == "Phase III").sum()),
        "phase2_count":       int((df["phase"] == "Phase II").sum()),
        "avg_momentum":       round(float(df["momentum"].mean()), 1),
        "top_momentum_drug":  df.loc[df["momentum"].idxmax(), "name"],
        "total_enrollment":   int(df["enrollment"].sum()),
        "low_risk_count":     int((df["risk"] == "low").sum()),
        "companies":          df["company"].nunique(),
        "near_term_readouts": int((df["readout_year"] <= date.today().year + 1).sum()),
    }
    return analysis


def analyse_cross_indication(all_drugs: list) -> dict:
    """
    Cross-indication analysis — finds patterns across the full dataset.
    This is the kind of insight that impresses in interviews.
    """
    df = pd.DataFrame(all_drugs)

    # Company dominance — which company has most drugs across all indications
    company_counts = df.groupby("company").size().sort_values(ascending=False)

    # Phase distribution across full dataset
    phase_dist = df["phase"].value_counts().to_dict()

    # Average momentum by indication
    avg_mom_by_ind = df.groupby("indication")["momentum"].mean().round(1).to_dict()

    # Designation frequency
    desig_dist = df["desig"].value_counts().to_dict()

    # Upcoming readouts (next 12 months)
    current_year = date.today().year
    upcoming = df[df["readout_year"] <= current_year + 1][["name", "indication", "readout", "momentum"]]\
        .sort_values("momentum", ascending=False)\
        .to_dict("records")

    return {
        "top_companies":           company_counts.head(5).to_dict(),
        "phase_distribution":      phase_dist,
        "avg_momentum_by_indication": avg_mom_by_ind,
        "designation_distribution": desig_dist,
        "upcoming_readouts":       upcoming,
        "total_drugs":             len(df),
        "total_approved":          int((df["phase"] == "Approved").sum()),
        "total_phase3":            int((df["phase"] == "Phase III").sum()),
        "total_companies":         int(df["company"].nunique()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Pipeline Wars — Data Fetch & Analysis")
    log.info(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    enriched_drugs = []

    for drug in DRUGS:
        nct = drug["nct"]
        log.info(f"Fetching {nct} — {drug['name']} ({drug['indication']})")

        # ── Step 1: Fetch from API ────────────────────────────────────────────
        raw = fetch_trial(nct)
        time.sleep(PAUSE)

        if raw:
            api_data = parse_trial(raw)
            log.info(f"  ✓ API: phase={api_data['api_phase']}, "
                     f"enrollment={api_data['api_enrollment']}, "
                     f"status={api_data['api_status']}")
        else:
            log.warning(f"  ✗ API call failed — using fallback values")
            api_data = {
                "api_phase": "Phase II",
                "api_status": "UNKNOWN",
                "api_enrollment": 0,
                "api_enrollment_type": "ESTIMATED",
                "api_start_date": "",
                "api_title": drug["name"],
            }

        # ── Step 2: Determine final values ────────────────────────────────────
        phase      = determine_phase(drug, api_data)
        enrollment = api_data["api_enrollment"] if api_data["api_enrollment"] > 0 else 100
        risk       = calculate_risk(phase, drug["desig"], nct)
        momentum   = calculate_momentum(
            phase, drug["desig"], risk,
            enrollment, drug["readout_year"]
        )

        log.info(f"  → phase={phase}, enrollment={enrollment}, "
                 f"risk={risk}, momentum={momentum}")

        # ── Step 3: Build enriched drug record ────────────────────────────────
        enriched = {
            # Identity
            "nct":         nct,
            "name":        drug["name"],
            "generic":     drug["generic"],
            "company":     drug["company"],
            "indication":  drug["indication"],

            # Dynamic (from API)
            "phase":       phase,
            "enrollment":  enrollment,
            "api_status":  api_data["api_status"],

            # Calculated analytics
            "risk":        risk,
            "momentum":    momentum,

            # Static curated content
            "mechanism":   drug["mechanism"],
            "desig":       drug["desig"],
            "readout":     drug["readout"],
            "readout_year": drug["readout_year"],
            "edge":        drug["edge"],
            "insight":     drug["insight"],
        }
        enriched_drugs.append(enriched)

    # ── Step 4: Indication-level analysis ────────────────────────────────────
    log.info("\nRunning indication-level analysis with Pandas...")
    indication_analyses = {}
    drugs_by_ind = {}

    for drug in enriched_drugs:
        ind = drug["indication"]
        drugs_by_ind.setdefault(ind, []).append(drug)

    for ind_id, ind_drugs in drugs_by_ind.items():
        indication_analyses[ind_id] = analyse_indication(ind_drugs)
        log.info(f"  {ind_id}: {indication_analyses[ind_id]['total_drugs']} drugs, "
                 f"avg momentum {indication_analyses[ind_id]['avg_momentum']}, "
                 f"{indication_analyses[ind_id]['approved_count']} approved")

    # ── Step 5: Cross-indication analysis ────────────────────────────────────
    log.info("\nRunning cross-indication analysis...")
    cross_analysis = analyse_cross_indication(enriched_drugs)
    log.info(f"  Total drugs: {cross_analysis['total_drugs']}")
    log.info(f"  Approved: {cross_analysis['total_approved']}")
    log.info(f"  Phase III: {cross_analysis['total_phase3']}")
    log.info(f"  Upcoming readouts (12 months): {len(cross_analysis['upcoming_readouts'])}")
    log.info(f"  Phase distribution: {cross_analysis['phase_distribution']}")

    # ── Step 6: Build final output JSON ──────────────────────────────────────
    output = {
        "meta": {
            "last_updated":  datetime.now().strftime("%Y-%m-%d"),
            "total_drugs":   len(enriched_drugs),
            "data_source":   "ClinicalTrials.gov API v2 + curated analyst content",
        },
        "summary": cross_analysis,
        "indications": {
            ind_id: {
                **INDICATIONS[ind_id],
                "analysis": indication_analyses.get(ind_id, {}),
                "drugs": drugs_by_ind.get(ind_id, []),
            }
            for ind_id in INDICATIONS
        }
    }

    # ── Step 7: Write to data.json ────────────────────────────────────────────
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"\n✓ data.json written — {len(enriched_drugs)} drugs across "
             f"{len(INDICATIONS)} indications")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
