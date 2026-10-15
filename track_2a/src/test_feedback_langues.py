"""Test du feedback final en français ou en italien (mêmes 4 échanges que test_feedback.py).
Lancer : python -m uv run python test_feedback_langues.py fr
         python -m uv run python test_feedback_langues.py it
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from analyse import analyser
from essai_llm import appeler_llm
import feedback
from feedback import generer_feedback

LANGUE = sys.argv[1] if len(sys.argv) > 1 else "fr"
if LANGUE not in ("fr", "it"):
    sys.exit("Utilisation : python test_feedback_langues.py fr|it")

DONNEES = {
    "fr": [
        ("Pourquoi veux-tu devenir polymécanicien ?", ["motivation", "concrete_examples", "clarity"],
         "Je bricole mon scooter depuis trois ans. L'été dernier, j'ai nettoyé le carburateur moi-même, "
         "et ensuite il a de nouveau fonctionné. Pendant le stage d'essai, j'ai remarqué que j'aime le travail précis."),
        ("Quelle est une de tes qualités ?", ["self_reflection", "concrete_examples", "clarity"],
         "Je suis fiable."),
        ("Quelle est une de tes faiblesses ?", ["self_reflection", "difficult_questions", "communication"],
         "Parfois je suis trop lent parce que je veux tout faire avec précision. J'essaie maintenant de "
         "faire d'abord un plan avec des étapes."),
        ("Comment réagis-tu en cas de dispute dans l'équipe ?", ["communication", "relevance", "self_reflection"],
         "Je parle avec la personne. Quand je suis en colère, je m'éloigne d'abord un moment, "
         "puis je lui parle calmement."),
    ],
    "it": [
        ("Perché vuoi diventare policmeccanico?", ["motivation", "concrete_examples", "clarity"],
         "Da tre anni lavoro sul mio motorino. L'estate scorsa ho pulito il carburatore da solo, "
         "e dopo ha funzionato di nuovo. Durante lo stage ho capito che mi piace lavorare con precisione."),
        ("Qual è un tuo punto di forza?", ["self_reflection", "concrete_examples", "clarity"],
         "Sono affidabile."),
        ("Qual è un tuo punto debole?", ["self_reflection", "difficult_questions", "communication"],
         "A volte sono troppo lento perché voglio fare tutto con precisione. Ora provo a fare prima "
         "un piano con dei passi."),
        ("Come ti comporti in caso di litigio nel team?", ["communication", "relevance", "self_reflection"],
         "Parlo con la persona. Quando sono arrabbiato, mi allontano un attimo e poi parlo con calma."),
    ],
}

entretien = []
for i, (texte, criteres, reponse) in enumerate(DONNEES[LANGUE], 1):
    question = {"id": f"Q{i}", "text": texte, "criteria": criteres}
    analyse = analyser(question, reponse, langue=LANGUE, appeler=appeler_llm)
    entretien.append({"question": texte, "reponse": reponse, "analyse": analyse})
    print(f"Q{i}  action={analyse['coach_action']:<10} notes={analyse['criteria_scores']}")

resultat = generer_feedback(entretien, langue=LANGUE, appeler=appeler_llm)
print(f"\nLangue : {LANGUE}")
print(f"Critères avec citation vérifiée : {[c['criterion'] for c in resultat['donnees']['criteres']]}")
print(f"Appels pour le feedback : {resultat['appels']}\n")
print(resultat["texte"])
if not resultat["donnees"]["criteres"]:
    print("\nRejets :", *resultat["donnees"].get("rejets", []), sep="\n  - ")
    niveaux = resultat["donnees"]["niveaux"]
    fortes, faibles = feedback.choisir_candidats(niveaux)
    print("\nRéponse BRUTE du modèle (appel critères) :")
    print(appeler_llm(feedback.messages_criteres(entretien, fortes, faibles, niveaux, LANGUE, ""),
                      temperature=0.3, max_tokens=1200))
