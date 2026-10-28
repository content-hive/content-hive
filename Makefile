VERSION ?= $(shell grep '^APP_VERSION' .env | cut -d= -f2)

# Alembic downgrade target. Examples: make db-downgrade, make db-downgrade STEPS=-2
STEPS ?= -1

.PHONY: up
up:
	uv version $(VERSION)
	uv lock
	APP_VERSION=$(VERSION) docker compose up --build -d


.PHONY: down
down:
	docker compose down


.PHONY: db-downgrade
db-downgrade:
	docker compose exec content-hive alembic downgrade $(STEPS)
