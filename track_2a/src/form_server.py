"""Local web server for the candidate profile form."""

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.coach.schemas import InterviewConfig


FORM_DIRECTORY = Path(__file__).parent / "form"
MAX_REQUEST_BYTES = 16_384
# Agent Aegra : la page chat.html lui parle via /agent/... (même origine, pas de souci CORS).
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:2026").rstrip("/")
AGENT_TIMEOUT = 300  # un tour = 2 appels à Apertus, le feedback final en fait plus


def validate_form_config(payload: Any) -> dict:
    """Validate and remove fields that are not part of the interview contract."""
    if not isinstance(payload, dict):
        raise ValueError("Le formulaire doit envoyer un objet JSON.")
    return InterviewConfig.model_validate(payload).model_dump(
        mode="json", exclude_none=True
    )


class FormRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FORM_DIRECTORY), **kwargs)

    def do_POST(self):
        if self.path.startswith("/agent/"):
            self._proxy_to_agent()
            return
        if self.path != "/api/profile":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Taille de requête invalide."})
            return

        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "La requête est vide ou trop volumineuse."})
            return

        try:
            raw_payload = json.loads(self.rfile.read(content_length))
            config = validate_form_config(raw_payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "Le corps doit être un JSON valide."})
            return
        except ValidationError as error:
            details = [
                {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                for item in error.errors()
            ]
            self._send_json(422, {"error": "Certains champs sont invalides.", "details": details})
            return
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return

        self._send_json(200, {"config": config, "source": "profile"})

    def _proxy_to_agent(self) -> None:
        """Transmet POST /agent/<chemin> à l'API Aegra et renvoie sa réponse telle quelle."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "La requête est trop volumineuse."})
            return
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        request = urllib.request.Request(
            AGENT_URL + self.path[len("/agent"):], data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=AGENT_TIMEOUT) as response:
                status, payload = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, payload = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            self._send_json(502, {"error": "L'agent ne répond pas. Vérifie qu'il est lancé (port 2026)."})
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: dict) -> None:
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response)


def main() -> None:
    host = os.getenv("FORM_HOST", "127.0.0.1")
    port = int(os.getenv("FORM_PORT", "8090"))
    server = ThreadingHTTPServer((host, port), FormRequestHandler)
    print(f"Formulaire disponible sur http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()