# Operations

## Upgrade

```bash
docker compose pull
docker compose up -d
```

## Backup

Stop the service first to ensure SQLite consistency:

```bash
docker compose down
tar -czf content-hive-backup-$(date +%Y%m%d-%H%M%S).tar.gz ./data
```

Backup should include at least:
- `data/contenthive.db`
- `data/media/`
- `plugins/`
- `plugins/plugins.yaml`
- `logs/` (optional, but useful for troubleshooting)

## Restore / Rollback

```bash
docker compose down
tar -xzf content-hive-backup-YYYYMMDD-HHMMSS.tar.gz
docker compose up -d
```

For image rollback, pin a previously released version tag in `docker-compose.yml` (for example `ghcr.io/content-hive/content-hive:1.2.3`) and run `docker compose up -d` again. Release tags are produced from Git tags matching `v*` in CI/CD.

## Forgotten admin password

If the only admin cannot log in, reset the password via CLI inside the container (no HTTP endpoint).

Stopping the service first is recommended to avoid SQLite write-lock contention:

```bash
docker compose stop
docker compose run --rm content-hive contenthive admin reset-password --username admin
docker compose up -d
```

Non-interactive (scripts/automation):

```bash
docker compose run --rm content-hive contenthive admin reset-password \
  --username admin --password 'YourPassword123!'
```

Notes:
- Only users with `is_admin=true` can be reset
- Password requirements: ≥8 characters with uppercase, lowercase, digit, and a special character (any non-alphanumeric, e.g. `!@#$%^&*-_.`)
- All sessions for that user are revoked; existing tokens stop working immediately
- Omit `--password` to be prompted interactively with confirmation
