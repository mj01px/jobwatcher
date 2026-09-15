"""Default scoring profile: term groups, weights and penalties (ported from Vaggio).

The profile saved from Settings overrides ``PROFILE``; everything else here
(years of experience penalty, seniority and work mode detection) stays in code.

Rules that apply to every group:

- terms are matched normalized (lowercase, no accents), because that is how the
  job text reaches the engine;
- a hit in the title counts double, it is the most reliable signal;
- one hit per group is enough, so repetition cannot inflate a score.
"""

from __future__ import annotations

import re
from typing import Any

WEIGHT_CORE = 12
WEIGHT_DOMAIN = 10
WEIGHT_LEVEL_MATCH = 10
WEIGHT_ADJACENT = 6
WEIGHT_ACTIVITY = 5
WEIGHT_WORK_MODE = 4

PENALTY_LEVEL_TOO_HIGH = -25
PENALTY_STACK_MISMATCH = -20
PENALTY_AREA_MISMATCH = -15
PENALTY_LEVEL_MID = -8

ScoringProfile = dict[str, dict[str, Any]]

PROFILE: ScoringProfile = {
    # High weight: the core of what the person wants to do.
    "core": {
        "weight": WEIGHT_CORE,
        "terms": ["python", "django", "django rest", "drf", "postgres", "postgresql", "sql"],
    },
    # Medium weight: adjacent stack already in use.
    "adjacent": {
        "weight": WEIGHT_ADJACENT,
        "terms": [
            "java",
            "spring",
            "spring boot",
            "api rest",
            "apis rest",
            "rest api",
            "backend",
            "back-end",
            "back end",
            "docker",
            "typescript",
            "react",
        ],
    },
    # The niche where banking experience is worth the most. Careful when
    # editing: "banco" alone matches "banco de dados" and inflates every back end
    # job. Use terms that only exist in the sector.
    "domain": {
        "weight": WEIGHT_DOMAIN,
        "terms": [
            "fintech",
            "bancario",
            "bancaria",
            "banco digital",
            "setor bancario",
            "instituicao financeira",
            "mercado financeiro",
            "financeiro",
            "financeira",
            "investimento",
            "investimentos",
            "credito",
            "pagamentos",
            "meios de pagamento",
            "seguradora",
            "seguros",
            "cooperativa de credito",
            "erp",
            "conciliacao",
            "antifraude",
            "prevencao a fraude",
            "compliance",
        ],
    },
    # The kind of work described in the job that matches what the person does.
    "activity": {
        "weight": WEIGHT_ACTIVITY,
        "terms": [
            "automacao",
            "automatizar",
            "analise de dados",
            "tratamento de dados",
            "integracao",
            "integracoes",
            "scripts",
            "etl",
            "relatorios",
        ],
    },
    # Compatible level.
    "level_match": {
        "weight": WEIGHT_LEVEL_MATCH,
        "terms": [
            "estagio",
            "estagiario",
            "junior",
            "jr",
            "trainee",
            "aprendiz",
            "primeiro emprego",
            "entry level",
            "programa de formacao",
        ],
    },
    # Work format.
    "work_mode": {
        "weight": WEIGHT_WORK_MODE,
        "terms": ["remoto", "home office", "hibrido", "anywhere"],
    },
    # Penalty: level above reach today. "sr" and "pl" have no dot on purpose,
    # jobs write "Python SR" and "Analista PL". Matching is on word boundaries,
    # so "srv" is not caught.
    "level_too_high": {
        "weight": PENALTY_LEVEL_TOO_HIGH,
        "terms": [
            "senior",
            "sr",
            "sr.",
            "especialista",
            "tech lead",
            "staff",
            "principal",
            "arquiteto",
            "coordenador",
            "gerente",
            "head of",
            "iii",
            "iv",
        ],
    },
    "level_mid": {
        "weight": PENALTY_LEVEL_MID,
        "terms": ["pleno", "pl", "pl.", "mid level", "mid-level"],
    },
    # Penalty: a stack the person does not have. High weight on purpose, it is
    # what fills the queue with noise the most.
    "stack_mismatch": {
        "weight": PENALTY_STACK_MISMATCH,
        "terms": [
            "php",
            "laravel",
            "wordpress",
            "delphi",
            "cobol",
            "abap",
            ".net",
            "c#",
            "ruby on rails",
            "flutter",
            "react native",
            "android nativo",
            "ios",
            "salesforce",
            "sap",
            "vba",
            "sharepoint",
        ],
    },
    # Penalty: a different area.
    "area_mismatch": {
        "weight": PENALTY_AREA_MISMATCH,
        "terms": [
            "designer",
            "ux/ui",
            "social media",
            "marketing",
            "vendas",
            "comercial",
            "suporte tecnico n1",
            "help desk",
            "infraestrutura de redes",
            "recrutamento",
        ],
    },
}

# Required years of experience: each band above 2 years pulls the job down.
YEARS_RE = re.compile(r"(\d+)\s*\+?\s*anos?\s+de\s+(experi|atua|vivenc)", re.IGNORECASE)

# Most demanding first: the first band that matches wins.
YEARS_PENALTIES: list[tuple[int, int]] = [(5, -25), (3, -12)]

# Seniority terms in the order they are tested. Internship before junior and
# senior before mid, because "pl" is the most generic of the four and would
# match titles that already stated the real level.
SENIORITY_TERMS: list[tuple[str, tuple[str, ...]]] = [
    ("internship", ("estagio", "estagiario", "estagiaria")),
    ("junior", ("junior", "jr", "trainee", "aprendiz")),
    ("senior", ("senior", "especialista", "tech lead", "staff")),
    ("mid", ("pleno", "pl")),
]

WORK_MODE_TERMS: list[tuple[str, tuple[str, ...]]] = [
    ("remote", ("remoto", "home office", "anywhere", "100% remoto")),
    ("hybrid", ("hibrido",)),
    ("onsite", ("presencial",)),
]
