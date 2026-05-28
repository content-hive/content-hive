import { defineConfig } from 'vitepress'

export default defineConfig({
  title: "Content Hive",
  description: "Content Hive service docs",
  base: '/content-hive/',

  locales: {
    zh: {
      label: '中文',
      lang: 'zh-CN',
      link: '/zh/',
      themeConfig: {
        nav: [
          { text: '首页', link: '/zh/' },
          { text: '文档', link: '/zh/intro' },
        ],
        sidebar: [
          {
            text: '入门',
            items: [
              { text: '项目简介', link: '/zh/intro' },
              { text: '快速开始', link: '/zh/getting-started' },
              { text: '配置项', link: '/zh/configuration' },
            ]
          },
          {
            text: 'API & 运维',
            items: [
              { text: 'API 文档', link: '/zh/api' },
              { text: '运维', link: '/zh/operations' },
            ]
          },
          {
            text: '插件',
            items: [
              { text: '插件开发者指南', link: '/zh/plugins' },
              { text: '插件系统设计', link: '/zh/plugin-system' },
            ]
          },
        ],
      }
    },
    en: {
      label: 'English',
      lang: 'en-US',
      link: '/en/',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Docs', link: '/en/intro' },
        ],
        sidebar: [
          {
            text: 'Getting Started',
            items: [
              { text: 'Introduction', link: '/en/intro' },
              { text: 'Quick Start', link: '/en/getting-started' },
              { text: 'Configuration', link: '/en/configuration' },
            ]
          },
          {
            text: 'API & Operations',
            items: [
              { text: 'API', link: '/en/api' },
              { text: 'Operations', link: '/en/operations' },
            ]
          },
          {
            text: 'Plugins',
            items: [
              { text: 'Plugin Developer Guide', link: '/en/plugins' },
              { text: 'Plugin System Design', link: '/en/plugin-system' },
            ]
          },
        ],
      }
    },
  },

  themeConfig: {
    socialLinks: [
      { icon: 'github', link: 'https://github.com/content-hive/content-hive' }
    ]
  }
})
