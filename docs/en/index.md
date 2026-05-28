---
layout: home

hero:
  name: "Content Hive"
  text: "Plugin-driven Content Parsing"
  tagline: Self-hosted, multi-platform, extensible without restarts
  actions:
    - theme: brand
      text: Get Started
      link: /en/getting-started
    - theme: alt
      text: Plugin Development
      link: /en/plugins

features:
  - title: Plugin-driven Architecture
    details: Each platform (Twitter, YouTube, TikTok, etc.) is an independent plugin distributed via GitHub, supporting hot-reload without restarting the service.
  - title: Task Deduplication
    details: When the same URL is submitted by multiple users, parsing runs only once. Subsequent requests automatically share the PRIMARY task's result.
  - title: Async Task Queue
    details: Priority-based concurrent execution with FIFO ordering within the same priority. Configurable concurrency limit; pending tasks can be cancelled.
  - title: Media Download
    details: Automatically downloads every media item to a structured local path. MIME types are detected automatically; video thumbnails are extracted.
  - title: Multi-user Support
    details: Each user has isolated content, task history, and subscriptions. Authentication uses short-lived access tokens and long-lived refresh tokens.
  - title: Plugin Management API
    details: Install, update, enable/disable, and configure plugins via REST API. Version checks fetch only the remote manifest — not the full package.
---
