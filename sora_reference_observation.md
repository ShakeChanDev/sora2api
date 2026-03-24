# Sora `references` / `nf/create` Observation Report

Date: 2026-03-23
Workspace: `C:\Codex\apps\Sora2Api`
Page: `https://sora.chatgpt.com/explore`

## Scope

This report covers:

- `references` creation
- `references` editing
- `references` querying
- two `POST /backend/nf/create` task submissions

Data sources used:

- observed network request order from the controlled browser session
- browser resource timing
- live React Query mutation/query cache
- loaded frontend runtime module code

Important note:

- The exact raw request/response bodies were recovered exactly for the latest `POST /backend/nf/create` and for the current `GET /backend/project_y/references/mine`.
- The first `POST /backend/nf/create` request body can be reconstructed with high confidence from the live frontend payload builder and the observed single selected reference id.
- The first `POST /backend/nf/create` 400 response body was not retained in the mutation cache by the time extraction ran, so only its status and timing are directly observed.

## Key Conclusions

1. `references` are not sent to `POST /backend/nf/create` as a top-level `references` field.
2. Selected references are folded into `inpaint_items` as items shaped like:

```json
{ "kind": "reference", "reference_id": "<ref_id>" }
```

3. `inpaint_items` is a mixed array. It contains:

- uploaded files as `{ "kind": "file", "file_id": ... }`
- generations as `{ "kind": "generation", "generation_id": ... }`
- uploads as `{ "kind": "upload", "upload_id": ... }`
- references as `{ "kind": "reference", "reference_id": ... }`

4. `references` are optional for task submission.

- No selected reference means `referenceIds = []`
- In that case `inpaint_items` is still present, but can be an empty array

5. The client-side selected reference state is stored as `referenceIds` in the aux config store, not as a dedicated backend fetch-time dependency.

- default: `referenceIds: []`
- deduped client-side
- capped client-side to at most 5 ids

6. Task submission does not trigger a fresh `/references/` lookup immediately before `POST /backend/nf/create`.

- The client submits using already-held local `referenceIds`
- In this session, there was no `/references/*` request between the final `GET /references/mine` after edit and the first `POST /backend/nf/create`

7. Reference creation and editing both invalidate the same query key and cause a refetch of `GET /backend/project_y/references/mine?limit=20`.

8. Selecting a reference from the references carousel toggles `referenceIds`.

- The carousel click path updates `referenceIds`
- The inline autocomplete path can also insert `[reference_name]` text into the textarea and update `referenceIds`
- The actual `nf/create` payload uses `reference_id`, not the display text

9. In this session, both observed `POST /backend/nf/create` calls returned `400`.

## Observed Timeline

Times below are Asia/Shanghai (`+08:00`).

| Time | Event |
| --- | --- |
| 2026-03-23 18:52:18.398 | `GET /backend/project_y/references/mine?limit=20` |
| 2026-03-23 18:53:17.863 | `POST /backend/project_y/references/create` |
| 2026-03-23 18:53:18.370 | `GET /backend/project_y/references/mine?limit=20` |
| 2026-03-23 18:54:29.034 | `PUT /backend/project_y/references/ref_69c11b8a20bc81919e63f1087b43a6c0` |
| 2026-03-23 18:54:29.454 | `GET /backend/project_y/references/mine?limit=20` |
| 2026-03-23 18:54:34.601 | `POST /backend/nf/create` #1 |
| 2026-03-23 18:54:41.626 | `POST /backend/nf/create` #2 |

Observed sequencing summary:

- create reference -> refetch list
- edit reference -> refetch list
- first task submit happened about 5.1s after the post-edit refetch
- second task submit happened about 7.0s after the first task submit
- no `/references/*` request occurred between the post-edit refetch and the first `nf/create`

## Current Exact Reference Query Sample

Observed exact response from the live authenticated query function:

`GET /backend/project_y/references/mine?limit=20`

```json
{
  "items": [
    {
      "reference_id": "ref_69c11b8a20bc81919e63f1087b43a6c0",
      "owner_id": "user-5ZxcHZ7VKOSi6ceBWDpbuz6T",
      "name": "衣服",
      "display_name": "衣服",
      "description": "一黑黑色的衣服，有白色的花纹",
      "type": "setting",
      "asset_pointers": [
        "sediment://file_0000000004a072309a49b047ff9e3f3f"
      ],
      "preview_asset_url": "https://videos.openai.com/az/files/00000000-04a0-7230-9a49-b047ff9e3f3f%2Fraw?se=2026-03-26T00%3A00%3A00Z&sp=r&sv=2026-02-06&sr=b&skoid=5e5fc900-07cf-43e7-ab5b-314c0d877bb0&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-03-22T22%3A23%3A07Z&ske=2026-03-29T22%3A28%3A07Z&sks=b&skv=2026-02-06&sig=C3UfJAc5q279HS6ReU246HN/sn2bYvl/sUlJ44qckZU%3D&ac=oaisdmntprwestus",
      "can_edit": true,
      "visibility": "private",
      "allowlist": [],
      "blocklist": []
    }
  ],
  "cursor": null
}
```

## `references` Create / Edit Mechanics

### Create request shape

Recovered from live frontend module logic:

1. If an image is chosen, the client first uploads it:

`POST /backend/project_y/file/upload`

2. The returned `asset_pointer` is then used in:

`POST /backend/project_y/references/create`

Request body shape:

```json
{
  "name": "<trimmed name>",
  "display_name": "<same as name>",
  "description": "<trimmed description or null>",
  "type": "<character|setting|style|other>",
  "asset_pointers": ["<asset_pointer>"]
}
```

If no image is chosen, `asset_pointers` can be `[]`.

Frontend expects the create response to contain at least:

