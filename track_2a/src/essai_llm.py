"""Essai : envoyer un message à Apertus depuis Python."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()  # lit LLM_NAME, LLM_BASE_URL, LLM_API_KEY dans .env


def appeler_llm(messages, temperature=0.3, max_tokens=400):
    reponse = httpx.post(
        os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        json={
            "model": os.environ["LLM_NAME"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    reponse.raise_for_status()
    return reponse.json()["choices"][0]["message"]["content"]


if __name__ == "__main__":
    texte = appeler_llm([
        {"role": "system",
         "content": "Du bist ein freundlicher Ausbilder in einem Schweizer Betrieb. "
                    "Du führst ein Vorstellungsgespräch mit einer 15-jährigen Person. "
                    "Sprich sie mit 'du' an. Antworte in höchstens zwei kurzen Sätzen."},
        {"role": "user", "content": "Hallo, ich bin hier für das Gespräch."},
    ])
    print(texte)