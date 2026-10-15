"""Test à la main du feedback final : un mini-entretien de 4 réponses, analysé puis résumé.
Lancer : python -m uv run python test_feedback.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from analyse import analyser
from essai_llm import appeler_llm
import feedback
from feedback import generer_feedback

ECHANGES = [
    ({"id": "Q1", "text": "Warum möchtest du Polymechaniker werden?",
      "criteria": ["motivation", "concrete_examples", "clarity"]},
     "Ich schraube seit drei Jahren an meinem Mofa. Letzten Sommer habe ich den Vergaser selbst "
     "gereinigt, und danach lief es wieder. In der Schnupperlehre habe ich gemerkt, dass mir das "
     "genaue Arbeiten gefällt."),
    ({"id": "Q2", "text": "Was ist eine Stärke von dir?",
      "criteria": ["self_reflection", "concrete_examples", "clarity"]},
     "Ich bin zuverlässig."),
    ({"id": "Q3", "text": "Was ist eine Schwäche von dir?",
      "criteria": ["self_reflection", "difficult_questions", "communication"]},
     "Manchmal bin ich zu langsam, weil ich alles genau machen will. Ich versuche jetzt, mir vorher "
     "einen Plan mit Schritten zu machen."),
    ({"id": "Q4", "text": "Wie gehst du mit Streit im Team um?",
      "criteria": ["communication", "relevance", "self_reflection"]},
     "Ich rede mit der Person. Wenn ich wütend bin, gehe ich zuerst kurz weg und rede dann in Ruhe mit ihr."),
]

entretien = []
for question, reponse in ECHANGES:
    analyse = analyser(question, reponse, langue="de", appeler=appeler_llm)
    entretien.append({"question": question["text"], "reponse": reponse, "analyse": analyse})
    print(f"{question['id']}  action={analyse['coach_action']:<10} notes={analyse['criteria_scores']}")

resultat = generer_feedback(entretien, langue="de", appeler=appeler_llm)
print(f"\nNiveaux calculés par le code : {resultat['donnees']['niveaux']}")
print(f"Critères avec citation vérifiée : {[c['criterion'] for c in resultat['donnees']['criteres']]}")
print(f"Appels pour le feedback : {resultat['appels']}\n")
print(resultat["texte"])

# ---- DIAGNOSTIC (peut être supprimé quand tout marche)
print("\n===== DIAGNOSTIC =====")
print("fichier feedback.py chargé :", feedback.__file__)
print("version avec diagnostic    :", hasattr(feedback, "JOURNAL"))
rejets = resultat["donnees"].get("rejets")
if rejets is None:
    print(">>> ANCIENNE VERSION de feedback.py : remplace ce fichier par le dernier envoyé.")
elif not resultat["donnees"]["criteres"]:
    print("Raisons des rejets :")
    for ligne in rejets:
        print("  -", ligne)
    # réponse brute du modèle pour le 1er appel, pour voir ce qu'il écrit vraiment
    fortes, faibles = feedback.choisir_candidats(resultat["donnees"]["niveaux"])
    msgs = feedback.messages_criteres(entretien, fortes, faibles, resultat["donnees"]["niveaux"], "de", "")
    print("\nRéponse brute du modèle (appel critères) :")
    print(appeler_llm(msgs, temperature=0.3, max_tokens=1200))
sys.stdout.flush()
