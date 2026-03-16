# NSTBrowser 官方 API 与自动化文档整理

> 抓取日期：`2026-03-16`
>
> 来源范围：仅整理 `https://apidocs.nstbrowser.io/` 公布的公开文档，并以 `https://apidocs.nstbrowser.io/llms.txt` 作为页面清单。
>
> 默认基址：HTTP `http://localhost:8848/api/v2`，WebSocket `ws://localhost:8848/api/v2`
>
> 认证方式：请求头 `x-api-key`

## 总览

- 这份文档不是官方页面镜像，而是按中文使用场景重组后的摘要版。
- 覆盖范围固定为 API v2 的 31 个接口页，加自动化的 6 个官方页面。
- 除特殊说明外，所有 HTTP / WS 接口都要求携带 `x-api-key`。
- CDP/自动化相关页面反复强调：客户端或 Docker 默认监听 `8848` 端口。

| 板块 | 内容 |
| --- | --- |
| Browsers | 浏览器实例启动、停止、状态、页面列表、调试地址 |
| Profiles | Profile 本体、分组、代理、标签 |
| Locals | 本地 profile 数据与 cookies 清理 |
| CDP Endpoints | WebSocket/CDP 连接入口 |
| Automation | Selenium / Puppeteer / Playwright 接法与 CDP 扩展函数 |

## Browsers

官方 Browser APIs 将这组接口定义为“管理浏览器实例、检查页面、获取调试数据”的入口。

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `StartBrowser` | `POST` | `/browsers/{profileId}` | 启动指定 `profileId` 的浏览器，并返回远程调试地址。 |
| `StartBrowsers` | `POST` | `/browsers` | 批量启动一组 profile 对应的浏览器实例。 |
| `StartOnceBrowser` | `POST` | `/browsers/once` | 创建并启动一次性浏览器，无需预先创建 profile。 |
| `StopBrowser` | `DELETE` | `/browsers/{profileId}` | 停止指定浏览器实例。 |
| `StopBrowsers` | `DELETE` | `/browsers` | 批量停止浏览器实例；传空数组时会停止全部浏览器。 |
| `GetBrowsers` | `GET` | `/browsers` | 列出当前浏览器运行实例。 |
| `GetBrowserPages` | `GET` | `/browsers/{profileId}/pages` | 按 `profileId` 查询当前浏览器打开的页面列表。 |
| `GetBrowserDebugger` | `GET` | `/browsers/{profileId}/debugger` | 获取指定浏览器的远程调试地址。 |

### StartBrowser
- 协议/方法：`POST`
- 路径：`/browsers/{profileId}`
- 用途：启动指定 `profileId` 的浏览器，并返回远程调试地址。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：需在请求头提供 `x-api-key`。
- 响应核心字段：`code`、`err`、`msg`，以及 `data.port`、`data.profileId`、`data.proxy`、`data.webSocketDebuggerUrl`。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554899.md)

### StartBrowsers
- 协议/方法：`POST`
- 路径：`/browsers`
- 用途：批量启动一组 profile 对应的浏览器实例。
- 必填参数：无必填路径参数；可选查询参数 `headless` 控制是否无头启动。
- 关键请求体字段：`application/json` 数组，请求体为 `profileId` 字符串数组；可配合可选查询参数 `headless=true|false`。
- 默认值/限制：如果只想批量启动现有 profile，这是比单个 `StartBrowser` 更直接的入口。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554897.md)

### StartOnceBrowser
- 协议/方法：`POST`
- 路径：`/browsers/once`
- 用途：创建并启动一次性浏览器，无需预先创建 profile。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 对象，核心字段为 `name`、`platform`、`kernelMilestone`、`autoClose`、`timedCloseSec`、`fingerprintRandomness`、`headless`、`incognito`、`remoteDebuggingPort`、`proxy`、`skipProxyChecking`、`args`、`startupUrls`、`fingerprint`。
- 默认值/限制：官方页面列出的 `kernelMilestone` 枚举为 `128`、`130`、`132`；与 `CreateProfile` 页面的枚举不一致。
- 响应核心字段：`code`、`err`、`msg`，以及 `data.port`、`data.profileId`、`data.proxy`、`data.webSocketDebuggerUrl`。
- 版本备注：无单独版本门槛，但官方页给出的 milestone 枚举偏旧。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554898.md)

