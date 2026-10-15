"""Client LLM unique (rôle 4) : la seule porte vers Apertus.
[version 3.1 : nouvelles tentatives + vérification du JSON + faux LLM + réglages]

Ce que fait le client :
  1. lit LLM_NAME, LLM_BASE_URL et LLM_API_KEY, sans valeur par défaut ;
  2. envoie une demande à Apertus et rend la réponse (texte, ou dict si un schéma JSON est donné) ;
  3. réessaie en cas de panne passagère (réseau, délai dépassé, HTTP 429/500/502/503/504) ;
  4. vérifie le JSON reçu et fait AU PLUS UNE demande de correction ;
  5. compte chaque requête envoyée (essais et corrections compris) ;
  6. ne journalise jamais le contenu des échanges (textes d'élèves).

Réglages optionnels : LLM_TIMEOUT (secondes, défaut 60) et LLM_MAX_RETRIES (défaut 2).

Faux LLM : si LLM_FAKE=1 (ou LLM_NAME=fake), get_llm() rend un client factice qui ne contacte
aucun serveur. Variable optionnelle LLM_FAKE_FAIL_EVERY=N : une requête sur N échoue.
NE JAMAIS activer le faux LLM pour la soumission.

Ne dépend que de la bibliothèque standard (le validateur JSON ci-dessous gère les schémas simples :
type, required, properties, items, enum, minimum, maximum).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

# Journal technique : étiquette, durée, tokens, statut. Jamais de prompt ni de réponse.
log = logging.getLogger("llm")

RETRYABLE_HTTP = {429, 500, 502, 503, 504}  # pannes passagères : on réessaie
DEFAULT_JSON_MAX_TOKENS = 500  # Apertus écrit beaucoup d'espaces : on garde de la marge


class LLMError(Exception):
    """Le modèle est injoignable, a refusé la demande ou a répondu de façon inutilisable."""


class LLMJSONError(LLMError):
    """La réponse n'est pas un JSON valide, même après la correction unique."""


def _need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LLMError(f"Variable d'environnement manquante : {name}")
    return value


