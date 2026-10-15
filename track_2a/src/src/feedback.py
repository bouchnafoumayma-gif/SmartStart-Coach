"""Nœud de FEEDBACK final (rôle 1) : le bilan donné à l'élève à la fin de l'entretien.

Principe : le CODE fait tout ce qui doit être fiable, le MODÈLE n'écrit que les phrases.
  1. Le code calcule le niveau de chaque critère (moyenne des analyses) : le modèle ne peut pas les changer,
     ce qui rend le bilan cohérent d'un entretien et d'une langue à l'autre.
  2. Le code choisit de quoi parler : jusqu'à 3 critères réussis (niveau 3 ou 4) et 3 critères à travailler
     (niveau 1 ou 2), et le tour d'entretien où citer l'élève. Chaque critère reçoit un tour DIFFÉRENT quand
     c'est possible (le meilleur tour pour un point fort, le plus faible pour un point à travailler), pour ne
     pas citer deux fois la même phrase.
  3. Appel n°1 : le modèle propose, pour ces critères seulement, une citation, une phrase sur le comportement
     observé et un conseil concret.
  4. Le code VÉRIFIE chaque proposition : la citation existe vraiment dans le tour visé (rien d'inventé), la
     phrase de comportement ne parle pas d'un autre critère, le conseil est à l'impératif (sinon conseil
     générique). Il raccourcit la citation et garde 2 points forts et 2 points à travailler au maximum.
     S'il manque des critères, UN seul appel de réparation redemande uniquement ceux-là.
  5. Appel n°2 : le modèle écrit un court résumé et la phrase de fin (le code écarte un résumé qui
     ne s'adresse pas à l'élève).
  6. Le code assemble le texte final dans la langue de l'entretien, avec un rappel de soutien si
     l'élève a montré de la détresse pendant l'entretien. Si le modèle est en panne, le code fournit un
     bilan simple de secours.
Au total 2 appels au modèle (3 si la réparation est nécessaire), une seule fois par entretien.
"""
import json
import os
import re
import sys

from analyse import LANGUES, _dossier_data, criteres, extraire_json

JOURNAL = []   # raisons des rejets du dernier feedback (affichées automatiquement si rien n'est vérifié)


def _debug(*message):
    """Note pourquoi une proposition est rejetée ; l'affiche tout de suite si FEEDBACK_DEBUG=1."""
    ligne = " ".join(str(m) for m in message)
    JOURNAL.append(ligne)
    if os.environ.get("FEEDBACK_DEBUG"):
        print("[feedback]", ligne, file=sys.stderr)


ADRESSE = {"de": "du", "fr": "tu", "it": "tu"}

# Exemples d'impératifs donnés au modèle et mots interdits en début de conseil (infinitif / article)
IMPERATIVS = {"de": "Erzähle, Überlege, Nenne, Beschreibe", "fr": "Raconte, Pense, Décris, Choisis",
              "it": "Racconta, Pensa, Descrivi, Scegli"}
FIN_INFINITIF = {"de": ("en",), "fr": ("er", "ir", "re"), "it": ("are", "ere", "ire", "re")}
ARTICLES = {"de": {"ein", "eine", "einen", "einem", "einer", "der", "die", "das", "den", "dem",
                   "kurz", "kurze", "konkrete", "mehr"},
            "fr": {"un", "une", "des", "le", "la", "les", "plus"},
            "it": {"un", "una", "uno", "il", "la", "le", "i", "lo", "gli", "più"}}
PRONOMS = {"de": r"\b(du|dir|dich|dein\w*)\b", "fr": r"\b(tu|te|toi|ton|ta|tes)\b",
           "it": r"\b(tu|ti|tuo|tua|tue|tuoi|hai|sei|puoi)\b"}
EXEMPLE_RESUME = {"de": "Du hast ... erzählt. Als Nächstes ...", "fr": "Tu as ... raconté. Ensuite ...",
                  "it": "Hai ... raccontato. Ora ..."}