### StopBrowser
- 协议/方法：`DELETE`
- 路径：`/browsers/{profileId}`
- 用途：停止指定浏览器实例。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：用于关闭正在运行的单个浏览器实例。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554900.md)

### StopBrowsers
- 协议/方法：`DELETE`
- 路径：`/browsers`
- 用途：批量停止浏览器实例；传空数组时会停止全部浏览器。
- 必填参数：无。
- 关键请求体字段：`application/json` 数组，请求体为 `profileId` 字符串数组；空数组表示停止全部浏览器。
- 默认值/限制：官方说明明确指出：空数组会停止全部浏览器。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554896.md)

### GetBrowsers
- 协议/方法：`GET`
- 路径：`/browsers`
- 用途：列出当前浏览器运行实例。
- 必填参数：可选查询参数 `status`，支持 `starting`、`running`、`stopping`。
- 关键请求体字段：无。
- 默认值/限制：返回值适合做运行状态巡检。
- 响应核心字段：`code`、`err`、`msg`，以及 `data[]` 中的 `kernel`、`kernelMillis`、`name`、`platform`、`profileId`、`remoteDebuggingPort`、`running`、`starting`、`stopping`。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554895.md)

### GetBrowserPages
- 协议/方法：`GET`
- 路径：`/browsers/{profileId}/pages`
- 用途：按 `profileId` 查询当前浏览器打开的页面列表。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：只对正在运行的浏览器有意义。
- 响应核心字段：`code`、`err`、`msg`，以及 `data[]` 中的 `id`、`title`、`type`、`url`、`description`、`devtoolsFrontendUrl`、`webSocketDebuggerUrl`。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554902.md)

### GetBrowserDebugger
- 协议/方法：`GET`
- 路径：`/browsers/{profileId}/debugger`
- 用途：获取指定浏览器的远程调试地址。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：Selenium 场景通常先拿到调试地址，再挂接现有浏览器。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554901.md)

## Profiles

官方 Profile APIs 用于管理 profile 本身，以及它的分组、代理和标签。

### 核心接口

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `CreateProfile` | `POST` | `/profiles` | 创建一个新 profile，可使用随机指纹，也可通过 `fingerprint` 自定义。 |
| `DeleteProfiles` | `DELETE` | `/profiles` | 按 `profileIds` 批量删除 profile。 |
| `DeleteProfile` | `DELETE` | `/profiles/{profileId}` | 删除单个 profile。 |
| `GetProfiles` | `GET` | `/profiles` | 按页码分页列出 profile，并带回页面信息。 |
| `GetProfilesByCursor` | `GET` | `/profiles/cursor` | 按游标分页列出 profile，适合全量遍历。 |

#### CreateProfile
- 协议/方法：`POST`
- 路径：`/profiles`
- 用途：创建一个新 profile，可使用随机指纹，也可通过 `fingerprint` 自定义。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 对象，核心字段为 `name`、`platform`、`kernelMilestone`、`groupId`、`groupName`、`proxy`、`proxyGroupName`、`note`、`fingerprint`、`startupUrls`、`args`。
- 默认值/限制：`groupId` 优先级高于 `groupName`，`proxy` 优先级高于 `proxyGroupName`；默认名称为 `nst_${timestamp}`。
- 响应核心字段：`code`、`err`、`msg`，以及 `data._id`、`data.profileId`、`data.name`、`data.groupId`、`data.platform`、`data.kernelMilestone`、`data.status`、`data.tags`、`data.createdAt`、`data.updatedAt`。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554904.md)

#### DeleteProfiles
- 协议/方法：`DELETE`
- 路径：`/profiles`
- 用途：按 `profileIds` 批量删除 profile。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 数组，请求体为 `profileId` 字符串数组。
- 默认值/限制：请求体是 `profileId` 数组。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554905.md)

