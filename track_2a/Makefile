.PHONY: run stop

# Lance tout le projet dans Docker : le site de l'élève sur http://localhost:8090
# et l'API de l'agent (+ PostgreSQL + Redis) sur http://localhost:2026.
# Les réglages LLM_NAME, LLM_BASE_URL et LLM_API_KEY viennent du shell ou de src/.env.
run:
	cd src && docker compose up --build

stop:
	cd src && docker compose down
