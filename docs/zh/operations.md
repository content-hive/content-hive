# 运维

## 升级

```bash
docker compose pull
docker compose up -d
```

## 备份

建议先停机再备份，保证 SQLite 一致性：

```bash
docker compose down
tar -czf content-hive-backup-$(date +%Y%m%d-%H%M%S).tar.gz ./data
```

备份内容至少应包含：
- `data/contenthive.db`
- `data/media/`
- `plugins/`
- `plugins/plugins.yaml`
- `logs/`（可选，但建议保留用于排障）

## 恢复 / 回滚

```bash
docker compose down
tar -xzf content-hive-backup-YYYYMMDD-HHMMSS.tar.gz
docker compose up -d
```

如需镜像版本回滚，可在 `docker-compose.yml` 中将镜像固定到已发布的历史版本标签（例如 `ghcr.io/content-hive/content-hive:1.2.3`），然后再次执行 `docker compose up -d`。CI/CD 由匹配 `v*` 的 Git tag 触发发布，镜像标签使用去掉 `v` 前缀后的版本号。

## 忘记 admin 密码

若唯一 admin 忘记密码且无法登录，可通过 CLI 在容器内重置（不经过 HTTP 接口）。

建议先停机，避免 SQLite 写锁冲突：

```bash
docker compose stop
docker compose run --rm content-hive contenthive admin reset-password --username admin
docker compose up -d
```

非交互式（脚本/自动化）：

```bash
docker compose run --rm content-hive contenthive admin reset-password \
  --username admin --password 'YourPassword123!'
```

说明：
- 仅可重置 `is_admin=true` 的用户
- 密码要求：≥8 位，包含大小写字母、数字和特殊字符（任意非字母数字字符，例如 `!@#$%^&*-_.`）
- 重置后会吊销该用户所有会话，旧 token 立即失效
- 省略 `--password` 时会交互式提示输入并确认