#### DeleteProfile
- 协议/方法：`DELETE`
- 路径：`/profiles/{profileId}`
- 用途：删除单个 profile。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：删除前无需额外请求体。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554906.md)

#### GetProfiles
- 协议/方法：`GET`
- 路径：`/profiles`
- 用途：按页码分页列出 profile，并带回页面信息。
- 必填参数：查询参数 `page`、`pageSize`、`s`、`tags`、`groupId`、`sortBy`。
- 关键请求体字段：无请求体；使用查询参数 `page`、`pageSize`、`s`、`tags`、`groupId`、`sortBy`。
- 默认值/限制：默认 `page=1`、`pageSize=10`；官方页建议做全量遍历时优先用 `GetProfilesByCursor`。
- 响应核心字段：`code`、`err`、`msg`，以及 `data.docs`、`data.totalDocs`、`data.page`、`data.totalPages`、`data.hasPrevPage`、`data.hasNextPage`、`data.prevPage`、`data.nextPage`。
- 版本备注：`sortBy` 参数需要 Nstbrowser `1.17.4+`。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554903.md)

#### GetProfilesByCursor
- 协议/方法：`GET`
- 路径：`/profiles/cursor`
- 用途：按游标分页列出 profile，适合全量遍历。
- 必填参数：查询参数 `pageSize`、`s`、`tags`、`groupId`、`direction`、`cursor`。
- 关键请求体字段：无请求体；使用查询参数 `pageSize`、`s`、`tags`、`groupId`、`direction`、`cursor`。
- 默认值/限制：默认 `pageSize=10`；只有在传入 `cursor` 时才需要配合 `direction=next|prev`。
- 响应核心字段：`code`、`err`、`msg`，以及 `data.docs`、`data.hasMore`、`data.nextCursor`、`data.prevCursor`。
- 版本备注：整个接口需要 Nstbrowser `1.17.3+`。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-19974738.md)

### Groups

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `GetAllProfileGroups` | `GET` | `/profiles/groups` | 列出全部 profile 分组，可按名称过滤。 |
| `ChangeProfileGroup` | `PUT` | `/profiles/{profileId}/group` | 把单个 profile 调整到指定分组。 |
| `BatchChangeProfileGroup` | `PUT` | `/profiles/group/batch` | 批量调整多个 profile 的分组。 |

#### GetAllProfileGroups
- 协议/方法：`GET`
- 路径：`/profiles/groups`
- 用途：列出全部 profile 分组，可按名称过滤。
- 必填参数：可选查询参数 `groupName`。
- 关键请求体字段：无。
- 默认值/限制：返回的是分组元数据，而不是 profile 列表。
- 响应核心字段：`code`、`err`、`msg`，以及 `data[]` 中的 `groupId`、`name`、`isDefault`、`createdAt`、`teamId`、`userId`。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15645168.md)

#### ChangeProfileGroup
- 协议/方法：`PUT`
- 路径：`/profiles/{profileId}/group`
- 用途：把单个 profile 调整到指定分组。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：`multipart/form-data`，必填字段只有 `groupId`。
- 默认值/限制：这一页使用 `multipart/form-data`，不是 JSON。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15645166.md)

#### BatchChangeProfileGroup
- 协议/方法：`PUT`
- 路径：`/profiles/group/batch`
- 用途：批量调整多个 profile 的分组。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 对象，必填字段为 `groupId` 和 `profileIds`。
- 默认值/限制：`groupId` 和 `profileIds` 都是必填。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15645167.md)

### Proxy

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `UpdateProfileProxy` | `PUT` | `/profiles/{profileId}/proxy` | 更新单个 profile 的代理配置。 |
| `BatchUpdateProxy` | `PUT` | `/profiles/proxy/batch` | 批量更新多个 profile 的代理配置。 |
| `ResetProfileProxy` | `DELETE` | `/profiles/{profileId}/proxy` | 把单个 profile 的代理重置为 local 类型。 |
| `BatchResetProfileProxy` | `DELETE` | `/profiles/proxy/batch` | 批量把多个 profile 的代理重置为 local 类型。 |

