# AdsPower Local API（参考）

## 定位

- 外部工具接口参考
- 当前项目主流程基于 ixBrowser，AdsPower 不是主链路依赖

## 官方文档

- <https://localapi-doc-zh.adspower.net/>

## 最小速查

- 默认地址：`http://local.adspower.net:50325/` 或 `http://localhost:50325/`
- 常见鉴权：`Authorization: Bearer <API_KEY>`
- 官方说明存在频控，常见口径是每秒 1 次

## 若未来引入 AdsPower

1. 先更新 `docs/architecture.md` 说明边界变化
2. 适配层收敛在 `app/modules/*/infra`
3. 补齐测试与文档说明
