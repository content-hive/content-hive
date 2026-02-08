#!/bin/bash
set -e

# 获取环境变量中的 UID 和 GID,默认为 1000
PUID=${PUID:-1000}
PGID=${PGID:-1000}

# 创建必要的目录
mkdir -p /config/data /config/logs /config/plugins

# 如果是以 root 运行
if [ "$(id -u)" = "0" ]; then
    echo "Running as root, setting up contenthive user with PUID=${PUID} and PGID=${PGID}"
    
    # 创建组
    if ! getent group contenthive > /dev/null 2>&1; then
        groupadd -g ${PGID} contenthive 2>/dev/null || groupmod -g ${PGID} contenthive
    fi
    
    # 创建用户
    if ! id contenthive > /dev/null 2>&1; then
        useradd -m -u ${PUID} -g contenthive contenthive 2>/dev/null || usermod -u ${PUID} contenthive
    fi
    
    # 修改目录所有权
    chown -R ${PUID}:${PGID} /config /app
    
    # 使用 gosu 切换到非 root 用户
    exec gosu contenthive "$@"
else
    echo "Running as user $(id -u):$(id -g)"
    exec "$@"
fi