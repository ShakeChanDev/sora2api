# Camoufox（外部依赖速查）

本文基于 `2026-03-13` 可访问的 Camoufox 官方公开资料整理，只记录可确认的事实、官方入口、接入方式、能力边界与已知限制，不讨论本项目迁移方案、替换结论或实施计划。Camoufox 仍处于活跃开发中，版本、支持矩阵与实验能力可能随时间变化；遇到时间点或版本敏感信息时，本文会直接写明绝对日期或版本。

## Camoufox 是什么

- Camoufox 官方将其定义为 open source anti-detect browser，核心卖点是 robust fingerprint injection 与 anti-bot evasion。来源：<https://camoufox.com/>、<https://github.com/daijro/camoufox>
- 官方资料说明 Camoufox 构建在 Firefox 之上，而不是 Chromium；首页同时说明其方案参考了 Tor Project、Arkenfox、CreepJS 等研究与工具。来源：<https://camoufox.com/>
- 官方指纹文档说明其会在 C++ implementation level 拦截并修改相关数据，而不是依赖页面 JavaScript 注入。来源：<https://camoufox.com/fingerprint/>
- 官方 Python 文档将其定位为对 Playwright API 的轻量封装；现有 Playwright 代码通常主要调整浏览器初始化方式。来源：<https://camoufox.com/python/>、<https://camoufox.com/python/usage/>
- 官方指纹与 BrowserForge 文档说明：用户未显式提供的部分指纹配置会由 BrowserForge 自动补齐，以贴近真实流量的统计分布。来源：<https://camoufox.com/fingerprint/>、<https://camoufox.com/python/browserforge/>
- 官方首页在 `2026-03-13` 可访问版本中明确提示：latest releases highly experimental，preview releases not stable，也不 suitable for production use。来源：<https://camoufox.com/>

## 官方入口

- 官方文档首页：<https://camoufox.com/>
- Python 文档入口：<https://camoufox.com/python/>
- 官方 PyPI：<https://pypi.org/project/camoufox/>
- 官方 GitHub 仓库：<https://github.com/daijro/camoufox>
- 官方 GitHub README 明确写明：浏览器开发当前活跃于 `CloverLabsAI/camoufox`，而 `daijro/camoufox` 主要承载 Python library updates 与 upstream browser release mirror。来源：<https://github.com/daijro/camoufox>、<https://github.com/CloverLabsAI/camoufox>
- 官方最新文档以 `camoufox.com` 为准；GitHub README 当前也明确提示 latest documentation 以官网为准。来源：<https://camoufox.com/>、<https://github.com/daijro/camoufox>

## 安装与运行方式

### 安装

```bash
pip install -U camoufox[geoip]
python -m camoufox fetch
```

- 官方安装主路径是先安装 `camoufox` Python 包，再执行 `fetch` 下载浏览器；官方同时给出 `camoufox fetch`、`python -m camoufox fetch`、`python3 -m camoufox fetch`。来源：<https://camoufox.com/python/installation/>
- `geoip` extra 是 optional，但官方明确写明在使用代理时 heavily recommended，因为它会额外下载定位 longitude、latitude、timezone、country、locale 所需的数据。来源：<https://camoufox.com/python/installation/>
- Linux 新环境下，官方安装页额外列出了 Firefox 运行依赖，例如 `libgtk-3-0`、`libx11-xcb1`、`libasound2`。来源：<https://camoufox.com/python/installation/>
- 若需要从源码自建浏览器，官方公开了 build guide；GitHub README 还说明 build system 面向 Linux，`WSL will not work`。来源：<https://camoufox.com/development/overview/>、<https://github.com/daijro/camoufox>
- GitHub README 同时提供了 Docker 方式参与构建。来源：<https://github.com/daijro/camoufox>

### CLI

- 官方安装页公开列出的 CLI 命令包括：`fetch`、`path`、`remove`、`server`、`test`、`version`。来源：<https://camoufox.com/python/installation/>
- `server` 用于启动 Playwright websocket server，`test` 用于打开 Playwright inspector。来源：<https://camoufox.com/python/installation/>、<https://camoufox.com/python/remote-server/>

## 与 Playwright / Firefox 的关系

