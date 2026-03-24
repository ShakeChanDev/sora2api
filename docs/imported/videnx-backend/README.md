# VidenX Backend 参考代码导入说明

这批文件从 `https://github.com/videnx/backend` 导入到当前仓库，目的是把与“外部视频供应商 `/videos` 兼容接入”直接相关的后端实现沉淀到本地，方便后续检索、对照和设计兼容层。

- 来源仓库：<https://github.com/videnx/backend>
- 来源提交：`8138de6d2e0c55665f98ddd3ddc76139a776e068`
- 导入日期：`2026-03-24`
- 落库路径：`docs/imported/videnx-backend/`
- 导入策略：保留上游相对路径，仅导入与视频任务创建、供应商选择、Polo 兼容调用、轮询状态回收、任务 DTO/实体相关的代码快照

## 当前导入范围

- `src/module/common/api/`
  - `polo.api.ts`
  - `dayangyu.web.api.ts`
  - `sorarpa.api.ts`
  - `sora.web.api.ts`
  - `api.interface.ts`
- `src/module/task/`
  - `provider/video.provider.ts`
  - `runner/video/*`
  - `runner/runner.interface.ts`
  - `task.module.ts`
  - `task.service.ts`
- `src/module/api/`
  - `api.module.ts`
  - `public-api.module.ts`
  - `controller/public/task.controller.ts`
  - `services/task.service.ts`
  - `dto/task.dto.ts`
- `src/entity/`
  - `task.entity.ts`
  - `task-group.entity.ts`
  - `video-artifact.entity.ts`
  - `media-resource.entity.ts`
- `docs/`
  - `技术入门指南.md`

## 使用边界

- 本目录是上游实现快照，供参考，不参与当前仓库运行时构建。
- 上游代码仍然保留 NestJS、TypeORM、路径别名（如 `@/src/...`）等原始上下文，不能直接在当前仓库运行。
- 其中最关键的参考链路是：
  - `src/module/api/api.module.ts` / `public-api.module.ts`：公开任务路由挂载关系
  - `src/module/common/api/polo.api.ts`：Polo `/videos` 兼容客户端
  - `src/module/task/provider/video.provider.ts`：多供应商统一封装与状态归一
  - `src/module/task/runner/video/*.ts`：创建、轮询、重试与完成链路
  - `src/module/api/controller/public/task.controller.ts`：对外任务入口