```json
{
  "reference_info": {
    "...": "..."
  }
}
```

### Edit request shape

Recovered from live frontend module logic:

`PUT /backend/project_y/references/{reference_id}`

Request body shape:

```json
{
  "name": "<trimmed name>",
  "display_name": "<same as name>",
  "description": "<trimmed description or null>",
  "type": "<character|setting|style|other>",
  "asset_pointers": ["<asset_pointer if replacing image>"]
}
```

Important behavior:

- `asset_pointers` is only included when a new image is uploaded during edit
- create and edit both invalidate `["references","mine"]`
- delete uses `DELETE /backend/project_y/references/{reference_id}`
- deleting a reference also removes its id from local `referenceIds`

## `nf/create` Payload Builder

Recovered from live frontend runtime:

- local selected references live in `auxConfig.referenceIds`
- local style lives in `auxConfig.styleId`
- local model lives in `auxConfig.model`
- local frame count comes from `config.nFrames`
- local `nSamples` can switch the endpoint from `/nf/create` to `/nf/bulk_create` when `nsamples > 1`

Relevant request shape emitted by the client:

```json
{
  "kind": "video",
  "prompt": "<prompt>",
  "title": null,
  "orientation": "<portrait|landscape>",
  "size": "<small|large>",
  "n_frames": 300,
  "inpaint_items": [
    "...attachments mapped here...",
    { "kind": "reference", "reference_id": "<ref_id>" }
  ],
  "remix_target_id": null,
  "reroll_target_id": null,
  "project_config": null,
  "trim_config": null,
  "metadata": null,
  "use_image_as_first_frame": false,
  "cameo_ids": null,
  "cameo_replacements": null,
  "model": "sy_8",
  "style_id": null,
  "audio_caption": null,
  "audio_transcript": null,
  "video_caption": null,
  "i2v_reference_instruction": null,
  "remix_prompt_template": null,
  "storyboard_id": null
}
```

If `nSamples > 1`, the client adds:

```json
{ "nsamples": <n> }
```

and switches endpoint to `/backend/nf/bulk_create`.

## `POST /backend/nf/create` Samples

### #1 with reference

Observed:

- endpoint: `POST /backend/nf/create`
- time: `2026-03-23 18:54:34.601 +08:00`
- status: `400`
- this was the submit you described as carrying a reference
- only one reference existed in the account at that moment, so the selected reference count was effectively `1`

High-confidence reconstructed request body from the live frontend builder plus the observed single reference id:

```json
{
  "kind": "video",
  "prompt": "123",
  "title": null,
  "orientation": "portrait",
  "size": "small",
  "n_frames": 300,
  "inpaint_items": [
    {
      "kind": "reference",
      "reference_id": "ref_69c11b8a20bc81919e63f1087b43a6c0"
    }
  ],
  "remix_target_id": null,
  "reroll_target_id": null,
  "project_config": null,
  "trim_config": null,
  "metadata": null,
  "use_image_as_first_frame": false,
  "cameo_ids": null,
  "cameo_replacements": null,
  "model": "sy_8",
  "style_id": null,
  "audio_caption": null,
  "audio_transcript": null,
  "video_caption": null,
  "i2v_reference_instruction": null,
  "remix_prompt_template": null,
  "storyboard_id": null
}
```

Observed response facts:

- HTTP status: `400`
- browser resource decoded body size: `150`
- exact raw response JSON was not retained in the mutation cache by the time extraction ran

### #2 without reference

Observed exact mutation variables and exact error response from the live mutation cache:

```json
{
  "request": {
    "kind": "video",
    "prompt": "123",
    "title": null,
    "orientation": "portrait",
    "size": "small",
    "n_frames": 300,
    "inpaint_items": [],
    "remix_target_id": null,
    "reroll_target_id": null,
    "project_config": null,
    "trim_config": null,
    "metadata": null,
    "use_image_as_first_frame": false,
    "cameo_ids": null,
    "cameo_replacements": null,
    "model": "sy_8",
    "style_id": null,
    "audio_caption": null,
    "audio_transcript": null,
    "video_caption": null,
    "i2v_reference_instruction": null,
    "remix_prompt_template": null,
    "storyboard_id": null
  },
  "response": {
    "error": {
      "message": "Hmmm something didn't look right with your request. Please try again later or visit https://help.openai.com if this issue persists.",
      "type": "invalid_request_error",
      "param": null,
      "code": "invalid_request"
    }
  },
  "meta": {
    "status": 400,
    "error_name": "UserError",
    "error_code": "invalid_request",
    "request_id": "7385b367-d1fc-4a73-b865-d4f1af43e29a",
    "submitted_at_ms": 1774263281595
  }
}
```

## Answer Matrix

| Question | Answer |
| --- | --- |
| create payload 里是否直接包含 `references` 顶层字段 | 否 |
| 真正承载 reference 的字段名 | `inpaint_items` |
| reference 的单项结构 | `{ "kind": "reference", "reference_id": "<ref_id>" }` |
| 数量限制 | 客户端 `referenceIds` 最多 5 个，且会去重 |
| 是否必填 | 否 |
| 与其他字段联动 | 与 attachments 共用 `inpaint_items`；与 `style_id`、`model`、`n_frames` 同时进入同一个 create payload |
| 提交前是否会再次查询 `/references/*` | 本次观测下没有 |
| create/edit 后是否会刷新 references 列表 | 会，都会 refetch `GET /references/mine` |
| create/edit 是否影响后续提交 | 会，最终影响的是本地 `referenceIds`，提交时转成 `inpaint_items[].reference_id` |
| 两次 `nf/create` 响应是否相同 | 不完全相同；两次都是 `400`，但响应体大小不同，第二次精确为 `invalid_request`，第一次精确 body 未保留 |

