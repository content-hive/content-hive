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
