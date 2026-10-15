"""Logique de décision : Python pur, SANS appel LLM. C'est le « panneau de signalisation ».

Elle lit l'analyse de la dernière réponse (JSON produit par le rôle 1). Les noms de champs
suivent les annotations du dataset (data/annotations/) :
  quality_level (1..4), answer_class, problem_flags, coach_action.
Si le rôle 1 utilise d'autres noms ou valeurs, modifiez UNIQUEMENT les constantes ci-dessous.
"""
from typing import Optional

from .state import HARD_CAP_QUESTIONS, MAX_FOLLOWUPS_PER_QUESTION, STAGE_QUOTAS, STAGES, FEEDBACK_STAGE

# coach_action (dataset) : continue | probe | redirect | support_and_refer
SUPPORT_ACTIONS = {"support_and_refer", "support"}
FOLLOWUP_ACTIONS = {"probe", "redirect", "followup", "relancer"}
CONTINUE_ACTIONS = {"continue", "next", "continuer"}

# Si coach_action est absent, on se rabat sur ces drapeaux (problem_flags du dataset) et le niveau.
DISTRESS_FLAGS = {"distress_signal", "distress"}
FOLLOWUP_FLAGS = {"one_word", "off_topic", "manipulation_attempt", "vague", "too_short"}
FOLLOWUP_MAX_LEVEL = 2  # niveau 1 ou 2 -> on relance


def last_analysis(state: dict) -> dict:
    analyses = state.get("analyses") or []
    return analyses[-1] if analyses else {}


def _flags(analysis: dict) -> set:
    return set(analysis.get("problem_flags") or analysis.get("risk_flags") or [])


def _action(analysis: dict) -> Optional[str]:
    return analysis.get("coach_action") or analysis.get("action")


def _level(analysis: dict) -> Optional[int]:
    value = analysis.get("quality_level", analysis.get("level"))
    return value if isinstance(value, int) else None


def is_distress(analysis: dict) -> bool:
    return _action(analysis) in SUPPORT_ACTIONS or bool(_flags(analysis) & DISTRESS_FLAGS)


def needs_followup(analysis: dict) -> bool:
    action = _action(analysis)
    if action in FOLLOWUP_ACTIONS:
        return True
    if action in CONTINUE_ACTIONS:
        return False
    level = _level(analysis)  # pas d'action fournie : on déduit du niveau et des drapeaux
    return bool(_flags(analysis) & FOLLOWUP_FLAGS) or (level is not None and level <= FOLLOWUP_MAX_LEVEL)


def next_stage_of(stage: str) -> Optional[str]:
    if stage not in STAGES:
        return None
    i = STAGES.index(stage)
    return STAGES[i + 1] if i + 1 < len(STAGES) else None


def decide_next_action(state: dict) -> str:
    """Renvoie : 'support' | 'followup' | 'next_question' | 'next_stage' | 'finish'."""
    if state.get("final_feedback"):  # entretien déjà terminé
        return "finish"

    analysis = last_analysis(state)

    # 1. Détresse : priorité absolue (élèves de 14 à 16 ans) -> orienter vers une vraie personne.
    if is_distress(analysis):
        return "support"

    # 2. Début d'entretien : aucune réponse à analyser, on pose la 1re question.
    if state.get("question_count", 0) == 0:
        return "next_question"

    # 3. Réponse faible : relance, dans la limite du nombre de relances par question.
    if needs_followup(analysis) and state.get("followup_count", 0) < MAX_FOLLOWUPS_PER_QUESTION:
        return "followup"

    # 4. Plafond de sécurité.
    if state.get("question_count", 0) >= HARD_CAP_QUESTIONS:
        return "finish"

    # 5. Avancement : quota de l'étape atteint ?
    stage = state.get("stage", STAGES[0])
    if state.get("stage_question_count", 0) >= STAGE_QUOTAS.get(stage, 0):
        return "next_stage" if next_stage_of(stage) else "finish"
    return "next_question"


def state_updates_for(action: str, state: dict) -> dict:
    """Met à jour les compteurs selon la décision (on ne renvoie que les changements)."""
    qc = state.get("question_count", 0)
    stage = state.get("stage", STAGES[0])

    if action == "followup":
        return {"followup_count": state.get("followup_count", 0) + 1}
    if action == "next_question":
        return {
            "question_count": qc + 1,
            "stage_question_count": state.get("stage_question_count", 0) + 1,
            "followup_count": 0,
        }
    if action == "next_stage":
        return {
            "stage": next_stage_of(stage) or stage,
            "question_count": qc + 1,
            "stage_question_count": 1,
            "followup_count": 0,
        }
    if action == "finish":
        return {"stage": FEEDBACK_STAGE}
    return {}  # "support" : on ne change aucun compteur


def rolling_summary(summary: str, question: str, answer: str, max_chars: int = 1200) -> str:
    """Résumé court et borné (un modèle de 8 Mds de paramètres se perd sur un long historique)."""
    entry = f"Q: {question.strip()} | R: {answer.strip()[:300]}"
    text = f"{summary}\n{entry}".strip()
    if len(text) > max_chars:
        text = "…" + text[-(max_chars - 1):]
    return text