#### UpdateProfileProxy
- 协议/方法：`PUT`
- 路径：`/profiles/{profileId}/proxy`
- 用途：更新单个 profile 的代理配置。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：`application/json` 对象，字段为 `url`、`protocol`、`username`、`password`、`host`、`port`。
- 默认值/限制：官方说明要求：`url` 不能与 `protocol`、`host`、`port` 同时为空。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554907.md)

#### BatchUpdateProxy
- 协议/方法：`PUT`
- 路径：`/profiles/proxy/batch`
- 用途：批量更新多个 profile 的代理配置。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 对象，字段为 `profileIds` 和 `proxyConfig`；其中 `proxyConfig` 内含 `url`、`protocol`、`username`、`password`、`host`、`port`。
- 默认值/限制：批量更新时，代理配置收敛在 `proxyConfig` 对象里。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554909.md)

#### ResetProfileProxy
- 协议/方法：`DELETE`
- 路径：`/profiles/{profileId}/proxy`
- 用途：把单个 profile 的代理重置为 local 类型。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：重置后代理类型回到 local。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554908.md)

#### BatchResetProfileProxy
- 协议/方法：`DELETE`
- 路径：`/profiles/proxy/batch`
- 用途：批量把多个 profile 的代理重置为 local 类型。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 数组，请求体为 `profileId` 字符串数组。
- 默认值/限制：请求体是 `profileId` 数组。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554910.md)

### Tags

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `CreateProfileTags` | `POST` | `/profiles/{profileId}/tags` | 为单个 profile 新增标签。 |
| `BatchCreateProfileTags` | `POST` | `/profiles/tags/batch` | 为多个 profile 批量新增标签。 |
| `UpdateProfileTags` | `PUT` | `/profiles/{profileId}/tags` | 覆盖单个 profile 的标签列表。 |
| `BatchUpdateProfileTags` | `PUT` | `/profiles/tags/batch` | 批量覆盖多个 profile 的标签列表。 |
| `ClearProfileTags` | `DELETE` | `/profiles/{profileId}/tags` | 清空单个 profile 的标签。 |
| `BatchClearProfileTags` | `DELETE` | `/profiles/tags/batch` | 批量清空多个 profile 的标签。 |
| `GetProfileTags` | `GET` | `/profiles/tags` | 获取系统中的全部标签定义。 |

#### CreateProfileTags
- 协议/方法：`POST`
- 路径：`/profiles/{profileId}/tags`
- 用途：为单个 profile 新增标签。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：`application/json` 数组，元素为标签对象 `{ "name": string, "color": "#RRGGBB" }`。
- 默认值/限制：标签对象包含 `name` 和 `color`。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554912.md)

#### BatchCreateProfileTags
- 协议/方法：`POST`
- 路径：`/profiles/tags/batch`
- 用途：为多个 profile 批量新增标签。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 对象，字段为 `profileIds` 和 `tags`；`tags` 为标签对象数组。
- 默认值/限制：适合一次性给多条 profile 打相同标签。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554916.md)

#### UpdateProfileTags
- 协议/方法：`PUT`
- 路径：`/profiles/{profileId}/tags`
- 用途：覆盖单个 profile 的标签列表。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：`application/json` 数组，元素为标签对象 `{ "name": string, "color": "#RRGGBB" }`。
- 默认值/限制：语义上更偏向覆盖而不是追加。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554911.md)

#### BatchUpdateProfileTags
- 协议/方法：`PUT`
- 路径：`/profiles/tags/batch`
- 用途：批量覆盖多个 profile 的标签列表。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 对象，字段为 `profileIds` 和 `tags`；`tags` 为标签对象数组。
- 默认值/限制：请求体结构与 `BatchCreateProfileTags` 相同。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554915.md)

#### ClearProfileTags
- 协议/方法：`DELETE`
- 路径：`/profiles/{profileId}/tags`
- 用途：清空单个 profile 的标签。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：只清空标签，不删除 profile。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554913.md)

#### BatchClearProfileTags
- 协议/方法：`DELETE`
- 路径：`/profiles/tags/batch`
- 用途：批量清空多个 profile 的标签。
- 必填参数：无路径参数。
- 关键请求体字段：`application/json` 数组，请求体为 `profileId` 字符串数组。
- 默认值/限制：请求体是 `profileId` 数组。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554917.md)

