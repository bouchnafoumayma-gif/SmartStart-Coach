from data_loader import load_candidates, load_postings, load_questions, load_scenarios


def condition_ok(question, candidate):
    if question["condition"] is None:
        return True
    if candidate is None:
        return False
    school = candidate.get("school") or {}
    if question["id"] == "Q-06-06":
        return bool(school.get("stellwerk"))
    return bool(school.get("absences_note"))


def metier_ok(question, posting):
    if question["berufsfeld"] is None:
        return True
    if posting is None:
        return False
    return question["berufsfeld"]["key"] == posting["occupation"]["berufsfeld_key"]


def to_question(question, lang):
    return {
        "id": question["id"],
        "text": question["text"][lang],
        "stage": question["flow_stage"],
        "criteria": question["criteria"],
    }


def _get(state, key, default=None):
    """Lit un réglage dans state["config"] (graphe) ou à la racine de state (eval/check_selector.py)."""
    config = state.get("config") or {}
    value = config.get(key)
    return value if value is not None else state.get(key, default)


def get_next_question(state, stage):
    lang = _get(state, "language", "de")
    asked = state.get("asked_ids") or state.get("asked_question_ids") or []
    candidate = load_candidates().get(_get(state, "candidate_id"))
    posting = load_postings().get(_get(state, "posting_id"))
    scenario = load_scenarios().get(_get(state, "scenario_id"))

    planned = scenario["planned_question_ids"] if scenario else []
    situation = scenario["situation"] if scenario else "apprenticeship_interview"

    possibles = [
        q for q in load_questions()
        if q["flow_stage"] == stage
        and q["id"] not in asked
        and condition_ok(q, candidate)
        and (
            q["id"] in planned
            or (q["situation"] in ("apprenticeship_interview", situation)
                and metier_ok(q, posting))
        )
    ]
    if not possibles:
        return None

    if scenario:
        for qid in scenario["planned_question_ids"]:
            for q in possibles:
                if q["id"] == qid:
                    return to_question(q, lang)

    for q in possibles:
        if q["berufsfeld"] is not None:
            return to_question(q, lang)

    return to_question(possibles[0], lang)


def get_posting_facts(posting_id):
    posting = load_postings().get(posting_id)
    if posting is None:
        return {}
    return {
        "company": posting["company"],
        "occupation": posting["occupation"]["name_de"],
        "offers": posting["offers"],
        "selection_process": posting["selection_process"],
        "insider_facts": posting["insider_facts"],
        "bm_possible": posting["bm_possible"],
        "start_date": posting["start_date"],
    }


if __name__ == "__main__":
    state = {"language": "fr", "candidate_id": "C-01", "posting_id": "P-01",
             "scenario_id": None, "asked_question_ids": []}
    etapes = ["introduction", "motivation", "strengths_weaknesses",
              "situational", "candidate_questions", "closing"]
    for etape in etapes:
        for _ in range(2):
            q = get_next_question(state, etape)
            if q is None:
                print(etape, "-> plus de question")
                break
            print(etape, "->", q["id"], ":", q["text"])
            state["asked_question_ids"].append(q["id"])
    print(get_posting_facts("P-01")["company"])