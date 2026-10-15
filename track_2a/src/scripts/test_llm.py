"""Test de connexion à Apertus (rôle 4) - version 2.
Ne dépend que de la bibliothèque standard. N'affiche jamais la clé API.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Charge un fichier .env simple, sans écraser les variables déjà définies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERREUR : variable manquante : {name}")
        sys.exit(1)
    return value


def post_chat(base_url: str, api_key: str, payload: dict, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print("=== test_llm.py version 2 ===")
    load_dotenv(Path(".env"))
    model, base_url, api_key = need("LLM_NAME"), need("LLM_BASE_URL"), need("LLM_API_KEY")
    print(f"Modèle demandé : {model}\nAdresse : {base_url}\n")

    # Test 1 : une phrase simple
    print("Test 1 : réponse en texte libre")
    started = time.time()
    try:
        data = post_chat(base_url, api_key, {
            "model": model,
            "messages": [{"role": "user", "content": "Sag Hallo auf Deutsch, in einem kurzen Satz."}],
            "max_tokens": 50,
        })
    except urllib.error.HTTPError as err:
        print(f"ECHEC : le serveur a répondu {err.code} ({err.reason})")
        return 1
    except Exception as err:  # réseau, délai dépassé, adresse fausse...
        print(f"ECHEC : {type(err).__name__} : {err}")
        return 1
    elapsed = time.time() - started
    try:
        print("Réponse :", data["choices"][0]["message"]["content"].strip())
    except (KeyError, IndexError, TypeError):
        print("ECHEC : la réponse n'a pas la forme OpenAI attendue (choices/message/content).")
        return 1
    print("Modèle déclaré par le serveur :", data.get("model"))
    print("Détail tokens :", data.get("usage"))
    print(f"Durée : {elapsed:.1f} s\n")

    # Test 2 : réponse imposée sous forme de fiche (JSON)
    print("Test 2 : format JSON imposé (décodage guidé)")
    schema = {
        "type": "object",
        "properties": {"niveau": {"type": "integer"}, "vague": {"type": "boolean"}},
        "required": ["niveau", "vague"],
    }
    content = ""
    finish = None
    try:
        data = post_chat(base_url, api_key, {
            "model": model,
            "messages": [{"role": "user", "content":
                          "Évalue cette réponse d'élève de 1 à 4 : « parce que j'aime bien ça »."}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "analyse", "schema": schema}},
            "max_tokens": 300,
        })
        content = data["choices"][0]["message"]["content"]
        finish = data["choices"][0].get("finish_reason")
        json.loads(content)
        print("OK : le serveur accepte le format JSON imposé. Contenu :", content.strip())
    except urllib.error.HTTPError as err:
        print(f"Non pris en charge (code {err.code}). Le client devra valider le JSON lui-même.")
    except (ValueError, KeyError, IndexError, TypeError):
        print("Accepté mais le contenu n'est pas du JSON valide : validation côté client nécessaire.")
        print("Contenu brut reçu :", repr(content))
        print("Raison d'arrêt (finish_reason) :", finish)
    except Exception as err:
        print(f"Test 2 non concluant : {type(err).__name__} : {err}")

    print("\nFin du test (le test 1 a réussi : le modèle répond).")
    return 0


if __name__ == "__main__":
    sys.exit(main())