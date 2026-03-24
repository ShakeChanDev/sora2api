# 文档索引

## 当前仓库文档

- [NSTBrowser 官方 API 与自动化文档整理](./nstbrowser-api-automation.md)

## 研究文档

- [2026-03-20 视频真实轮询观测与 PollingClient 差异](./research/sora-video-polling-observation-2026-03-20.md)
  - 当前实现已按该文档结论切到 `drafts/v2`，并改为依赖 `browser_profile_id + token.proxy_url` 绑定约束

## 导入文档

- [api-docs 导入说明](./imported/api-docs/README.md)
- [VidenX Backend 视频供应商链路参考](./imported/videnx-backend/README.md)

## 说明

- `docs/imported/api-docs/` 下的文件按上游仓库原文件名导入，便于后续比对和再次同步。
- 部分导入文档来自其它项目上下文，存在 `app/...`、`docs/architecture.md`、`docs/research/...` 等跨仓库引用；这些内容在当前仓库中应视为参考资料，而不是当前实现契约。
