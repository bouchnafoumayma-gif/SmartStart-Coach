import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_loader import load_questions, load_scenarios
from few_shot import find_similar_answers
from question_selector import get_next_question, get_posting_facts

ETAPES = ["introduction", "motivation", "strengths_weaknesses",
          "situational", "candidate_questions", "closing"]


def questions_posees(scenario):
    state = {
        "language": scenario["lang"],
        "candidate_id": scenario["candidate_id"],
        "posting_id": scenario["posting_id"],
        "scenario_id": scenario["id"],
        "asked_question_ids": [],
    }
    for etape in ETAPES:
        while True:
            q = get_next_question(state, etape)
            if q is None:
                break
            state["asked_question_ids"].append(q["id"])
    return state["asked_question_ids"]


def main():
    total_prevues = 0
    total_manquees = 0
    for scenario in load_scenarios().values():
        posees = questions_posees(scenario)
        manquees = [qid for qid in scenario["planned_question_ids"] if qid not in posees]
        facts_ok = bool(get_posting_facts(scenario["posting_id"]))

        total_prevues += len(scenario["planned_question_ids"])
        total_manquees += len(manquees)

        statut = "OK" if not manquees and facts_ok else "KO"
        print(statut, scenario["id"], scenario["lang"], scenario["situation"], "manquées:", manquees)

    print(f"\n{total_manquees} questions prévues jamais posées sur {total_prevues}")

    sans_exemple = [q["id"] for q in load_questions() if not find_similar_answers(q["id"], "test")]
    print(f"{len(sans_exemple)} questions sans exemple few-shot sur {len(load_questions())}")


if __name__ == "__main__":
    main()