- Camoufox 官方明确写明其基于 Firefox，而不是 Chromium；官方给出的理由包括 Chrome 与 Chromium 差异、Chromium/CDP 更常见、Firefox 在抗指纹研究上的积累更多。来源：<https://camoufox.com/>
- 官方 Python 文档说明：Camoufox wraps around Playwright API，现有 Playwright 代码通常只需要调整 browser initialization。来源：<https://camoufox.com/python/>、<https://camoufox.com/python/usage/>
- 官方 Usage 页面写明：Camoufox 接受全部 Playwright Firefox launch options，并额外提供自己的参数。来源：<https://camoufox.com/python/usage/>
- 官方 Features 页面写明其包含 “Custom implementation of Playwright for the latest Firefox”。这是官方实现描述，不等同于本项目已验证所有 Playwright 场景都可零改动兼容。来源：<https://camoufox.com/features/>
- 官方 Stealth 文档说明：Playwright 在 Firefox 上使用的是 Juggler 而不是 Chromium 的 CDP；Camoufox 对 Juggler 做了隔离补丁，让自动化读写发生在隔离世界。来源：<https://camoufox.com/stealth/>
- 对 Python 之外的语言，官方公开路径是 experimental remote websocket server，可供其他支持 Playwright API 的语言通过 websocket `connect` 接入。来源：<https://camoufox.com/python/remote-server/>

## 指纹、代理、持久化、扩展、自动化控制等能力边界

| 能力面 | 官方已确认事实 | 当前不能据此下的结论 |
| --- | --- | --- |
| 指纹 / 反检测 | 官方文档列出 `navigator`、`screen`、`viewport`、`headers`、`WebGL`、`fonts`、`voices`、`WebRTC IP`、`geolocation`、`timezone`、`locale` 等 spoofing 或 injection 能力；相关数据在 C++ implementation level 处理，默认可结合 BrowserForge 生成或补齐设备特征。官方同时明确写明：Camoufox 不支持注入 Chromium fingerprints，因为 V8 特有 JavaScript 行为无法伪装。来源：<https://camoufox.com/>、<https://camoufox.com/features/>、<https://camoufox.com/fingerprint/>、<https://camoufox.com/python/browserforge/> | 不能据此认定它一定能稳定绕过本项目目标站点的所有检测；该效果需要单独验证。 |
| 代理 | 官方文档确认可直接使用 Playwright 的 `proxy` 参数；若启用 `geoip=True` 或传入目标 IP，会按目标 IP 对齐 longitude、latitude、timezone、country、locale，并 spoof WebRTC IP。官方同时明确建议使用 residential proxies 以获得更好效果。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/python/geoip/> | 官方文档没有给出 ixBrowser 那类代理资产管理、代理池管理或代理绑定 API。 |
| 持久化 | 官方 Usage 页面确认支持 `persistent_context=True`，并要求同时提供 `user_data_dir`。来源：<https://camoufox.com/python/usage/> | 官方公开资料没有给出类似 ixBrowser profile 体系的模型、生命周期和兼容承诺。 |
| 扩展 | 官方文档确认支持 Firefox addons；入参要求是 extracted addon 路径；加载 `.xpi` 需要先改名为 `.zip` 并解压；官方还说明默认会下载并启用 uBlock Origin，可通过 `exclude_addons` 排除默认 addon；Features 页面同时写明 addons 不允许打开新标签页。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/fingerprint/addons/>、<https://camoufox.com/features/> | 不能据此推断现有 Chrome 扩展可直接复用；官方公开资料未说明 Chrome extension 直接兼容。 |
| 自动化控制 | 官方确认提供 sync / async Python API、Playwright inspector、remote websocket server；默认 JavaScript 执行在 isolated world 中，可读 DOM 且不易被页面检测，但不能直接修改 DOM；若启用 `main_world_eval` 并以 `mw:` 前缀在 main world 执行代码，则可以修改 DOM，但官方明确警告这会被目标站点检测到，且不支持从 main world 返回 element/node 引用。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/python/main-world-eval/>、<https://camoufox.com/python/remote-server/>、<https://camoufox.com/stealth/> | 不能据此推断 Camoufox 自带任务编排、浏览器编队管理或窗口资产管理层。 |
| 本地 API / 浏览器管理 | 从官方文档当前可确认的控制面主要是 Python wrapper、CLI 与 Playwright websocket server。来源：<https://camoufox.com/python/installation/>、<https://camoufox.com/python/remote-server/> | 是否存在类似 ixBrowser Local API 的 `profile/group/window/proxy` CRUD 接口：未知。 |

## 常见启动参数或接入模式