TEXTES = {
    "de": {"dp": ":", "titre": "Dein Feedback", "forces": "Das ist dir gut gelungen:",
           "travail": "Daran kannst du als Nächstes arbeiten:", "conseil": "Tipp",
           "rien": "Für ein genaues Feedback waren es noch zu wenige Antworten. Übe gern noch einmal – "
                   "jede Runde hilft dir weiter!",
           "conseil_generique": "Denk an eine echte Situation von dir und erzähle sie in drei Sätzen.",
           "fin_secours": "Das war eine Übungsrunde – jede Runde hilft dir weiter!",
           "soutien": "Wenn dich etwas belastet, sprich bitte mit einer Person, der du vertraust – zum "
                      "Beispiel mit deinen Eltern, einer Lehrperson oder der Berufsberatung."},
    "fr": {"dp": " :", "titre": "Ton feedback", "forces": "Voici ce qui t'a bien réussi :",
           "travail": "Voici ce que tu peux travailler ensuite :", "conseil": "Conseil",
           "rien": "Il y avait encore trop peu de réponses pour un feedback précis. Réessaie volontiers : "
                   "chaque tour t'aide à progresser !",
           "conseil_generique": "Pense à une vraie situation que tu as vécue et raconte-la en trois phrases.",
           "fin_secours": "C'était un tour d'entraînement : chaque tour t'aide à progresser !",
           "soutien": "Si quelque chose te pèse, parles-en à une personne de confiance, par exemple tes "
                      "parents, un enseignant ou un conseiller en orientation."},
    "it": {"dp": ":", "titre": "Il tuo feedback", "forces": "Ecco cosa ti è riuscito bene:",
           "travail": "Ecco su cosa puoi lavorare ora:", "conseil": "Consiglio",
           "rien": "Le risposte erano ancora troppo poche per un feedback preciso. Riprova pure: "
                   "ogni giro ti aiuta a migliorare!",
           "conseil_generique": "Pensa a una situazione vera che hai vissuto e raccontala in tre frasi.",
           "fin_secours": "Era un giro di allenamento: ogni giro ti aiuta a migliorare!",
           "soutien": "Se qualcosa ti pesa, parlane con una persona di fiducia, per esempio i tuoi "
                      "genitori, un insegnante o un consulente di orientamento."},
}


# ------------------------------------------------------------------ lecture tolérante du JSON du modèle
_GUILLEMET_MANQUANT = re.compile(
    r'("(?:evidence|rationale|tip|summary|closing)"\s*:\s*)(?!["\d\-]|null|true|false)([^"]*?)"(\s*[,}])')


def reparer_json(brut):
    """Répare l'erreur la plus fréquente d'Apertus : un guillemet OUVRANT oublié devant une phrase
    (\"rationale\": Die Antwort ...\"). Ne coûte aucun appel au modèle."""
    return _GUILLEMET_MANQUANT.sub(lambda m: f'{m.group(1)}"{m.group(2)}"{m.group(3)}', brut or "")


def lire_json(brut):
    """Lit la réponse du modèle ; si elle est invalide, tente la réparation. Renvoie {} si impossible."""
    donnees = extraire_json(brut)
    if not donnees:
        donnees = extraire_json(reparer_json(brut))
        if donnees:
            _debug("JSON invalide réparé par le code (guillemet manquant)")
    return donnees or {}


# Noms de champs que le modèle traduit ou remplace parfois (surtout en italien et en français)
ALIAS_CHAMPS = {
    "evidence": ("quote_from", "quote", "citation", "citazione", "evidenza", "evidenze", "zitat", "extrait", "estratto",
                 "cita", "evidence_quote", "preuve", "prova"),
    "rationale": ("reason", "observation", "observed", "behaviour", "behavior", "motivazione", "spiegazione",
                  "osservazione", "comportamento", "raison", "explication", "begründung", "beobachtung"),
    "tip": ("advice", "suggestion", "consiglio", "suggerimento", "conseil", "astuce", "tipp", "hint"),
}


