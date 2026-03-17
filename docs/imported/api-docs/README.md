# api-docs 导入说明

这些资料从上游文档仓库导入到当前项目，目的是把分散在外部仓库的链路说明、外部依赖速查和存储设计稿沉淀到本仓库，方便本地检索和后续维护。

- 来源仓库：<https://github.com/ShakeChanDev/api-docs>
- 来源提交：`36f8baf`
- 导入日期：`2026-03-17`
- 落库路径：`docs/imported/api-docs/`
- 导入策略：保留原文件名和主体内容，不改写为当前仓库的正式接口契约

## 使用边界

- `sora2api-task-chain.md`、`sora-observed-web-api.md` 与当前项目关联最直接，可作为 Sora 上游链路参考。
- `camoufox-reference.md`、`ixbrowser-local-api.md`、`adspower-local-api.md`、`receipt-plus-bind-api.md` 主要是外部工具或外围链路资料。
- `rpasora-api.md` 以及部分文档中的 `app/...`、`docs/architecture.md`、`docs/research/...` 引用来自原始上下文，当前仓库不一定存在对应文件。
- `webshare-proxy-core-schema.sql` 和 `webshare-proxy-core-storage.md` 是存储设计稿，不会自动接入当前项目现有 SQLite 结构。
- 本目录是导入副本，不会自动跟踪上游仓库更新；如需重新同步，请运行 `python scripts/import_api_docs.py`。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| [adspower-local-api.md](./adspower-local-api.md) | AdsPower Local API 参考 |
| [camoufox-reference.md](./camoufox-reference.md) | Camoufox 官方资料整理 |
| [ixbrowser-local-api.md](./ixbrowser-local-api.md) | ixBrowser Local API 速查 |
| [receipt-plus-bind-api.md](./receipt-plus-bind-api.md) | Receipt Plus 绑定链路参考 |
| [rpasora-api.md](./rpasora-api.md) | 历史 rpaSora 接口快照 |
| [sora-observed-web-api.md](./sora-observed-web-api.md) | Sora Web 侧观测接口速查 |
| [sora2api-task-chain.md](./sora2api-task-chain.md) | `sora2api` 图片/视频任务链路拆解 |
| [webshare-proxy-core-schema.sql](./webshare-proxy-core-schema.sql) | Webshare 代理核心存储 DDL |
| [webshare-proxy-core-storage.md](./webshare-proxy-core-storage.md) | Webshare 代理核心落库方案 |
