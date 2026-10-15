import json
from functools import lru_cache

from analyse import _dossier_data  # même recherche de data/ partout : DATA_DIR, /app/data (Docker), dossiers parents


def load_jsonl(relative_path):
    rows = []
    with open(_dossier_data() / relative_path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows




def by_id(rows):
    return {row["id"]: row for row in rows}


@lru_cache(maxsize=None)
def load_questions():
    return load_jsonl("questions/questions.jsonl")


@lru_cache(maxsize=None)
def load_candidates():
    return by_id(load_jsonl("profiles/candidates.jsonl"))


@lru_cache(maxsize=None)
def load_postings():
    return by_id(load_jsonl("profiles/postings.jsonl"))


@lru_cache(maxsize=None)
def load_scenarios():
    return by_id(load_jsonl("scenarios/scenarios.jsonl"))


def by_key(rows, key):
    return {row[key]: row for row in rows}


@lru_cache(maxsize=None)
def load_answers():
    return by_id(load_jsonl("answers/answers.jsonl"))


@lru_cache(maxsize=None)
def load_annotations():
    return by_key(load_jsonl("annotations/annotations.jsonl"), "answer_id")


if __name__ == "__main__":
    qs = load_questions()
    print(len(qs), "questions chargées")
    print(qs[0]["text"]["fr"])