def normaliser_champs(p):
    """Si le modèle a renommé un champ (ex. « citazione » au lieu de « evidence »), le remet à son nom."""
    q = dict(p)
    bas = {str(k).lower().strip(): k for k in p}
    for canonique, alias in ALIAS_CHAMPS.items():
        if q.get(canonique) in (None, ""):
            for a in alias:
                if a in bas and p[bas[a]] not in (None, ""):
                    q[canonique] = p[bas[a]]
                    _debug(f"champ « {bas[a]} » lu comme « {canonique} »")
                    break
    return q


# ------------------------------------------------------------------ données du rubric
def _lire(nom_fichier):
    with open(_dossier_data() / "rubric" / nom_fichier, encoding="utf-8") as f:
        return json.load(f)


def libelle_niveau(niveau, langue):
    for n in _lire("criteria.json")["scale"]:
        if n["value"] == niveau:
            return n.get(langue) or n["de"]
    return str(niveau)


def libelle_critere(cle, langue):
    return criteres()[cle]["label"].get(langue) or criteres()[cle]["label"]["de"]


def regles_de_feedback():
    """Les règles de feedback pour adolescents (en anglais) sous forme de texte compact."""
    lignes = []
    for groupe in _lire("feedback_guidelines.json")["groups"]:
        for r in groupe["rules"]:
            lignes.append(f"{r['id']}: {r.get('en') or r.get('de')}")
    return "\n".join(lignes)


# ------------------------------------------------------------------ étape 1 : les niveaux (code)
def calculer_niveaux(entretien):
    """Moyenne des notes par critère sur tout l'entretien ; None si le critère n'a jamais été noté."""
    notes = {cle: [] for cle in criteres()}
    for tour in entretien:
        analyse = tour.get("analyse") or {}
        if not analyse.get("analyse_ok", True):
            continue
        for cle, note in (analyse.get("criteria_scores") or {}).items():
            if cle in notes and isinstance(note, (int, float)):
                notes[cle].append(note)
    return {cle: (int(sum(v) / len(v) + 0.5) if v else None) for cle, v in notes.items()}


def tours_candidats(entretien, cle, le_plus_faible):
    """Index des tours où citer l'élève pour ce critère, du plus indiqué au moins indiqué.

    Point à travailler : on préfère les tours notés 1 ou 2 (le plus faible d'abord).
    Point fort : on préfère les tours notés 3 ou 4 (le meilleur d'abord). À note égale, le plus tôt.
    S'il n'y a aucun tour du bon côté, on garde tous les tours notés pour ne jamais rester sans citation.
    """
    notes = []
    for i, tour in enumerate(entretien):
        analyse = tour.get("analyse") or {}
        note = (analyse.get("criteria_scores") or {}).get(cle)
        if analyse.get("analyse_ok", True) and isinstance(note, (int, float)):
            notes.append((note, i))
    bons = [(n, i) for n, i in notes if (n <= 2 if le_plus_faible else n >= 3)]
    liste = bons or notes
    liste.sort(key=(lambda x: (x[0], x[1])) if le_plus_faible else (lambda x: (-x[0], x[1])))
    return [i for _, i in liste]


def tour_extreme(entretien, cle, le_plus_faible):
    """Index du tour le plus indiqué pour ce critère (voir tours_candidats). None si jamais noté."""
    candidats = tours_candidats(entretien, cle, le_plus_faible)
    return candidats[0] if candidats else None


def attribuer_tours(entretien, fortes, faibles):
    """Donne un tour d'entretien à chaque critère retenu, en évitant de réutiliser le même tour.

    Les points à travailler passent d'abord, et dans chaque groupe les critères qui n'ont qu'un seul tour
    possible (ils n'ont pas le choix), puis les autres prennent leur meilleur tour encore libre. Si tous les tours possibles sont déjà pris, le critère
    garde son meilleur tour (deux citations différentes d'un même tour restent possibles).
    Renvoie {critère: index du tour}.
    """
    demandes = [(cle, True) for cle in faibles] + [(cle, False) for cle in fortes]
    options = {cle: tours_candidats(entretien, cle, faible) for cle, faible in demandes}
    pris, attribution = set(), {}
    # Les points à travailler passent avant les points forts ; dans chaque groupe, le moins de choix d'abord
    for cle, _ in sorted(demandes, key=lambda d: (not d[1], len(options[d[0]]))):   # tri stable
        if not options[cle]:
            continue
        libres = [i for i in options[cle] if i not in pris]
        attribution[cle] = (libres or options[cle])[0]
        pris.add(attribution[cle])
    return attribution