#### GetProfileTags
- 协议/方法：`GET`
- 路径：`/profiles/tags`
- 用途：获取系统中的全部标签定义。
- 必填参数：无。
- 关键请求体字段：无。
- 默认值/限制：官方页只给出通用响应包，没有在该页展开 `data` 的字段结构。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554914.md)

## Locals

官方 Local APIs 处理本地 userdata，例如清 profile 数据和清 cookies。

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `ClearProfileCache` | `DELETE` | `/local/profiles/{profileId}` | 清理本地 profile 数据。 |
| `ClearProfileCookies` | `DELETE` | `/local/profiles/{profileId}/cookies` | 清理本地 profile cookies。 |

### ClearProfileCache
- 协议/方法：`DELETE`
- 路径：`/local/profiles/{profileId}`
- 用途：清理本地 profile 数据。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：面向本地 userdata；不是删除 profile 记录。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554918.md)

### ClearProfileCookies
- 协议/方法：`DELETE`
- 路径：`/local/profiles/{profileId}/cookies`
- 用途：清理本地 profile cookies。
- 必填参数：`profileId` 路径参数。
- 关键请求体字段：无。
- 默认值/限制：只清 cookie，不清 profile 其他本地数据。
- 响应核心字段：`code`、`data`、`err`、`msg`；该页通常把 `data` 视作通用返回体，未展开更多字段。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554919.md)

## CDP Endpoints

官方 CDP Endpoints 提供基于 Chrome DevTools Protocol 的连接入口，供 Puppeteer、Playwright、Selenium 等框架接管浏览器。

| 接口 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| `ConnectBrowser` | `WS` | `/connect/{profileId}` | 通过 WebSocket/CDP 启动并连接已有或已创建的 profile。 |
| `ConnectOnceBrowser` | `WS` | `/connect` | 通过 WebSocket/CDP 创建一次性浏览器并立即连接。 |

### ConnectBrowser
- 协议/方法：`WS`
- 路径：`/connect/{profileId}`
- 用途：通过 WebSocket/CDP 启动并连接已有或已创建的 profile。
- 必填参数：`profileId` 路径参数；可选查询参数 `config` 必须为 URL 编码后的 JSON 字符串。
- 关键请求体字段：实际通过 WebSocket 查询参数 `config` 传入 URL 编码后的 JSON；其结构与文档中的 `application/json` 对象一致，核心字段为 `autoClose`、`timedCloseSec`、`clearCacheOnClose`、`headless`、`incognito`、`proxy`、`skipProxyChecking`、`remoteDebuggingPort`、`startupUrls`、`urlBlockList`、`urlAllowList`、`args`。
- 默认值/限制：由于 `WS/GET` 不能带 request body，`config` 必须编码到 URL 查询参数中。
- 响应核心字段：`code`、`err`、`msg`，以及 `data.port`、`data.profileId`、`data.proxy`、`data.webSocketDebuggerUrl`。
- 版本备注：无明确版本门槛。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554920.md)

