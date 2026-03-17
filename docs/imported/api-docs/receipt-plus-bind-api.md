# Receipt Plus 绑定 API（外部参考）

## 服务地址

- 页面入口：`https://receipt.nitro.xin/redeem/chatgpt`
- API 网关：`https://receipt-api.nitro.xin`

## 真实请求总览

主链路顺序如下：

`/cdks/public/check -> /external/public/check-user -> /stocks/public/outstock -> /stocks/public/outstock/{task_id}`

## 接口 1：CDK 校验

```http
POST /cdks/public/check
Content-Type: application/json
X-Product-ID: chatgpt

{
  "code": "<redacted len=12>"
}
```

成功返回会包含 `used`、`app_name`、`app_product_name` 等字段。

## 接口 2：用户校验

- 请求体必须同时包含 `cdk` 和 `user`
- `user` 必须是 `https://chatgpt.com/api/auth/session` 的完整 JSON 字符串
- 单独传 `email`、`user.id`、`accessToken`、`sessionToken` 不属于成功链路
- 实测口径：`HTTP 200` 视为校验通过

```http
POST /external/public/check-user
Content-Type: application/json
X-Product-ID: chatgpt

{
  "cdk": "<redacted len=12>",
  "user": "<chatgpt_session_json_string redacted len=2048>"
}
```

## AuthSession 获取方式

1. 在已登录 ChatGPT 的浏览器页面访问 `https://chatgpt.com/api/auth/session`
2. 复制完整 JSON 原文
3. 将该 JSON 整体作为字符串传给 `user`

## 接口 3：提交充值任务

- 请求头要求：`Content-Type: application/json`、`X-Product-ID: chatgpt`
- `user` 字段规则与接口 2 相同
- 返回为 `text/plain`，内容是 UUID `task_id`

```http
POST /stocks/public/outstock
Content-Type: application/json
X-Product-ID: chatgpt

{
  "cdk": "<redacted len=12>",
  "user": "<chatgpt_session_json_string redacted len=2048>"
}
```

## 接口 4：查询任务状态

- 轮询频率建议每 10 秒一次
- 成功终态：`pending=false && success=true`

```http
GET /stocks/public/outstock/{task_id}
```

## 已知陷阱

- `user` 必须是完整 AuthSession JSON 字符串，不能拆字段传递
- 不要在日志、文档、截图中记录可复用 token、cookie、session 原文
- `GET /public/check-usage/:codes` 已不在主链路，`2026-03-04` 实测返回 `404 page not found`
