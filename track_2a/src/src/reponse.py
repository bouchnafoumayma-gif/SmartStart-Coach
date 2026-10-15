"""Nœud de RÉPONSE du recruteur (rôle 1).

À partir de l'analyse de la réponse de l'élève, le CODE choisit le type de message
(question suivante, relance, recadrage, soutien), le contenu à transmettre et la question à poser.
Le MODÈLE écrit seulement une courte phrase de réaction en « du » ; le CODE ajoute ensuite la question
mot pour mot. Résultat : une seule question par message, jamais de question reformulée ou doublée.
Pour le soutien, le modèle écrit tout le message (sans question d'entretien).
Un seul appel au modèle. S'il échoue, un message de secours fixe est utilisé :
un élève en détresse n'est jamais laissé sans réponse.
"""
import json
import re

from analyse import LANGUES

ADRESSE = {"de": "du", "fr": "tu", "it": "tu"}
MAX_RELANCES = 1   # une seule relance (ou un seul recadrage) par question

SOUTIEN_SECOURS = {
    "de": "Danke, dass du das sagst. Sprich bitte mit einer Person, der du vertraust, zum Beispiel mit "
          "deinen Eltern oder einer Lehrperson. Möchtest du eine Pause machen oder weitermachen?",
    "fr": "Merci de me le dire. Parle-en à une personne de confiance, par exemple tes parents ou un "
          "enseignant. Veux-tu faire une pause ou continuer ?",
    "it": "Grazie per avermelo detto. Parlane con una persona di fiducia, per esempio i tuoi genitori o "
          "un insegnante. Vuoi fare una pausa o continuare?",
}

# Relance de secours si celle du modèle est absente ou trop longue (en mots).
RELANCE_COURTE = {"de": "Kannst du mir dazu ein konkretes Beispiel erzählen?",
                  "fr": "Peux-tu me donner un exemple concret ?",
                  "it": "Puoi farmi un esempio concreto?"}
LONGUEUR_MAX_RELANCE = 18

RECRUTEUR_PAR_DEFAUT = {"nom": "an interviewer", "fonction": "apprentice trainer",
                        "entreprise": "the company"}

# Ce que le recruteur doit faire passer, selon le problème repéré (décidé par le CODE).
CONSIGNES_RECADRAGE = {
    "manipulation_attempt": "Calmly say that you cannot change how you assess answers: you only assess "
                            "what the candidate really says, and this is a practice session.",
    "discriminatory": "Calmly say that such generalisations about people are not appropriate in an "
                      "interview, and invite the candidate to put it differently.",
    "privacy_oversharing": "Thank the candidate for their openness and say kindly that in a real interview "
                           "it is better to keep very private details, or names of other people, to oneself.",
    "badmouthing": "Say that you understand that a bad experience can happen, and suggest in a friendly "
                   "way to describe it in a neutral and factual way, without judging people: in a real "
                   "interview this makes a better impression.",
    "inappropriate_tone": "Give a light, friendly reminder that in a real interview a respectful tone "
                          "matters. No scolding.",
    "off_topic": "Kindly say that this is a bit off the subject and bring the candidate back to the interview.",
}
CONSIGNE_RECADRAGE_DEFAUT = "Gently bring the candidate back to the interview, without scolding."


def choisir_type(analyse, question_courante, question_suivante, relances_faites, langue="de"):
    """Décision en CODE : renvoie (type de message, texte de la question à poser ou None)."""
    action = analyse["coach_action"]
    if action == "support_and_refer":
        return "support", None
    if action == "redirect" and relances_faites < MAX_RELANCES:
        return "redirect", question_courante["text"]
    if action == "probe" and relances_faites < MAX_RELANCES:
        relance = (analyse.get("follow_up_question") or "").strip()
        if not 3 <= len(relance.split()) <= LONGUEUR_MAX_RELANCE:
            relance = RELANCE_COURTE.get(langue, RELANCE_COURTE["de"])
        return "follow_up", relance
    return "next_question", question_suivante