def _int_env(name: str, default: int) -> int:
    """Lit un réglage numérique optionnel (ex. LLM_TIMEOUT). Valeur absente -> défaut."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise LLMError(f"{name} doit être un nombre entier, reçu : {raw!r}") from None
    if value < 0:
        raise LLMError(f"{name} ne peut pas être négatif")
    return value


# ---- vérification du JSON (stdlib uniquement) ------------------------------
_PY_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _validate(value, schema: dict, path: str = "réponse") -> list[str]:
    """Rend la liste des problèmes (vide si tout va bien). Les messages ne citent jamais les valeurs."""
    expected = schema.get("type")
    if isinstance(expected, str):
        if expected == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected in _PY_TYPES:
            ok = isinstance(value, _PY_TYPES[expected])
        else:
            ok = True  # type inconnu : on ne bloque pas
        if not ok:
            return [f"{path} : type attendu « {expected} »"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path} : valeur hors de la liste autorisée"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return [f"{path} : valeur trop petite"]
        if "maximum" in schema and value > schema["maximum"]:
            return [f"{path} : valeur trop grande"]
    errors: list[str] = []
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path} : champ « {name} » manquant")
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                errors += _validate(value[name], sub, f"{path}.{name}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errors += _validate(item, schema["items"], f"{path}[{i}]")
    return errors


def _parse_json(text: str, finish: str | None, schema: dict):
    """Rend (données, None) si tout va bien, sinon (None, description courte du problème)."""
    if finish == "length":
        return None, "réponse coupée (limite de tokens atteinte)"
    cleaned = (text or "").strip()
    openers = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not openers:
        return None, "aucun JSON trouvé dans la réponse"
    start = min(openers)  # ignore une phrase d'introduction ou les balises ```json
    end = cleaned.rfind("}" if cleaned[start] == "{" else "]")
    if end < start:
        return None, "JSON incomplet"
    try:
        data = json.loads(cleaned[start:end + 1])
    except ValueError:
        return None, "JSON illisible"
    errors = _validate(data, schema)
    if errors:
        return None, errors[0]
    return data, None


# ---- client -----------------------------------------------------------------
class LLMClient:
    def __init__(self, timeout: int = 60, max_retries: int = 2, retry_delay: float = 1.0):
        # Si un réglage manque, on s'arrête ici avec un message clair (aucune requête n'est partie).
        self.model = _need("LLM_NAME")
        self.base_url = _need("LLM_BASE_URL").rstrip("/")
        self._api_key = _need("LLM_API_KEY")
        # Réglables sans toucher au code : LLM_TIMEOUT (secondes) et LLM_MAX_RETRIES.
        self.timeout = _int_env("LLM_TIMEOUT", timeout) or timeout
        self.max_retries = _int_env("LLM_MAX_RETRIES", max_retries)  # 2 => jusqu'à 3 requêtes
        self.retry_delay = retry_delay  # attente de 1 s, puis 2 s...
        self._init_counters()

    # ---- compteurs ----
    def _init_counters(self) -> None:
        self._lock = threading.Lock()
        self._calls = 0
        self._by_tag: dict[str, int] = {}
        self._retries = 0
        self._repairs = 0
        self._json_failures = 0

    def stats(self) -> dict:
        """Copie des compteurs. `calls` = toutes les requêtes envoyées (essais et corrections inclus)."""
        with self._lock:
            return {"calls": self._calls, "by_tag": dict(self._by_tag), "retries": self._retries,
                    "repairs": self._repairs, "json_failures": self._json_failures}

    def reset_stats(self) -> None:
        with self._lock:
            self._calls, self._by_tag = 0, {}
            self._retries = self._repairs = self._json_failures = 0

    def _count(self, tag: str) -> None:
        with self._lock:
            self._calls += 1
            self._by_tag[tag] = self._by_tag.get(tag, 0) + 1

    def _bump(self, field: str) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)

    # ---- envoi d'une requête, avec nouvelles tentatives ----
    def _post(self, payload: dict, tag: str):
        """Rend (texte, finish_reason). Chaque requête partie est comptée, réussie ou non."""
        body = json.dumps(payload).encode("utf-8")
        last_problem = "Apertus ne répond pas"
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._bump("_retries")
                time.sleep(self.retry_delay * 2 ** (attempt - 1))
            self._count(tag)
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions", data=body, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            )
            started = time.time()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                choice = data["choices"][0]
                text = choice["message"]["content"] or ""
                finish = choice.get("finish_reason")
            except urllib.error.HTTPError as err:
                # On ne recopie pas le corps de l'erreur : il pourrait contenir le prompt.
                log.warning("tag=%s status=http_%s attempt=%d", tag, err.code, attempt + 1)
                if err.code in RETRYABLE_HTTP:
                    last_problem = f"Apertus a répondu avec le code HTTP {err.code}"
                    continue
                raise LLMError(f"Apertus a répondu avec le code HTTP {err.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                log.warning("tag=%s status=%s attempt=%d", tag, type(err).__name__, attempt + 1)
                last_problem = "Apertus ne répond pas (réseau ou délai dépassé)"
                continue
            except (ValueError, KeyError, IndexError, TypeError):
                log.warning("tag=%s status=bad_shape", tag)
                raise LLMError("Réponse d'Apertus inutilisable (forme inattendue)") from None
            tokens = (data.get("usage") or {}).get("total_tokens")
            log.info("tag=%s status=ok ms=%d tokens=%s", tag, (time.time() - started) * 1000, tokens)
            return text, finish
        raise LLMError(f"{last_problem} (après {self.max_retries + 1} essais)")

    # ---- appel principal ----
    def call(self, prompt: str | list[dict], *, json_schema: dict | None = None, tag: str = "misc",
             max_tokens: int | None = None, temperature: float | None = None):
        """Envoie `prompt` à Apertus. Rend un texte, ou un dict valide si `json_schema` est donné.

        `prompt` : un texte, ou une liste de messages [{"role": "system"|"user", "content": ...}].
        `tag` (« analyse », « relance », « feedback »...) sert uniquement au détail du compteur.
        Lève LLMError (panne) ou LLMJSONError (JSON invalide même après correction).
        """
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]
        payload = {"model": self.model, "messages": messages}
        if json_schema is None:
            if max_tokens:
                payload["max_tokens"] = max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            text, _ = self._post(payload, tag)
            return text

        payload.update(
            temperature=0.2 if temperature is None else temperature,
            max_tokens=max_tokens or DEFAULT_JSON_MAX_TOKENS,
            response_format={"type": "json_schema", "json_schema": {"name": "reponse", "schema": json_schema}},
        )
        text, finish = self._post(payload, tag)
        data, problem = _parse_json(text, finish, json_schema)
        if problem is None:
            return data

        # Une seule demande de correction, comptée comme un appel.
        self._bump("_repairs")
        repair = dict(payload, temperature=0, messages=[{"role": "user", "content": (
            f"Ta réponse précédente ne respecte pas le format demandé ({problem}). "
            "Réponds uniquement avec le JSON corrigé, sans aucun texte autour.\n"
            f"Schéma attendu : {json.dumps(json_schema, ensure_ascii=False)}\n"
            f"Réponse à corriger :\n{text}")}])
        text, finish = self._post(repair, f"{tag}_repair")
        data, problem = _parse_json(text, finish, json_schema)
        if problem is None:
            return data
        self._bump("_json_failures")
        raise LLMJSONError(f"JSON invalide après une correction ({problem})")


# ---- faux LLM -----------------------------------------------------------
def _fake_value(schema: dict):
    """Fabrique une valeur minimale qui respecte un schéma JSON simple."""
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    kind = schema.get("type")
    if kind == "object":
        return {name: _fake_value(sub) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        items = schema.get("items")
        return [_fake_value(items)] if items and schema.get("minItems", 0) > 0 else []
    if kind == "integer":
        return int(schema.get("minimum", 1))
    if kind == "number":
        return float(schema.get("minimum", 1))
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return "exemple"  # string et cas inconnus


class FakeLLMClient(LLMClient):
    """Remplace Apertus pendant le développement : aucune connexion, mêmes compteurs."""

    def __init__(self, fail_every: int = 0):
        self.model = "fake"
        self.timeout = 0
        self.fail_every = fail_every
        self._init_counters()
        log.warning("MODE FAKE ACTIF : aucune requête n'est envoyée à Apertus")

    def call(self, prompt: str | list[dict], *, json_schema: dict | None = None, tag: str = "misc",
             max_tokens: int | None = None, temperature: float | None = None):
        self._count(tag)
        if self.fail_every and self._calls % self.fail_every == 0:
            raise LLMError("Échec simulé par le faux LLM")
        if json_schema is None:
            return f"[FAKE] Réponse simulée ({tag})."
        return _fake_value(json_schema)


# Accès simple pour les autres rôles : `from llm_client import get_llm`.
_client: LLMClient | None = None


def get_llm() -> LLMClient:
    """Crée le client au premier usage (l'import seul ne plante pas si un réglage manque)."""
    global _client
    if _client is None:
        if os.environ.get("LLM_FAKE") == "1" or os.environ.get("LLM_NAME") == "fake":
            _client = FakeLLMClient(int(os.environ.get("LLM_FAKE_FAIL_EVERY", "0") or 0))
        else:
            _client = LLMClient()
    return _client