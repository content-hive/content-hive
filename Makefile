VERSION ?= $(shell grep '^APP_VERSION' .env | cut -d= -f2)

.PHONY: up
up:
	uv version $(VERSION)
	uv lock
	APP_VERSION=$(VERSION) docker compose up --build -d


.PHONY: down
down:
	docker compose down
