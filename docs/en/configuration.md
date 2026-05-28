# Configuration

All settings are configured via environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `6123` | Server port |
| `TZ` | `Asia/Shanghai` | Container timezone |
| `ENVIRONMENT` | `production` | Runtime environment (`production` / `development`) |
| `DEBUG` | `false` | Enable debug logging |
| `ADMIN_PASSWORD` | *(auto-generated)* | Admin account password on first start. Must be ≥8 chars with uppercase, lowercase, digit, and special character. |
| `DATA_DIR` | `/config/data` | Directory for database and media files |
| `LOGS_DIR` | `/config/logs` | Directory for log files |
| `PLUGINS_DIR` | `/config/plugins` | Directory for installed plugins |
| `PLUGINS_DEPS_DIR` | `/app/deps` | Directory for plugin dependency installation |
| `PLUGINS_REPO_URL` | `https://github.com/content-hive/plugins.git` | Plugin distribution repository |
| `PLUGINS_REPO_REF_TYPE` | `branch` | Repository ref type: `branch`, `tag`, or `commit` |
| `PLUGINS_REPO_REF` | `main` | Repository ref value |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token validity in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token validity in days |
| `DOWNLOAD_MAX_RETRIES` | `3` | Maximum retries for media download failures |
| `DOWNLOAD_USER_AGENT` | built-in browser UA string | HTTP User-Agent used for media download requests |

## Persistent Data

The `/config` volume contains all persistent data:

```
/config/
  data/
    contenthive.db      # SQLite database
    media/              # Downloaded media files
  logs/                 # Rotating log files
  plugins/              # Installed plugin directories
    plugins.yaml        # Plugin enable/disable state and configuration
```
