---
layout: home

hero:
  name: "Content Hive"
  text: "插件化内容解析服务"
  tagline: 自托管，支持多平台，无需重启即可扩展
  actions:
    - theme: brand
      text: 快速上手
      link: /zh/getting-started
    - theme: alt
      text: 插件开发
      link: /zh/plugins

features:
  - title: 插件化架构
    details: 每个平台（Twitter、YouTube、TikTok、小红书等）是独立插件，通过 GitHub 仓库分发，支持热重载，无需重启服务。
  - title: 任务去重机制
    details: 多用户同时提交相同 URL 时，解析只执行一次，后续请求自动共享 PRIMARY 任务的结果。
  - title: 异步任务队列
    details: 基于优先级队列并发执行，同优先级按 FIFO 处理，最大并发数可配置，未开始的任务支持取消。
  - title: 媒体文件管理
    details: 自动下载每个媒体项，按结构化路径存储，MIME 类型自动检测，视频封面图自动提取。
  - title: 多用户支持
    details: 每个用户的内容、任务历史和订阅均独立隔离，采用短期 access token + 长期 refresh token 双令牌认证。
  - title: 插件管理 API
    details: 通过 REST API 安装、更新、启用/禁用、配置插件。版本检查只拉取远端 manifest，不下载完整包。
---