def choisir_candidats(niveaux):
    """Le CODE décide de quoi parler : jusqu'à 3 critères forts (niveau 3 ou 4) et 3 critères à travailler.

    Un critère à travailler a un niveau de 1 ou 2. Si tout est réussi, on garde quand même un seul point à
    travailler : le critère réussi le plus faible.
    """
    ordre = {cle: i for i, cle in enumerate(criteres())}
    notes = {cle: n for cle, n in niveaux.items() if n}
    fortes = sorted((c for c, n in notes.items() if n >= 3), key=lambda c: (-notes[c], ordre[c]))[:3]
    faibles = sorted((c for c, n in notes.items() if n <= 2), key=lambda c: (notes[c], ordre[c]))[:3]
    if not faibles and len(notes) >= 2:   # tout est réussi
        plus_faible = min(notes, key=lambda c: (notes[c], -ordre[c]))
        faibles = [plus_faible]
        fortes = [c for c in fortes if c != plus_faible]
    return fortes, faibles


# ------------------------------------------------------------------ étape 4 : vérifier les propositions (code)
def _normaliser(texte):
    texte = re.sub(r"[«»„“”\"'’]", "", texte.lower())
    return re.sub(r"\s+", " ", texte).strip()


def citation_valide(citation, entretien):
    """Vrai si la citation (ou chacun de ses morceaux séparés par …) figure dans les réponses de l'élève."""
    if not isinstance(citation, str) or not citation.strip():
        return False
    reponses = _normaliser(" ".join(t["reponse"] for t in entretien))
    morceaux = [m for m in re.split(r"…|\.\.\.", citation) if len(_normaliser(m)) >= 8]
    return bool(morceaux) and all(_normaliser(m) in reponses for m in morceaux)


_IGNORE = re.compile(r"[\s«»„“”\"'’]")


def _squelette(texte):
    """Texte sans espaces ni guillemets, en minuscules, avec la position de chaque lettre dans l'original."""
    cars, positions = [], []
    for i, c in enumerate(texte):
        if not _IGNORE.match(c):
            cars.append(c.lower())
            positions.append(i)
    return "".join(cars), positions


def retrouver_citation(citation, reponse):
    """Retrouve la citation dans la réponse de l'élève et renvoie l'extrait EXACT de l'original, ou None.

    Apertus recopie parfois mal (mots collés : « chemi piace »). On compare sans espaces, puis on rend le
    texte de l'élève tel qu'il l'a écrit : la citation affichée est donc toujours exacte.
    """
    if not isinstance(citation, str) or not citation.strip():
        return None
    brut, positions = _squelette(reponse)
    morceaux = [m for m in re.split(r"…|\.\.\.", citation) if len(_squelette(m)[0]) >= 8]
    if not morceaux:
        return None
    trouves = []
    for m in morceaux:
        sq = _squelette(m)[0]
        debut = brut.find(sq)
        if debut < 0:
            return None
        trouves.append(reponse[positions[debut]:positions[debut + len(sq) - 1] + 1].strip())
    return " … ".join(trouves)


def raccourcir_citation(citation, max_mots=25):
    """Une citation reste un extrait exact, mais courte : on garde les premières phrases (25 mots au plus)."""
    citation = citation.strip()
    gardees = []
    for phrase in re.split(r"(?<=[.!?])\s+", citation):
        if len(" ".join(gardees + [phrase]).split()) > max_mots:
            break
        gardees.append(phrase)
    if gardees:
        return " ".join(gardees)
    return " ".join(citation.split()[:max_mots]) + " …"


