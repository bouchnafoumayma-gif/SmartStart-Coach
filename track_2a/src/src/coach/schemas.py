"""Contrat d'API (rôle 3) : ce qui ENTRE dans l'agent et ce qui en SORT.

L'agent accepte :
  1. un candidate_id + un posting_id du dataset (data/profiles/),
  2. OU un profil complet venant du formulaire (`profile`),
  3. OU rien du tout (valeurs par défaut).
Le contrat ne fait jamais planter l'agent : une valeur invalide retombe sur un défaut.
Vie privée : élèves de 14-16 ans -> seuls les champs déclarés ci-dessous sont gardés
(pas de nom de famille, e-mail, adresse, téléphone : ils sont ignorés).
"""
import re
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

LANGUAGES = ("de", "fr", "it")
DEFAULT_LANGUAGE = "de"
DIALECTS = ("zh", "be", "bs", "lu", "sg", "gr", "vs", "ag", "so", "tg")


# --- Profil (formulaire) ------------------------------------------------------
class School(BaseModel):
    model_config = ConfigDict(extra="ignore")
    level: Optional[str] = Field(None, max_length=40)
    grade: Optional[str] = Field(None, max_length=40)
    strong_subjects: list[str] = Field(default_factory=list)
    weak_subjects: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Optional[str] = Field(None, max_length=40)           # ex. schnupperlehre
    occupation: Optional[str] = Field(None, max_length=80)
    company_type: Optional[str] = Field(None, max_length=80)
    duration_days: Optional[int] = Field(None, ge=0, le=365)
    what_happened: Optional[str] = Field(None, max_length=500)


class CandidateProfile(BaseModel):
    """Champs repris de data/profiles/candidates.jsonl, avec le minimum de données personnelles."""

    model_config = ConfigDict(extra="ignore")  # tout champ non déclaré est supprimé

    first_name: Optional[str] = Field(None, max_length=40)     # prénom SEULEMENT
    age: Optional[int] = Field(None, ge=10, le=25)
    gender: Optional[str] = Field(None, max_length=10)         # uniquement pour les accords grammaticaux
    canton: Optional[str] = Field(None, max_length=20)
    school: Optional[School] = None
    hobbies: list[str] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    development_areas: list[str] = Field(default_factory=list)
    target_occupation: Optional[str] = Field(None, max_length=80)
    career_choice_story: Optional[str] = Field(None, max_length=800)
    future_plans: Optional[str] = Field(None, max_length=500)

    @field_validator("first_name", mode="before")
    @classmethod
    def _only_first_name(cls, v):
        """« Luca Muster » -> « Luca » : on ne garde jamais le nom de famille."""
        if isinstance(v, str) and v.strip():
            return v.strip().split()[0]
        return None


# --- Entrée ---------------------------------------------------------------------
class InterviewConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    language: Literal["de", "fr", "it"] = DEFAULT_LANGUAGE
    dialect: Optional[Literal["zh", "be", "bs", "lu", "sg", "gr", "vs", "ag", "so", "tg"]] = None
    candidate_id: Optional[str] = Field(None, max_length=50)
    posting_id: Optional[str] = Field(None, max_length=50)
    posting_text: Optional[str] = Field(None, max_length=4000)
    challenge: Optional[Literal["confidence", "motivation", "strengths", "difficult_questions", "general_practice"]] = None
    profile: Optional[CandidateProfile] = None
    formal_address: bool = False  # False = « du/tu » (défaut du dataset), True = « Sie/vous/Lei »

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, v):
        """'FR', 'fr-CH' -> 'fr' ; 'gsw' ou valeur inconnue -> 'de'."""
        code = str(v or "").strip().lower()[:2]
        return code if code in LANGUAGES else DEFAULT_LANGUAGE

    @field_validator("dialect", mode="before")
    @classmethod
    def _normalize_dialect(cls, v):
        code = str(v or "").strip().lower()
        return code if code in DIALECTS else None

    @property
    def source(self) -> str:
        """D'où vient le candidat : 'profile' (formulaire) > 'dataset' (ids) > 'default'."""
        if self.profile is not None:
            return "profile"
        if self.candidate_id or self.posting_id:
            return "dataset"
        return "default"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str = "user"
    content: str = ""


class InterviewInput(BaseModel):
    """Ce que le front (ou le benchmark) envoie. `config` n'est utile qu'au premier tour."""

    model_config = ConfigDict(extra="ignore")
    messages: list[ChatMessage] = Field(default_factory=list)
    config: Optional[InterviewConfig] = None


def parse_config(raw: Any) -> InterviewConfig:
    """Transforme n'importe quelle entrée en config valide, sans jamais lever d'erreur."""
    if isinstance(raw, InterviewConfig):
        return raw
    if not isinstance(raw, dict):
        return InterviewConfig()
    try:
        return InterviewConfig.model_validate(raw)
    except ValidationError:
        pass
    try:  # le profil est peut-être invalide : on le retire et on garde le reste
        return InterviewConfig.model_validate({k: v for k, v in raw.items() if k != "profile"})
    except ValidationError:
        return InterviewConfig()


# --- Sortie ---------------------------------------------------------------------
class FinalFeedback(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    to_work_on: list[str] = Field(default_factory=list)
    next_step: str = ""


class PublicState(BaseModel):
    """L'état exposé en plus des messages."""

    stage: str
    question_count: int = 0
    llm_calls_total: int = 0
    final_feedback: Optional[Union[FinalFeedback, dict, str]] = None  # null jusqu'à l'étape 6


def public_view(state: dict) -> dict:
    return PublicState(
        stage=state.get("stage", "introduction"),
        question_count=state.get("question_count", 0),
        llm_calls_total=state.get("llm_calls_total", 0),
        final_feedback=state.get("final_feedback"),
    ).model_dump()


# --- Texte simple (pour qu'une voix puisse s'ajouter plus tard) -----------------------
def to_plain_text(text: str, max_chars: int = 600) -> str:
    """Retire la mise en forme (markdown, listes, liens) et raccourcit proprement."""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)        # [texte](url) -> texte
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)   # titres
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)        # puces
    t = re.sub(r"^\s*\d+[.)]\s+", "", t, flags=re.M)      # listes numérotées
    t = re.sub(r"[*_`~]+", "", t)                         # gras, italique, code
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        cut = t[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        t = cut[: end + 1] if end > max_chars // 2 else cut.rstrip() + "…"
    return t
