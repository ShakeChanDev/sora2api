# Sora2API References 功能需求

## 目标

为 Sora2API 增加 Sora `references` 能力，支持调用方在视频生成时附带已有 `reference_id`，并在管理端维护 reference 的增删改查，保证实现与 Sora Web 实际请求结构一致。

## 用户价值

- 开发者可复用已创建的角色、场景、风格参考，提高多次生成的一致性。
- 运营人员可在管理端维护 reference 库，而不是每次重复上传素材。

## 本期范围

- 支持普通视频生成、分镜生成使用 `references`
- 支持管理端查询、创建、编辑、删除 `references`
- 不要求本期支持 remix、bulk create、跨账号共享

## 功能要求

1. 生成接口新增 `references` 字段，类型为字符串数组，值为 `reference_id`
2. `references` 仅允许用于视频模型，图片模型传入时报参数错误
3. 服务端需自动去重，最大支持 5 个 reference
4. 提交 Sora 任务时，不新增顶层 `references` 字段，而是写入 `inpaint_items`
5. `inpaint_items` 中 reference 结构固定为：

```json
{ "kind": "reference", "reference_id": "ref_xxx" }
```

6. 当请求同时带图片和 references 时，二者共存于同一个 `inpaint_items` 数组
7. 未传 `references` 时，现有视频生成能力不得回归
8. 管理端需支持 reference 列表、创建、编辑、删除，以及图片上传

## 实现依据

本需求必须以观测文档为准：
[sora_reference_observation.md](C:\Codex\apps\Sora2Api\sora_reference_observation.md)

关键约束：

- `nf/create` 不直接接收顶层 `references`
- reference 选择结果来自本地 `referenceIds`，提交前不会额外查询 `/references/*`
- reference 创建链路为 `/project_y/file/upload -> asset_pointer -> /project_y/references/create`
- reference 编辑使用 `PUT /project_y/references/{reference_id}`
- reference 查询使用 `GET /project_y/references/mine?limit=20`

## 验收标准

- 带 `references` 的视频请求可成功提交，且 `inpaint_items` 结构正确
- 无 `references` 的视频请求行为与当前版本一致
- 管理端可完成 reference 增删改查闭环
- 文档包含请求示例、数量限制和错误提示