# Détection de l'anglais : Apertus écrit parfois la phrase ou le conseil en anglais malgré la consigne
MOTS_EN = {"the", "and", "your", "you", "with", "are", "that", "shows", "for", "this", "of", "to", "is",
           "lacks", "but", "like", "specific", "answer", "brief", "detail", "show", "clearly", "response",
           "provided", "about", "how", "what", "have", "has", "was", "were", "which"}
VERBES_EN = {"describe", "think", "tell", "write", "give", "try", "list", "name", "explain", "share",
             "imagine", "practice", "practise", "consider", "focus", "add", "mention", "include", "prepare"}


def est_anglais(texte):
    """Vrai si la phrase est visiblement en anglais (au moins 2 mots anglais courants, ou un verbe anglais en tête)."""
    mots = re.findall(r"[a-zA-Z']+", (texte or "").lower())
    if not mots:
        return False
    return len(set(mots) & MOTS_EN) >= 2 or mots[0] in VERBES_EN


def mentionne_autre_critere(texte, cle, langue):
    """Vrai si la phrase nomme un AUTRE critère que le sien (ex. « zeigt klare Motivation » sous Klarheit)."""
    t = (texte or "").lower()
    for autre in criteres():
        if autre == cle:
            continue
        etiquette = libelle_critere(autre, langue).lower().strip()
        if etiquette and etiquette in t:
            return True
    return False


def conseil_imperatif(conseil, langue):
    """Vrai si le conseil commence par un verbe à l'impératif (ni infinitif, ni article, ni groupe nominal)."""
    mots = re.findall(r"\w+", conseil or "")
    if not mots:
        return False
    premier = mots[0].lower()
    if premier in ARTICLES.get(langue, ()):
        return False
    return not premier.endswith(FIN_INFINITIF.get(langue, ()))


def resume_valide(texte, langue):
    """Vrai si le résumé s'adresse à l'élève (du / tu / hai…) : écarte les titres sans verbe ni adresse."""
    return bool(texte) and bool(re.search(PRONOMS.get(langue, PRONOMS["de"]), texte.lower()))


def verifier_proposition(p, cle, tour, niveaux, langue, est_faible, brouillons=None):
    """Renvoie la proposition nettoyée, ou None si elle est inutilisable (le code ne corrige jamais le fond).

    Si seule la phrase de comportement est inutilisable (anglais), la citation exacte est mise de côté dans
    `brouillons` : en dernier recours elle sera affichée seule, sans phrase.
    """
    p = normaliser_champs(p)
    exacte = retrouver_citation(p.get("evidence"), tour["reponse"])
    if exacte is None:
        _debug(cle, "REJET citation introuvable dans le tour visé :", repr(p.get("evidence")),
               "| champs reçus :", list(p.keys()), "| réponse du tour :", repr(tour["reponse"][:120]))
        return None
    tip = (p.get("tip") or "").strip() if isinstance(p.get("tip"), str) else ""
    if est_faible:
        if not tip:
            _debug(cle, "REJET conseil vide")
            return None
        if est_anglais(tip) or not conseil_imperatif(tip, langue):   # on garde la citation, conseil générique
            _debug(cle, "conseil en anglais ou pas à l'impératif, remplacé :", repr(tip))
            tip = TEXTES[langue]["conseil_generique"]
    rationale = p.get("rationale")
    mauvaise = None
    if not (isinstance(rationale, str) and rationale.strip()):
        mauvaise = "phrase de comportement vide"
    elif langue != "en" and est_anglais(rationale):
        mauvaise = "phrase de comportement en anglais"
    elif mentionne_autre_critere(rationale, cle, langue):
        mauvaise = "la phrase nomme un autre critère"
    if mauvaise:
        _debug(cle, "REJET", mauvaise, ":", repr(rationale))
        if brouillons is not None and mauvaise != "la phrase nomme un autre critère":
            brouillons[cle] = {"criterion": cle, "level": niveaux[cle], "evidence": raccourcir_citation(exacte),
                               "rationale": "", "tip": tip}
        return None
    return {"criterion": cle, "level": niveaux[cle], "evidence": raccourcir_citation(exacte),
            "rationale": rationale.strip(), "tip": tip}


