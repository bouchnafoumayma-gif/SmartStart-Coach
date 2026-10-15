"""Branchement du graphe LangGraph (rôle 1).

Un message de l'élève = un passage dans le graphe :
    accueil  (1er passage, question_count == 0) : message d'accueil + 1re question, 0 appel LLM
    tour     : analyse (1 appel) -> décision par flow.py -> réponse du recruteur (1 appel)
    feedback : si flow.py décide « finish » : bilan final (2 appels, 3 si réparation)

La décision (relance, question suivante, changement d'étape, fin, soutien) vient de flow.py.
reponse.py applique la même règle de son côté ; on suit toujours le type de message qu'il renvoie.
"""
from langgraph.graph import END, START, StateGraph

# Imports sans point : Aegra charge ce fichier seul et ajoute track_2a/src/src au sys.path (aegra.json).
from analyse import analyser
from coach.flow import decide_next_action, next_stage_of, rolling_summary, state_updates_for
from coach.state import FEEDBACK_STAGE, MAX_FOLLOWUPS_PER_QUESTION, InterviewState, new_state
from feedback import generer_feedback
from llm_client import LLMError, get_llm
from question_selector import get_next_question          # rôle 2 : get_next_question(state, stage)
from reponse import repondre

ACCUEIL = {
    "de": "Hallo! Schön, dass du da bist. Wir üben jetzt zusammen ein Vorstellungsgespräch. Los geht's!",
    "fr": "Bonjour ! On va s'entraîner ensemble à un entretien d'embauche. C'est parti !",
    "it": "Ciao! Ci alleniamo insieme a un colloquio di lavoro. Si parte!",
}

# Si l'appel d'analyse échoue (panne d'Apertus) : on continue l'entretien sans note.
ANALYSE_SECOURS = {"criteria_scores": {}, "problem_flags": [], "coach_action": "continue",
                   "follow_up_question": None, "analyse_ok": False, "appels": 0}


# ------------------------------------------------------------------ petits outils
def _appeler(tag):
    """Adaptateur : les nœuds appellent appeler(messages, temperature=, max_tokens=) -> str."""
    def appeler(messages, temperature=None, max_tokens=None):
        return get_llm().call(messages, tag=tag, temperature=temperature, max_tokens=max_tokens)
    return appeler


def _langue(state):
    return (state.get("config") or {}).get("language", "de")


def _question(q):
    """Question du rôle 2 (dict ou objet pydantic) -> {"id", "text", "criteria"}."""
    if q is None:
        return None
    d = q if isinstance(q, dict) else q.model_dump()
    return {"id": d.get("id"), "text": d["text"], "criteria": d.get("criteria") or []}


def _dernier_message_eleve(state):
    for m in reversed(state.get("messages") or []):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "type", None)
        if role in ("human", "user"):
            return str(m.get("content", "") if isinstance(m, dict) else m.content)
    return ""


MOTS_LANGUE = {
    "fr": {"bonjour", "salut", "bonsoir", "merci", "je", "suis", "oui", "coucou"},
    "it": {"ciao", "buongiorno", "buonasera", "grazie", "sono", "salve"},
}


def _deviner_langue(texte):
    """Sans langue choisie (ex. Agent Chat UI) : « Bonjour » -> fr, « Ciao » -> it, sinon de."""
    mots = set(texte.lower().replace("!", " ").replace(",", " ").replace(".", " ").split())
    for langue, indices in MOTS_LANGUE.items():
        if mots & indices:
            return langue
    return "de"


def _appels(state, avant):
    """Appels faits depuis `avant` (compteur du client : essais et corrections compris)."""
    delta = get_llm().stats()["calls"] - avant
    return {"llm_calls_turn": delta, "llm_calls_total": state.get("llm_calls_total", 0) + delta}


# ------------------------------------------------------------------ nœuds
def noeud_accueil(state):
    # L'interface de chat n'envoie que {"messages": [...]} : on complète avec l'état initial.
    config = dict(state.get("config") or {})
    if not config.get("language"):
        config["language"] = _deviner_langue(_dernier_message_eleve(state))
    init = new_state(config)
    del init["messages"]
    st = {**init, **{k: v for k, v in state.items() if v is not None and k != "config"}}
    q = _question(get_next_question(st, st["stage"]))
    maj = {**{k: st[k] for k in init}, **state_updates_for("next_question", st)}
    maj.update(current_question=q, asked_ids=(st.get("asked_ids") or []) + [q["id"]],
               next_action="next_question",
               messages=[{"role": "assistant", "content": f"{ACCUEIL.get(_langue(st), ACCUEIL['de'])}\n\n{q['text']}"}])
    return maj


