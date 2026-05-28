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