# ------------------------------------------------------------------ prompts
def messages_criteres(entretien, fortes, faibles, niveaux, langue, consignes_profil, tours=None):
    tours = tours if tours is not None else attribuer_tours(entretien, fortes, faibles)
    retenus = []
    for role, liste in (("strength", fortes), ("development", faibles)):
        for cle in liste:
            tour = entretien[tours[cle]]
            retenus.append({"criterion": cle, "role": role, "level": niveaux[cle],
                            "meaning": criteres()[cle]["what_is_assessed"]["en"],
                            "question": tour["question"], "quote_from": tour["reponse"][:300]})
    nom_langue = LANGUES.get(langue, "German")
    systeme = (
        f"LANGUAGE RULE: the rationale and the tip MUST be written in {nom_langue}, NEVER in English. "
        "(The instructions below are in English, your answer is not.)\n"
        "You write the detailed part of the final feedback for a 14-16-year-old after a practice job "
        "interview for an apprenticeship. For EACH criterion of the list, using ONLY what the candidate "
        "really said:\n"
        "- evidence: an EXACT quote copied word for word from the text given in quote_from, ONE sentence "
        "if possible and at most 25 words (keep the original language of the quote). Use a different quote "
        "for each criterion;\n"
        "- rationale: ONE short sentence about the observed behaviour or answer, never about the person, "
        "no character labels. It must describe ONLY the quoted sentence and only this criterion: never "
        "name or mention another criterion, and never mention anything that is not in quote_from (no "
        "invented places, activities or facts). If role is strength, say concretely what worked. If role is "
        "development, say what is not yet visible in this answer (use 'not yet' rather than 'not');\n"
        "- tip: ONE concrete, doable thing to try next time, written as a direct instruction to the candidate. "
        f"It must START with a verb in the informal imperative (e.g. {IMPERATIVS.get(langue, IMPERATIVS['de'])}), "
        "never with an infinitive or a noun phrase, and not vague like "
        "'be more confident'. Never put "
        "words in the candidate's mouth and never invent experiences or example sentences: invite the "
        "candidate to think of a real situation of their own.\n"
        "The level of each criterion is given: do not change it. If you find no real quote for a "
        "criterion, set evidence to null.\n"
        f"Write rationale and tip in {LANGUES.get(langue, 'German')}, informal '{ADRESSE.get(langue, 'du')}', "
        "short and simple sentences, no exaggerated praise.\n"
        f"Feedback rules to follow:\n{regles_de_feedback()}\n"
        "Reply with ONE JSON object and nothing else: "
        '{"criteria": [{"criterion": "...", "evidence": "...", "rationale": "...", "tip": "..."}]}'
        + (f"\nAdditional care for this candidate: {consignes_profil}" if consignes_profil else "")
    )
    utilisateur = json.dumps({"write_rationale_and_tip_in": nom_langue, "criteria": retenus}, ensure_ascii=False)
    return [{"role": "system", "content": systeme}, {"role": "user", "content": utilisateur}]


def messages_resume(forces, travail, langue, consignes_profil):
    systeme = (
        "You write the closing of the final feedback for a 14-16-year-old after a practice job interview. "
        f"Write in {LANGUES.get(langue, 'German')}, informal '{ADRESSE.get(langue, 'du')}', short simple "
        "sentences, no exaggerated praise, no character labels, never create fear. Do not minimise the "
        "exercise (never 'only a test') and do not predict the future ('you will certainly...'). Write complete "
        "sentences with a verb that address the candidate directly, never a title or a list of nouns "
        "(praise ONLY what is listed under 'strengths'; anything under 'to_work_on' is NOT yet achieved: never "
        "say the candidate did it well, and the next step must be the tip of the FIRST item of 'to_work_on') "
        f"(pattern: '{EXEMPLE_RESUME.get(langue, EXEMPLE_RESUME['de'])}').\n"
        "Reply with ONE JSON object and nothing else: "
        '{"summary": "2-3 short sentences: start with what went well, referring to a concrete answer, '
        'then ONE concrete next step", '
        '"closing": "ONE encouraging sentence that stresses this was a practice round"}'
        + (f"\nAdditional care for this candidate: {consignes_profil}" if consignes_profil else "")
    )
    utilisateur = json.dumps({"strengths": forces, "to_work_on": travail}, ensure_ascii=False)
    return [{"role": "system", "content": systeme}, {"role": "user", "content": utilisateur}]


