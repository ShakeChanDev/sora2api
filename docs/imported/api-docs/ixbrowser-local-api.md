# ixBrowser Local API（项目速查）

## 官方文档

- <https://www.ixbrowser.com/doc/v2/local-api/cn>
- 官方建议采用“双线程”模式处理开窗与自动化：一个启动线程、一个业务线程。
- 启动线程负责调用开窗接口并串行启动窗口；启动成功后，将 Selenium、调试地址等访问路径传给业务线程。
- 业务线程基于这些访问路径执行业务逻辑，不与开窗阶段混跑。

## 项目约定

- Base URL：`IXBROWSER_API_BASE`，默认 `http://127.0.0.1:53200`
- 传输方式：`POST + JSON`
- 响应成功口径：`error.code == 0`
- 开窗相关请求统一经 `ProfileOpenLauncherThread` 串行执行；启动线程负责 `opened-list / profile-open / close / open-state-reset`，业务线程只在拿到 `ws/debugging_address` 后继续 Playwright/CDP
- 开窗等待超时统一读取 `window_slot_wait_timeout_minutes -> sora_window_slot_wait_timeout_seconds`，不再使用旧的 30 秒私有等待字段
- 项目实现遵循上述双线程建议：开窗相关请求由单独启动线程串行执行，启动完成后再把 `ws/debugging_address` 等访问路径交给业务线程使用
- ixBrowser 侧项目约束：并发必须小于 3；

## 项目实际使用接口

| 接口 | 用途 | 当前实现入口 |
| --- | --- | --- |
| `POST /api/v2/group-list` | 获取分组列表 | `app/modules/ixbrowser/application/use_cases/groups.py` |
| `POST /api/v2/group-create` | 创建分组 | `app/api/ixbrowser.py` + `app/modules/ixbrowser/application/facade.py` |
| `POST /api/v2/profile-list` | 获取窗口列表 | `app/modules/ixbrowser/application/use_cases/groups.py` |
| `POST /api/v2/profile-create` | 创建窗口 | `app/api/ixbrowser.py` + `app/modules/ixbrowser/application/facade.py` |
| `POST /api/v2/profile-open` | 打开窗口并获取调试地址 | `app/modules/ixbrowser/application/profile_open_launcher.py` |
| `POST /api/v2/native-client-profile-opened-list` | 获取可连接已开窗口 | `app/modules/ixbrowser/application/profile_open_launcher.py` |
| `POST /api/v2/profile-close` | 关闭窗口 | `app/modules/ixbrowser/application/use_cases/profiles.py` |
| `POST /api/v2/profile-open-state-reset` | 重置打开状态 | `app/modules/ixbrowser/application/profile_open_launcher.py` |
| `POST /api/v2/profile-update-groups-in-batches` | 批量迁移窗口分组 | `app/modules/ixbrowser/application/use_cases/groups.py` |
| `POST /api/v2/proxy-list` | 查询代理列表 | `app/modules/ixbrowser/application/use_cases/proxies.py` |
| `POST /api/v2/proxy-create` | 新建代理 | `app/modules/ixbrowser/application/use_cases/proxies.py` |
| `POST /api/v2/proxy-update` | 更新代理 | `app/modules/ixbrowser/application/use_cases/proxies.py` |
| `POST /api/v2/proxy-delete` | 删除代理 | `app/modules/ixbrowser/application/use_cases/proxies.py` |
| `POST /api/v2/profile-update-proxy-for-custom-proxy` | 给窗口绑定代理 | `app/modules/ixbrowser/application/use_cases/proxies.py` |

## 常见错误码

- `1009`：进程未找到，关闭窗口时常见，可按已关闭兜底
- `111003`：窗口已打开，需要附着已开窗口或重置状态
- `2007`：窗口不存在
- `2012`：窗口云备份中，稍后重试
- `1008`：权限或繁忙类错误，项目内有退避重试