### ConnectOnceBrowser
- 协议/方法：`WS`
- 路径：`/connect`
- 用途：通过 WebSocket/CDP 创建一次性浏览器并立即连接。
- 必填参数：无路径参数；查询参数 `config` 必须为 URL 编码后的 JSON 字符串。
- 关键请求体字段：实际通过 WebSocket 查询参数 `config` 传入 URL 编码后的 JSON；核心字段为 `name`、`platform`、`kernelMilestone`、`autoClose`、`timedCloseSec`、`clearCacheOnClose`、`fingerprintRandomness`、`headless`、`incognito`、`proxy`、`remoteDebuggingPort`、`skipProxyChecking`、`startupUrls`、`urlBlockList`、`urlAllowList`、`fingerprint`、`args`。
- 默认值/限制：同样要求把 `config` 编码到 URL 查询参数；官方页面列出的 `kernelMilestone` 枚举也是 `128`、`130`、`132`。
- 响应核心字段：`code`、`err`、`msg`，以及 `data.port`、`data.profileId`、`data.proxy`、`data.webSocketDebuggerUrl`。
- 版本备注：无单独版本门槛，但官方页给出的 milestone 枚举偏旧。
- 官方链接：[官方页面](https://apidocs.nstbrowser.io/api-15554921.md)

## Automation

官方自动化文档并不是新增 HTTP API，而是解释如何借助 CDP / WebSocket 入口接入 Selenium、Puppeteer、Playwright，以及如何调用 Nstbrowser 暴露的自定义 CDP 函数。

### 通用流程

- 先运行 Nstbrowser Client 或 Docker，默认监听 `8848`。
- 如果是控制已有 profile，优先走 `ConnectBrowser`；如果是一次性浏览器，走 `ConnectOnceBrowser`。
- Puppeteer / Playwright 直接连接 `browserWSEndpoint`；Selenium 通常先拿调试端口，再通过 `debuggerAddress` 连接。
- 所有自动化示例都依赖 `x-api-key`，并把 `config` 编码进 URL。

| 页面 | 重点 | 官方链接 |
| --- | --- | --- |
| Introduction | 自动化入口说明，指向 Selenium / Puppeteer / Playwright / CDP Functions。 | [官方页面](https://apidocs.nstbrowser.io/doc-922599.md) |
| Selenium | 通过调试端口把 Selenium 接到现有浏览器。 | [官方页面](https://apidocs.nstbrowser.io/doc-922602.md) |
| Puppeteer | 通过 `puppeteer.connect` 直接接入 `browserWSEndpoint`。 | [官方页面](https://apidocs.nstbrowser.io/doc-922605.md) |
| Playwright | 通过 `chromium.connectOverCDP` 直接接入 `browserWSEndpoint`。 | [官方页面](https://apidocs.nstbrowser.io/doc-922606.md) |
| CDP Functions | 目前公开目录页只列出 `Network.updateContextProxy`，并注明更多函数稍后提供。 | [官方页面](https://apidocs.nstbrowser.io/folder-3411147.md) |
| Network.updateContextProxy | 运行中修改 context 代理配置。 | [官方页面](https://apidocs.nstbrowser.io/doc-922608.md) |

### ConnectBrowser 与 ConnectOnceBrowser 的差异

| 场景 | 适合接口 | 说明 |
| --- | --- | --- |
| 已有 profile | `ConnectBrowser` | 路径里带 `profileId`，更适合复用现有 profile 数据。 |
| 一次性浏览器 | `ConnectOnceBrowser` | 不依赖预创建 profile，配置直接跟随 `config`。 |
| 传参方式 | 两者相同 | 都是把 URL 编码后的 JSON 放进查询参数 `config`。 |

### Selenium

- 依赖：`pip install selenium`，并下载与内核版本匹配的 Chrome WebDriver。
- 官方思路：先拿到调试端口，再让 Selenium 连接现有浏览器。
- 代表性示例：

```python
from selenium import webdriver

options = webdriver.ChromeOptions()
options.add_experimental_option('debuggerAddress', '127.0.0.1:9222')
driver = webdriver.Chrome(options=options)
driver.get('https://nstbrowser.io')
```

来源：[Selenium](https://apidocs.nstbrowser.io/doc-922602.md)

### Puppeteer

- 依赖：`npm install puppeteer`。
- 官方思路：直接使用 `browserWSEndpoint` 调用 `puppeteer.connect`。
- 代表性示例：

```javascript
import puppeteer from 'puppeteer';

const browser = await puppeteer.connect({
  browserWSEndpoint: 'ws://localhost:8848/api/v2/connect/{profileId}?x-api-key=...&config=...',
  defaultViewport: null,
});
const page = await browser.newPage();
await page.goto('https://nstbrowser.io/');
```

来源：[Puppeteer](https://apidocs.nstbrowser.io/doc-922605.md)

### Playwright

- 依赖：`npm install playwright`。
- 官方思路：用 `chromium.connectOverCDP` 接管浏览器。
- 代表性示例：

```javascript
import { chromium } from 'playwright';

const browser = await chromium.connectOverCDP('ws://localhost:8848/api/v2/connect/{profileId}?x-api-key=...&config=...');
const page = await browser.newPage();
await page.goto('https://nstbrowser.io/');
```

来源：[Playwright](https://apidocs.nstbrowser.io/doc-922606.md)

### CDP Functions：Network.updateContextProxy

- 作用：在浏览器运行过程中更新当前 context 的代理配置。
- 调用方式：先建立 CDP session，再发送 `Network.updateContextProxy`。
- 参数重点：`proxyServer`、`proxyBypassList`。
- 特殊限制：代理 URL 里不要包含 `;`、`,`、`=` 这三个字符。
- 官方返回示例含义：成功时会返回布尔结果和提示信息，建议实际再验证代理是否生效。

```javascript
const result = await cdpSession.send('Network.updateContextProxy', {
  proxyServer: 'http://user:pass@host:port',
  proxyBypassList: '*.nstbrowser.io,*.google.com',
});
```

来源：[CDP Functions](https://apidocs.nstbrowser.io/folder-3411147.md) · [Network.updateContextProxy](https://apidocs.nstbrowser.io/doc-922608.md)

## 附录

### 公共响应结构

- 通用响应包 `rest.R-any`：`code`、`data`、`err`、`msg`。
- 远程调试地址 `browser.RemoteDebuggingAddress`：`port`、`profileId`、`proxy`、`webSocketDebuggerUrl`。
- 浏览器运行态 `browser.RuntimeData`：`kernel`、`kernelMillis`、`name`、`platform`、`profileId`、`remoteDebuggingPort`、`running`、`starting`、`stopping`。
- 页面对象 `browser.DevtoolsPageJsonRes`：`id`、`title`、`type`、`url`、`description`、`devtoolsFrontendUrl`、`webSocketDebuggerUrl`。
- Profile 分组对象 `business.ProfileGroupRep`：`groupId`、`name`、`isDefault`、`createdAt`、`teamId`、`userId`。

### 指纹与标签字段

- `fingerprint` 常见字段：`deviceMemory`、`disableImageLoading`、`doNotTrack`、`flags`、`fonts`、`geolocation`、`hardwareConcurrency`、`localization`、`restoreLastSession`、`screen`、`userAgent`、`webrtc`。
- `flags` 常见键：`audio`、`battery`、`canvas`、`clientRect`、`fonts`、`geolocation`、`geolocationPopup`、`gpu`、`localization`、`mediaDevices`、`screen`、`speech`、`timezone`、`webgl`、`webrtc`。
- `mediaDevices` 标记在官方 schema 中注明仅支持 `v1.18.1+`，默认标记为 `Masked`。
- 标签对象 `business.ProfileTag`：`name`、`color`，其中 `color` 使用十六进制颜色值。

### 版本与文档差异提示

- `GetProfilesByCursor` 明确要求 Nstbrowser `1.17.3+`。
- `GetProfiles` 的 `sortBy` 参数明确要求 Nstbrowser `1.17.4+`。
- 自动化示例里把 `userAgent` 备注为 `v0.15.0+` 支持。
- `CreateProfile` 页面列出的 `kernelMilestone` 枚举为 `132`、`135`、`138`、`140`，但 `StartOnceBrowser` / `ConnectOnceBrowser` 页面列出的是 `128`、`130`、`132`。如果你的本地版本较新，优先以实际运行时能力为准。
- `CreateProfile` 的平台枚举写成 `Windows` / `macOS` / `Linux`，而自动化示例里的配置值多用小写 `windows` / `macos` / `linux`；这是官方文档内部的书写差异。

### 官方页面清单

- Manifest：`https://apidocs.nstbrowser.io/llms.txt`
- API Introduction：`https://apidocs.nstbrowser.io/doc-922484.md`
- Automation Introduction：`https://apidocs.nstbrowser.io/doc-922599.md`
- Browsers / Profiles / Locals / CDP Endpoints 的细分接口均来自 `https://apidocs.nstbrowser.io/` 下对应 `.md` 页面。