# ------------------------------------------------------------------ rendu du texte (code)
def finir_phrase(texte):
    """Ajoute un point final si le modèle a oublié la ponctuation."""
    texte = (texte or "").strip()
    return texte if not texte or texte[-1] in ".!?…" else texte + "."


def _ligne_force(c, langue):
    dp = TEXTES[langue]["dp"]
    return (f"- {libelle_critere(c['criterion'], langue)} ({libelle_niveau(c['level'], langue)}){dp} "
            f"« {c['evidence']} »" + (f" – {finir_phrase(c['rationale'])}" if c["rationale"] else ""))


def _ligne_travail(c, langue):
    t = TEXTES[langue]
    return (f"- {libelle_critere(c['criterion'], langue)}{t['dp']} « {c['evidence']} »"
            + (f" – {finir_phrase(c['rationale'])}" if c["rationale"] else "")
            + f"\n  {t['conseil']}{t['dp']} {finir_phrase(c['tip'])}")


def rendre_texte(resume, cloture, forces, travail, langue, avec_soutien):
    t = TEXTES[langue]
    blocs = [t["titre"]]
    if resume:
        blocs.append(resume)
    if forces:
        blocs.append(t["forces"] + "\n" + "\n".join(_ligne_force(c, langue) for c in forces))
    if travail:
        blocs.append(t["travail"] + "\n" + "\n".join(_ligne_travail(c, langue) for c in travail))
    if avec_soutien:
        blocs.append(t["soutien"])
    if cloture:
        blocs.append(cloture)
    return "\n\n".join(blocs)


def texte_de_secours(fortes, faibles, niveaux, langue, avec_soutien):
    """Si le modèle est en panne ou si aucune citation n'est valide : un bilan simple, sans citation, fait par le code."""
    t = TEXTES[langue]
    blocs = [t["titre"]]
    if fortes:
        blocs.append(t["forces"] + "\n" + "\n".join(
            f"- {libelle_critere(c, langue)} ({libelle_niveau(niveaux[c], langue)})" for c in fortes[:2]))
    if faibles:
        blocs.append(t["travail"] + "\n" + "\n".join(
            f"- {libelle_critere(c, langue)}\n  {t['conseil']}{t['dp']} {t['conseil_generique']}"
            for c in faibles[:1]))
    if avec_soutien:
        blocs.append(t["soutien"])
    blocs.append(t["fin_secours"])
    return "\n\n".join(blocs)