### 直接在 Python 中启动

```python
from camoufox.sync_api import Camoufox

with Camoufox(
    proxy={"server": "http://proxy.example:8080"},
    geoip=True,
    persistent_context=True,
    user_data_dir="/path/to/profile-dir",
) as context:
    page = context.new_page()
    page.goto("https://example.com")
```

- `proxy`：沿用 Playwright `proxy` 参数。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/python/geoip/>
- `geoip=True` 或 `geoip="<target_ip>"`：按目标 IP 对齐 geolocation、timezone、country、locale 与 WebRTC IP。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/python/geoip/>
- `persistent_context=True` + `user_data_dir="/path/to/profile-dir"`：启用持久化上下文。来源：<https://camoufox.com/python/usage/>
- `addons=[...]`：加载已解包的 Firefox addons。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/fingerprint/addons/>
- `exclude_addons=[...]`：排除默认 addons，例如默认的 uBlock Origin。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/fingerprint/addons/>
- `headless=True`：标准 headless 模式。来源：<https://camoufox.com/python/usage/>
- `headless="virtual"`：在 Linux 上通过虚拟显示运行 headless。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/python/virtual-display/>
- `main_world_eval=True`：允许以 `mw:` 前缀把脚本送到 main world；官方明确提示此模式有可检测风险。来源：<https://camoufox.com/python/main-world-eval/>
- `enable_cache=True`：开启缓存；默认关闭，默认关闭时 `page.go_back()` 与 `page.go_forward()` 不可用。来源：<https://camoufox.com/python/usage/>
- `block_images=True`：阻止图片请求。来源：<https://camoufox.com/python/usage/>
- `block_webrtc=True`：阻止 WebRTC。来源：<https://camoufox.com/python/usage/>
- `disable_coop=True`：关闭 COOP。来源：<https://camoufox.com/python/usage/>

### 通过 Playwright websocket server 接入

```bash
python -m camoufox server
```

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.firefox.connect("ws://localhost:1234/hello")
    page = browser.new_page()
