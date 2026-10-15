"""État de l'entretien : le « carnet de notes » que LangGraph passe de nœud en nœud."""
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages

from .schemas import parse_config

# --- Le plan de l'entretien -------------------------------------------------
# Noms IDENTIQUES à `flow_stage` dans data/questions/questions.jsonl (rôle 2).
STAGES = [
    "introduction",
    "motivation",
    "strengths_weaknesses",
    "situational",
    "candidate_questions",
    "closing",
]
FEEDBACK_STAGE = "feedback"  # étape 6 : le feedback final (après `closing`)

# Questions principales par étape : 2+3+3+3+1+1 = 13  (le guide demande 10 à 15).
STAGE_QUOTAS = {
    "introduction": 2,
    "motivation": 3,
    "strengths_weaknesses": 3,
    "situational": 3,
    "candidate_questions": 1,
    "closing": 1,
}
TOTAL_QUESTIONS = sum(STAGE_QUOTAS.values())

MAX_FOLLOWUPS_PER_QUESTION = 1  # nombre maximal de relances par question
HARD_CAP_QUESTIONS = 15         # plafond de sécurité : on passe au feedback quoi qu'il arrive
MAX_LLM_CALLS_PER_TURN = 5      # le critère du hackathon : moins de 5 appels par réponse


class InterviewState(TypedDict, total=False):
    messages: Annotated[list, add_messages]  # historique
    config: dict                 # language, dialect, candidate_id, posting_id, profile, formal_address
    stage: str                   # étape courante (STAGES, puis "feedback")
    question_count: int          # questions principales posées
    stage_question_count: int    # questions posées dans l'étape courante
    followup_count: int          # relances faites sur la question courante
    asked_ids: list              # ids des questions déjà posées
    current_question: Optional[dict]
    analyses: list               # une analyse (dict JSON) par réponse de l'élève
    summary: str                 # résumé court plutôt que tout l'historique
    next_action: str             # dernière décision
    llm_calls_total: int         # compteur d'appels (retries compris)
    llm_calls_turn: int          # appels du tour en cours
    final_feedback: Optional[Any]  # None jusqu'à l'étape 6


def new_state(config: Optional[dict] = None) -> InterviewState:
    """État initial. `config` peut être None, partiel ou invalide : on retombe sur des défauts."""
    return {
        "messages": [],
        "config": parse_config(config).model_dump(),
        "stage": STAGES[0],
        "question_count": 0,
        "stage_question_count": 0,
        "followup_count": 0,
        "asked_ids": [],
        "current_question": None,
        "analyses": [],
        "summary": "",
        "next_action": "",
        "llm_calls_total": 0,
        "llm_calls_turn": 0,
        "final_feedback": None,
    }
