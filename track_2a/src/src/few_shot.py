import re

from data_loader import load_annotations, load_answers, load_questions


def words(text):
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


def similarity(text_a, text_b):
    a = words(text_a)
    b = words(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def to_example(answer):
    annotation = load_annotations()[answer["id"]]
    return {
        "answer_id": answer["id"],
        "text": answer["text"],
        "quality_level": answer["quality_level"],
        "answer_class": answer["answer_class"],
        "criteria_scores": annotation["criteria_scores"],
        "coach_action": annotation["coach_action"],
        "coach_feedback": annotation["coach_feedback"],
        "follow_up_question": annotation["follow_up_question"],
    }


def same_stage_question_ids(question_id):
    stages = {q["id"]: q["flow_stage"] for q in load_questions()}
    stage = stages.get(question_id)
    return {qid for qid, s in stages.items() if s == stage}



def find_similar_answers(question_id, student_answer, lang="de", k=3):
    pool = [a for a in load_answers().values() if a["question_id"] == question_id]
    if not pool:
        same_stage = same_stage_question_ids(question_id)
        pool = [a for a in load_answers().values() if a["question_id"] in same_stage]
    same_lang = [a for a in pool if a["lang"] == lang]
    if same_lang:
        pool = same_lang
    if not pool:
        return []

    pool.sort(key=lambda a: similarity(student_answer, a["text"]), reverse=True)

    chosen = []
    levels_seen = set()
    for a in pool:
        if a["quality_level"] not in levels_seen:
            chosen.append(a)
            levels_seen.add(a["quality_level"])
        if len(chosen) == k:
            break
    return [to_example(a) for a in chosen]


if __name__ == "__main__":
    reponse = "J'aime bricoler avec mon oncle et j'ai fait un stage dans un garage."
    for ex in find_similar_answers("Q-03-01", reponse, lang="fr"):
        print(ex["quality_level"], ex["answer_class"], "|", ex["text"][:80])
        print("   relance :", ex["follow_up_question"])