```

- 官方文档确认支持 remote websocket server，并允许其他支持 Playwright API 的语言通过 `connect` 接入。来源：<https://camoufox.com/python/remote-server/>
- 官方文档同时明确标注：该能力是 experimental，并使用了 hacky workaround 访问 undocumented Playwright methods。来源：<https://camoufox.com/python/remote-server/>
- 官方还说明：server 只使用一个 browser instance，因此 fingerprints 不会在 sessions 之间自动轮换；若要大规模使用，需要自行轮换 server。来源：<https://camoufox.com/python/remote-server/>

## 已知限制与风险

- 官方首页在 `2026-03-13` 可访问版本中明确提示：latest releases highly experimental，preview releases not stable，不应直接视为 production-ready。来源：<https://camoufox.com/>
- GitHub README 当前写明：`main` branch 构建在 Firefox `v146` 上，属于 experimental change；若需要 stable production version 来自行构建，README 建议使用 `releases/135` 分支。来源：<https://github.com/daijro/camoufox>
- 官方首页还写明：截至 `v146.0.1-beta.25`（`2026-01`），源码已公开；但官方同时说明 `v135.0.1-beta.24` 及以下官方 release 含 closed-source Canvas patch。若关心可审计性，需要按具体版本再次核验。来源：<https://camoufox.com/>
- 官方 Stealth 文档说明项目曾有约一年的 maintenance gap，导致基础 Firefox 版本与 newly discovered fingerprint inconsistencies 让性能与隐蔽性下降。来源：<https://camoufox.com/stealth/>
- 官方同时明确说明：即使隐藏了自动化库，fingerprint rotation 仍可能出现 inconsistency，因此仍需要持续维护。来源：<https://camoufox.com/stealth/>
- 官方 virtual display 文档说明：即使已有 headless detection patch，未来 headless 仍可能被检测；Linux 推荐改用 virtual display / `Xvfb`。来源：<https://camoufox.com/python/virtual-display/>、<https://camoufox.com/stealth/>
- 官方 remote server 文档明确警告该能力是 experimental，并依赖 undocumented Playwright methods。来源：<https://camoufox.com/python/remote-server/>
- 官方 `main world` 文档明确提示：所有在 main world 执行的代码都能被目标网站检测到；只有在确有必要修改 DOM 时才建议启用。来源：<https://camoufox.com/python/main-world-eval/>
- 官方 Usage 页面明确提示：固定 `window` 尺寸会带来 fingerprinting 风险；`block_webgl=True` 只适合特殊场景，否则可能造成 leaks；`config` 覆盖属于 advanced feature，应谨慎使用。来源：<https://camoufox.com/python/usage/>
- 官方 BrowserForge integration 文档说明：当前仍有部分 BrowserForge fingerprint properties 不会传给 Camoufox，原因是上游 fingerprint dataset 过旧；待上游数据更新后才会恢复。来源：<https://camoufox.com/python/browserforge/>
- GitHub README 当前仍保留一段与 Firefox `v146` 升级相关的阶段性说明，说明当时支持矩阵仍在变化；若计划自行构建，应在实现前再核对 README 与官方文档。来源：<https://github.com/daijro/camoufox>

## 与本项目相关的关注点

| 关注点 | 当前可确认结论 |
| --- | --- |
| 是否支持 Playwright 接入 | 支持。官方确认 Python wrapper 直接包裹 Playwright API；跨语言可通过 websocket server + `p.firefox.connect(...)` 接入。来源：<https://camoufox.com/python/>、<https://camoufox.com/python/usage/>、<https://camoufox.com/python/remote-server/> |
| 是否支持持久化用户数据目录 | 支持。官方确认 `persistent_context=True` 时需要 `user_data_dir`。来源：<https://camoufox.com/python/usage/> |
| 是否支持代理配置 | 支持。官方确认可传 Playwright `proxy` 参数；可选 `geoip` 做地区、语言、WebRTC IP 对齐；官方还建议优先使用 residential proxies。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/python/geoip/> |
| 是否支持浏览器指纹 / 反检测相关能力 | 官方文档明确列出相关能力，并以此作为核心卖点；但这些仍是官方宣称与官方实现描述，不是本项目实测结论。来源：<https://camoufox.com/>、<https://camoufox.com/features/>、<https://camoufox.com/fingerprint/>、<https://camoufox.com/python/browserforge/> |
| 是否支持扩展或替代现有插件机制 | 官方确认支持 Firefox addons，且要求 extracted addon 路径；但本仓库当前在 [README.md](../../README.md) 中记录的资源拦截机制是 Chrome 插件 `extensions/sora-fast-block/`，公开资料不足以证明两者可等价替代。来源：<https://camoufox.com/python/usage/>、<https://camoufox.com/fingerprint/addons/>、<https://camoufox.com/features/>、[README.md](../../README.md) |
| 是否有本地 API / 浏览器管理能力 | 当前公开资料仅能确认 CLI 与 Playwright websocket server；未见类似 ixBrowser 的 `profile/group/window/proxy` 管理 API 文档，因此此项按未知处理。本项目现有 ixBrowser 能力背景见 [docs/architecture.md](../architecture.md) 与 [docs/reference/ixbrowser-local-api.md](./ixbrowser-local-api.md)。来源：<https://camoufox.com/python/installation/>、<https://camoufox.com/python/remote-server/>、[docs/architecture.md](../architecture.md)、[docs/reference/ixbrowser-local-api.md](./ixbrowser-local-api.md) |
| 哪些能力看起来和 ixBrowser 不同，但先不下替换结论 | 从公开资料看，Camoufox 的文档重心在 Firefox 派生浏览器、Playwright wrapper、指纹与代理；ixBrowser 的文档重心在本地 API、窗口/分组/代理管理。该差异说明公开能力形态不同，但不直接构成替换结论。来源：<https://camoufox.com/>、<https://camoufox.com/python/>、<https://github.com/daijro/camoufox>、[docs/reference/ixbrowser-local-api.md](./ixbrowser-local-api.md) |

## 参考链接

- <https://camoufox.com/>
- <https://camoufox.com/python/>
- <https://camoufox.com/python/installation/>
- <https://camoufox.com/python/usage/>
- <https://camoufox.com/python/geoip/>
- <https://camoufox.com/python/remote-server/>
- <https://camoufox.com/python/main-world-eval/>
- <https://camoufox.com/python/virtual-display/>
- <https://camoufox.com/python/browserforge/>
- <https://camoufox.com/features/>
- <https://camoufox.com/fingerprint/>
- <https://camoufox.com/fingerprint/addons/>
- <https://camoufox.com/stealth/>
- <https://camoufox.com/development/overview/>
- <https://github.com/daijro/camoufox>
- <https://github.com/CloverLabsAI/camoufox>
