# Configuration

Deployment settings are configured via environment variables. Application settings that can be changed at runtime are stored in `/config/settings.yaml` and can also be managed via `GET/PUT /v1/system/settings` (admin only).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `6123` | Server port |
| `TZ` | `Asia/Shanghai` | Container timezone |
| `DATA_DIR` | `/config/data` | Directory for database and media files |
| `LOGS_DIR` | `/config/logs` | Directory for log files |
| `PLUGINS_DIR` | `/config/plugins` | Directory for installed plugins |
| `PLUGINS_DEPS_DIR` | `/app/deps` | Directory for plugin dependency installation |

## Runtime Settings (settings.yaml)

On first start, default values are written to `/config/settings.yaml`.

**Via API** (`PUT /v1/system/settings`): No container restart required. Changes are written to disk and the in-memory cache is updated immediately. Some settings take effect on next use (e.g. the next download or token issuance).

**Editing the file directly**: `GET /v1/system/settings` reads from disk on every request, so you can see file changes immediately. Internal paths (downloads, tokens, plugin repo, etc.) use an in-memory cache loaded at startup; after editing the file directly, **restart the container** for those paths to pick up changes. Prefer the API when possible.

```yaml
plugins:
  repo_url: https://github.com/content-hive/plugins.git
  repo_ref_type: branch   # branch | tag | commit
  repo_ref: release

auth:
  access_token_expire_minutes: 60
  refresh_token_expire_days: 30

download:
  max_retries: 3
  user_agent: >-
    Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
    (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0
```

| Setting | Default | Description |
|---------|---------|-------------|
| `plugins.repo_url` | `https://github.com/content-hive/plugins.git` | Plugin distribution repository. Verify repository trust before changing |
| `plugins.repo_ref_type` | `branch` | Repository ref type: `branch`, `tag`, or `commit` |
| `plugins.repo_ref` | `release` | Repository ref value. `release` = Stable (default), `main` = Beta |
| `auth.access_token_expire_minutes` | `60` | Access token validity in minutes |
| `auth.refresh_token_expire_days` | `30` | Refresh token validity in days |
| `download.max_retries` | `3` | Maximum retries for media download failures |
| `download.user_agent` | *(see above)* | HTTP User-Agent used for media downloads |

### API Example

```bash
# Read current settings
curl -s "$BASE_URL/v1/system/settings" -H "Authorization: Bearer ACCESS_TOKEN"

# Partial update (nested structure)
curl -s -X PUT "$BASE_URL/v1/system/settings" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download": { "max_retries": 5 },
    "auth": { "access_token_expire_minutes": 120 }
  }'
```

The response `data` field is the full nested settings object (`plugins` / `auth` / `download`).

### Migrating from Previous Versions

If you previously customized these values via environment variables such as `PLUGINS_REPO_REF`, `PLUGINS_REPO_REF_TYPE`, or `ACCESS_TOKEN_EXPIRE_MINUTES`, write them into `/config/settings.yaml` after upgrading. Those environment variables are no longer read.

## Persistent Data

The `/config` volume contains all persistent data:

```
/config/
  settings.yaml         # Application runtime settings
  data/
    contenthive.db      # SQLite database
    media/              # Downloaded media files
  logs/                 # Rotating log files
  plugins/              # Installed plugin directories
    plugins.yaml        # Plugin enable/disable state and configuration
```
