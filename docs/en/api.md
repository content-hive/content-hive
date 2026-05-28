# API

Interactive API documentation is available at `http://localhost:6123/docs` (Swagger UI).

| Prefix | Description |
|--------|-------------|
| `/v1/task` | Submit URLs for parsing, check task status, cancel tasks |
| `/v1/content` | Query parsed content, list platforms and authors |
| `/v1/plugins` | Manage plugins (install, update, configure, enable/disable) |
| `/v1/user` | User login, token refresh, profile, and password change |
| `/v1/admin` | Admin-only: user management |
| `/v1/system` | Health check, storage stats, log viewer, application restart |

Note: `/v1/user/token` is an OAuth2 compatibility endpoint and returns `{ "access_token": "...", "token_type": "bearer" }` directly instead of the unified `APIResponse` envelope.

## Minimal API Workflow Examples

Set a base URL:

```bash
BASE_URL="http://localhost:6123"
```

1) Login and get tokens:

```bash
curl -s -X POST "$BASE_URL/v1/user/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "YourPassword123!"
  }'
```

2) Submit a parser task (replace `ACCESS_TOKEN`):

```bash
curl -s -X POST "$BASE_URL/v1/task/parser" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://x.com/example/status/1234567890"
  }'
```

3) Query a task by task ID (replace `TASK_ID`):

```bash
curl -s -X GET "$BASE_URL/v1/task/parser/TASK_ID" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

4) Health check:

```bash
curl -s "$BASE_URL/v1/system/health"
```

## Error Code Quick Reference

| Code | Typical HTTP Status | Where | Meaning / Action |
|------|---------------------|-------|------------------|
| `AUTHENTICATION_FAILED` | `401` | `/v1/user/login` | Invalid username/password; verify credentials and account status |
| `INVALID_CREDENTIALS` | `401` | Auth dependencies | Token invalid or expired; login again and refresh token |
| `TASK_NOT_FOUND` | `404` | `/v1/task/*` | Task ID not found or not visible to current user |
| `TASK_CREATION_FAILED` | `500` | `/v1/task/parser` | Task creation failed on server side; check logs |
| `INVALID_CURSOR` | `400` | `/v1/task/parser/cursor`, `/v1/system/logs` | Cursor is malformed or expired; restart from first page |
| `PLUGIN_NOT_FOUND` | `404` | `/v1/plugins/{domain}/*` | Plugin domain not installed |
| `CONFIG_VALIDATION_FAILED` | `400` | `/v1/plugins/{domain}/config` | Submitted plugin config violates schema |
| `STORAGE_STATUS_FAILED` | `500` | `/v1/system/storage` | Storage statistics collection failed; check filesystem and logs |
| `INVALID_TIME_RANGE` | `400` | `/v1/system/logs` | `from` must be before `to` |
| `LOG_READ_FAILED` | `500` | `/v1/system/logs` | Log file cannot be parsed or read |
| `USER_CREATION_FAILED` | `400` | `/v1/admin/users` | User create request invalid (duplicate username/password policy, etc.) |
| `ADMIN_PRIVILEGES_REQUIRED` | `403` | Admin-protected endpoints | Current user is not admin |
