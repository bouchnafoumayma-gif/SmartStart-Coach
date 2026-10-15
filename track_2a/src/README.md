# FHGR HackApertus Template 2026

This repository contains the basic setup for the FHGR Hackapertus Challenge 2026 with Aegra and the Agent Chat UI.

## Getting Started

This template uses the following dependencies:

- [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui)
- [Aegra CLI](https://github.com/aegra/aegra)

### 1. Install Agent Chat UI

Clone the Agent Chat UI repository into a **separate directory** from this project:

```bash
git clone https://github.com/langchain-ai/agent-chat-ui.git
cd agent-chat-ui
```

> **Note:** Do not use `npx` to install Agent Chat UI, as it currently installs an older version.

Install the dependencies:

```bash
pnpm install
```

Start the development server:

```bash
pnpm dev
```

### 2. Start Aegra

In a separate terminal, navigate to this project's directory and start the Aegra development server:

```bash
uv run aegra dev
```

Open the Agent Chat UI in your browser, change the port to `2026`, and click **Continue** to connect to your agent.

### Candidate profile form

Start the local form server from this directory:

```bash
uv run python form_server.py
```

Open <http://127.0.0.1:8090>. The form posts its profile to `POST /api/profile`, where it is validated with the same Pydantic contract used by the coach. Set `FORM_HOST` or `FORM_PORT` to change the bind address or port.

The endpoint currently validates and returns the normalized profile; it does not save it or start an interview. The form is intended to be connected to the chat flow in a follow-up step.

### Interview feedback view

Open <http://127.0.0.1:8090/feedback.html> to preview the feedback view. It renders the object returned by `generer_feedback()` (`texte`, `donnees`, `appels`, `avec_soutien`) and shows a clearly labeled example when no session result is present. The view accepts structured criteria and falls back to the plain-text `texte` value.

When the interview UI receives the real result from the backend, pass it to the view in the same browser origin:

```javascript
sessionStorage.setItem("smartstart.feedback", JSON.stringify({
	...feedbackResult,
	language: interviewConfig.language,
}));
window.location.assign("/feedback.html");
```

The feedback view is presentation-only; `main.py` still needs to call the interview and feedback nodes before this bridge can run end to end.

## Production

When you're ready to run Aegra in production mode, use:

```bash
uv run aegra up
```