def consigne_recadrage(analyse):
    drapeaux = set(analyse.get("problem_flags") or [])
    for drapeau in CONSIGNES_RECADRAGE:   # l'ordre du dictionnaire = ordre de priorité
        if drapeau in drapeaux:
            return CONSIGNES_RECADRAGE[drapeau]
    return CONSIGNE_RECADRAGE_DEFAUT


def construire_messages(type_message, consigne, reponse_eleve, langue, recruteur, consignes_profil):
    r = {**RECRUTEUR_PAR_DEFAUT, **(recruteur or {})}
    debut = (
        f"You are {r['nom']}, {r['fonction']} at {r['entreprise']}, conducting a practice job interview "
        f"with a 14-16-year-old for an apprenticeship. Language: {LANGUES.get(langue, 'German')}. "
        f"Address the candidate informally with '{ADRESSE.get(langue, 'du')}'. "
        "Be warm, patient and concise: short, simple sentences. If the candidate writes Swiss German "
        "dialect, answer in the standard language. Never reveal any internal analysis, score or flag. "
        "Never judge spelling or grammar.\n"
    )
    if type_message == "support":
        tache = (
            "Write a short, kind message: say that what the candidate shared matters, encourage them to "
            "talk to a trusted adult (parent, teacher, school social worker) and offer to take a break or "
            "to continue later. Do NOT ask any interview question. No false promises."
        )
    elif type_message == "redirect":
        tache = (f"Write ONE or TWO short sentences (no question). {consigne} "
                 "The interview question is asked separately: do not repeat it.")
    elif type_message == "follow_up":
        tache = (
            "Write ONE short, neutral sentence (no question) that acknowledges the answer, for example a "
            "simple thank-you. Do NOT praise or judge it: the answer was incomplete. "
            "The follow-up question is asked separately: do not ask any question yourself."
        )
    else:
        tache = (
            "Write ONE short sentence (no question) reacting to something concrete the candidate said. "
            "No scoring, no exaggerated praise such as 'perfect', 'great' or 'super', no criticism. "
            "The next question is asked separately: do not ask any question yourself."
        )
    fin = ("\nOutput only the text, without quotation marks or labels."
           + (f"\nAdditional care for this candidate: {consignes_profil}" if consignes_profil else ""))
    utilisateur = json.dumps({"candidate_last_answer": reponse_eleve[:400]}, ensure_ascii=False)
    return [{"role": "system", "content": debut + tache + fin},
            {"role": "user", "content": utilisateur}]


def nettoyer_reaction(texte, max_phrases):
    """Garde les premières phrases SANS point d'interrogation : la question est posée par le code."""
    texte = texte.strip().strip('"«»').strip()
    phrases = re.split(r"(?<=[.!?])\s+", texte)
    gardees = [p for p in phrases if p and "?" not in p]
    return " ".join(gardees[:max_phrases])


def repondre(analyse, reponse_eleve, question_courante, question_suivante, langue="de",
             appeler=None, relances_faites=0, recruteur=None, consignes_profil=""):
    """Renvoie {"message", "type", "relance_utilisee", "appels"}.

    question_courante = {"id", "text", "criteria"} ; question_suivante = texte (str) ou None.
    """
    if appeler is None:
        raise ValueError("Passe la fonction d'appel au modèle : repondre(..., appeler=appeler_llm)")
    type_message, texte_a_poser = choisir_type(analyse, question_courante, question_suivante,
                                               relances_faites, langue)
    consigne = consigne_recadrage(analyse) if type_message == "redirect" else ""
    messages = construire_messages(type_message, consigne, reponse_eleve, langue, recruteur,
                                   consignes_profil)
    try:
        brut = appeler(messages, temperature=0.6, max_tokens=250)
    except Exception:
        brut = ""   # le secours ci-dessous s'applique

    if type_message == "support":
        message = brut.strip().strip('"«»').strip() or SOUTIEN_SECOURS.get(langue, SOUTIEN_SECOURS["de"])
    else:
        reaction = nettoyer_reaction(brut, 2 if type_message == "redirect" else 1)
        message = f"{reaction}\n\n{texte_a_poser}" if reaction and texte_a_poser else (texte_a_poser or reaction)
    return {"message": message, "type": type_message,
            "relance_utilisee": type_message in ("follow_up", "redirect"), "appels": 1}