# ------------------------------------------------------------------ fonction principale
def generer_feedback(entretien, langue="de", appeler=None, consignes_profil=""):
    """entretien = [{"question": str, "reponse": str, "analyse": dict renvoyé par analyser()}, ...]

    Renvoie {"texte", "donnees", "appels", "avec_soutien"}.
    """
    if appeler is None:
        raise ValueError("Passe la fonction d'appel au modèle : generer_feedback(..., appeler=appeler_llm)")
    langue = langue if langue in TEXTES else "de"
    niveaux = calculer_niveaux(entretien)
    avec_soutien = any((t.get("analyse") or {}).get("coach_action") == "support_and_refer"
                       or "distress_signal" in ((t.get("analyse") or {}).get("problem_flags") or [])
                       for t in entretien)
    appels = 0

    if not any(niveaux.values()):
        texte = TEXTES[langue]["rien"] + (("\n\n" + TEXTES[langue]["soutien"]) if avec_soutien else "")
        return {"texte": texte, "donnees": {"niveaux": niveaux, "criteres": []},
                "appels": 0, "avec_soutien": avec_soutien}

    JOURNAL.clear()
    fortes, faibles = choisir_candidats(niveaux)
    tours = attribuer_tours(entretien, fortes, faibles)   # un tour différent par critère quand c'est possible

    verifies = {}
    brouillons = {}

    def demander(a_faire_fortes, a_faire_faibles):
        """Un appel au modèle pour ces critères ; le code vérifie chaque proposition et garde les bonnes."""
        nonlocal appels
        try:
            appels += 1
            brut = appeler(messages_criteres(entretien, a_faire_fortes, a_faire_faibles, niveaux, langue,
                                             consignes_profil, tours),
                           temperature=0.3, max_tokens=1200)
            propositions = lire_json(brut).get("criteria") or []
        except Exception as e:
            _debug("ERREUR pendant l'appel n°1/réparation :", repr(e))
            return
        _debug("réponse du modèle :", len(propositions), "critère(s) proposé(s) :",
               [p.get("criterion") for p in propositions if isinstance(p, dict)])
        for p in propositions:
            cle = p.get("criterion") if isinstance(p, dict) else None
            if cle in tours and cle not in verifies and (cle in a_faire_fortes or cle in a_faire_faibles):
                bon = verifier_proposition(p, cle, entretien[tours[cle]], niveaux, langue,
                                           est_faible=(cle in faibles), brouillons=brouillons)
                if bon:
                    verifies[cle] = bon

    # Appel n°1 : citation, comportement observé et conseil pour ces critères seulement (6 au plus)
    demander(fortes, faibles)

    # Appel de réparation (une seule fois) s'il ne reste pas assez de critères valides pour le bilan
    manque_forts = sum(c in verifies for c in fortes) < min(2, len(fortes))
    manque_faibles = sum(c in verifies for c in faibles) < min(2, len(faibles))
    if manque_forts or manque_faibles:
        demander([c for c in fortes if c not in verifies], [c for c in faibles if c not in verifies])

    for cle in fortes + faibles:   # dernier recours : citation exacte seule, sans phrase du modèle
        if cle not in verifies and cle in brouillons:
            verifies[cle] = brouillons[cle]
            _debug(cle, "affiché avec la citation seule (phrase du modèle inutilisable)")

    if not verifies and not os.environ.get("FEEDBACK_DEBUG"):   # anomalie : on dit pourquoi, sans rien demander
        for ligne in JOURNAL:
            print("[feedback]", ligne, file=sys.stderr)

    utilisees = set()

    def prendre(cles, n):
        """Prend n critères vérifiés, sans répéter deux fois la même citation."""
        choix = []
        for cle in cles:
            c = verifies.get(cle)
            if c and c["evidence"] not in utilisees:
                utilisees.add(c["evidence"])
                choix.append(c)
                if len(choix) == n:
                    break
        return choix

    # Les points à travailler choisissent d'abord leur citation : il y a plus de points forts de rechange
    travail = prendre(faibles, 2) or [verifies[k] for k in faibles if k in verifies][:1]
    forces = prendre(fortes, 2)
    criteres_ok = list(verifies.values())

    # Appel n°2 : résumé et phrase de fin
    resume = cloture = ""
    if forces or travail:
        try:
            appels += 1
            brut = appeler(messages_resume(forces, travail, langue, consignes_profil),
                           temperature=0.5, max_tokens=400)
            donnees = lire_json(brut)
            resume = finir_phrase(str(donnees.get("summary") or ""))
            cloture = finir_phrase(str(donnees.get("closing") or ""))
            if not resume_valide(resume, langue):   # titre sans verbe ni adresse : mieux vaut pas de résumé
                resume = ""
        except Exception as e:
            _debug("ERREUR pendant l'appel du résumé :", repr(e))

    if forces or travail:
        texte = rendre_texte(resume, cloture, forces, travail, langue, avec_soutien)
    else:
        texte = texte_de_secours(fortes, faibles, niveaux, langue, avec_soutien)
    return {"texte": texte,
            "donnees": {"niveaux": niveaux, "criteres": criteres_ok, "resume": resume, "cloture": cloture,
                           "rejets": list(JOURNAL)},
            "appels": appels, "avec_soutien": avec_soutien}