def noeud_tour(state):
    avant = get_llm().stats()["calls"]
    langue = _langue(state)
    reponse = _dernier_message_eleve(state)
    q = state["current_question"]

    try:
        analyse = analyser(q, reponse, langue, appeler=_appeler("analyse"))
    except LLMError:
        analyse = dict(ANALYSE_SECOURS)

    # La question et la réponse sont rangées dans l'analyse : le feedback en a besoin pour citer l'élève.
    entree = {**analyse, "question": q["text"], "reponse": reponse}
    analyses = (state.get("analyses") or []) + [entree]
    st = {**state, "analyses": analyses}
    base = {"analyses": analyses,
            "summary": rolling_summary(state.get("summary", ""), q["text"], reponse)}

    def fin():
        return {**base, **state_updates_for("finish", st), "next_action": "finish", **_appels(state, avant)}

    action = decide_next_action(st)
    if action == "finish":
        return fin()

    # Que se passerait-il sans relance ? (pour connaître la question suivante éventuelle)
    avance = action if action != "followup" else decide_next_action(
        {**st, "followup_count": MAX_FOLLOWUPS_PER_QUESTION})
    q_suivante, etape = None, st["stage"]
    if avance in ("next_question", "next_stage"):
        etape = next_stage_of(st["stage"]) if avance == "next_stage" else st["stage"]
        q_suivante = _question(get_next_question(st, etape))

    res = repondre(analyse, reponse, q, q_suivante["text"] if q_suivante else None, langue,
                   appeler=_appeler("reponse"), relances_faites=st.get("followup_count", 0))

    # On suit le type de message réellement produit par reponse.py
    if res["type"] == "support":
        final = "support"
    elif res["type"] in ("follow_up", "redirect"):
        final = "followup"
    else:
        final = avance
    if final == "finish" or (final in ("next_question", "next_stage") and q_suivante is None):
        return fin()

    maj = {**base, **state_updates_for(final, st), "next_action": final,
           "messages": [{"role": "assistant", "content": res["message"]}]}
    if final == "followup" and res["type"] == "follow_up":
        # la prochaine réponse de l'élève répond à la relance : c'est elle qu'il faut citer au feedback
        maj["current_question"] = {**q, "text": res["message"].rsplit("\n\n", 1)[-1]}
    elif final in ("next_question", "next_stage"):
        maj["current_question"] = q_suivante
        maj["asked_ids"] = (state.get("asked_ids") or []) + [q_suivante["id"]]
    maj.update(_appels(state, avant))
    return maj


def noeud_feedback(state):
    avant = get_llm().stats()["calls"]
    entretien = [{"question": a["question"], "reponse": a["reponse"], "analyse": a}
                 for a in state.get("analyses") or []]
    fb = generer_feedback(entretien, _langue(state), appeler=_appeler("feedback"))
    # « rejets » contient des morceaux de réponses d'élèves : on ne l'expose pas
    donnees = {k: v for k, v in fb["donnees"].items() if k != "rejets"}
    delta = get_llm().stats()["calls"] - avant
    return {"final_feedback": {"texte": fb["texte"], "avec_soutien": fb["avec_soutien"], **donnees},
            "stage": FEEDBACK_STAGE,
            "messages": [{"role": "assistant", "content": fb["texte"]}],
            "llm_calls_turn": state.get("llm_calls_turn", 0) + delta,
            "llm_calls_total": state.get("llm_calls_total", 0) + delta}


# ------------------------------------------------------------------ routage
def depart(state):
    if state.get("final_feedback"):
        return END
    return "accueil" if state.get("question_count", 0) == 0 else "tour"


def apres_tour(state):
    return "feedback" if state.get("next_action") == "finish" else END


g = StateGraph(InterviewState)
g.add_node("accueil", noeud_accueil)
g.add_node("tour", noeud_tour)
g.add_node("feedback", noeud_feedback)
g.add_conditional_edges(START, depart, {"accueil": "accueil", "tour": "tour", END: END})
g.add_edge("accueil", END)
g.add_conditional_edges("tour", apres_tour, {"feedback": "feedback", END: END})
g.add_edge("feedback", END)

graph = g.compile()