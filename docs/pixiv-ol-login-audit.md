# Pixiv 登录链路检查与开源方案评估

检查日期：2026-10-03。本文保留登录修复过程；前半部分记录修复前故障，不代表当前状态。当前使用以 [Pixiv-ol 使用说明](pixiv-ol-usage.md) 为准。

## 本次结论

用户确认本次“没变化”发生在 Pixiv 白页或“协议未知”阶段。实际实例的新日志只记录了发起登录，没有新的完成连接提交；最近的新会话没有获得授权码，检查结束时已超时。本轮不能据此判定令牌兑换再次失败。

当前默认浏览器模式是“打开官方授权页 + 手动提交回调”，不是完整的自动回跳登录。本机没有注册 `pixiv://` 协议处理器，因此浏览器不能把 App 回调交给 PicManager。之前追加时间/摘要请求头和调整错误提示，没有补上这个接收环节。

真实账号连接尚未验证成功。模拟测试通过仅说明本地各分支可执行。

## 逐段核对

| 环节 | 核对结果 | 影响与处理 |
| --- | --- | --- |
| 页面按钮与默认浏览器 | 本机请求通过系统 URL 关联打开；默认关联为 Firefox。主流程不启动 Playwright，也不复制浏览器 Cookie | 可以沿用 Firefox 已有登录状态；远程访问不启动服务器桌面浏览器 |
| PKCE | 随机 verifier 加密保存；SHA-256 + Base64 URL 安全编码；RFC 7636 标准向量通过 | 重新打开和刷新恢复复用同一会话；重新开始生成新 verifier，旧回调不能混用 |
| Pixiv 授权入口 | URL、S256、客户端参数与 gppt、gallery-dl 相同 | 官方 `post-redirect` 的 JS 创建 POST 表单；不能把中转地址当作授权结果或手工改成 GET 来验证 |
| 浏览器最终回调 | 支持官方 HTTPS callback 和 `pixiv://account/login`；当前没有系统协议桥接 | 这是本次白页的主要流程缺口；当前需要手动复制回调，约 30 秒有效期的提示来自两个开源实现 |
| 本地提交与解析 | Root 鉴权、同源写入标识、所属会话和期限检查；拒绝陌生域名、用户信息、非标准端口、fragment 和多个 code | 新的完成连接请求才会进入兑换；不记录粘贴内容 |
| 授权码兑换 | POST 表单编码、code/verifier、固定 redirect_uri、客户端参数核对通过；真实请求准备阶段验证了字段未被额外编码 | 不能将没有效授权码的探测当作真实账号成功；HTTP 400/invalid_request 不应统一显示“暂时不可用” |
| 账号绑定 | 兑换后还调用 pixivpy 刷新一次，取得账号信息后加密保存 | 比单次兑换多一个网络失败点；日志已区分 exchange 与 connect。后续可利用已验证兑换响应的用户信息，减少重复刷新 |
| 重试与生命周期 | 服务端会话最多十分钟，兑换仅一次；失败会话提供重新开始入口 | 十分钟是本地等待期限，不代表 Pixiv 授权码能保存十分钟；同一授权码不应重复兑换 |

无效授权码的无凭据探测也会获得 `invalid_request` 和数字错误码 918，因此不能仅靠 918 断言配置的客户端凭据已失效。当前只保留数字码用于诊断，显示授权兑换被拒绝；明确 `invalid_client` / `unauthorized_client` 才归类为客户端拒绝。

## 可利用的开源项目

| 项目 | 实现与许可证 | 对本项目的适用性 |
| --- | --- | --- |
| [eggplants/get-pixivpy-token (gppt)](https://github.com/eggplants/get-pixivpy-token) | Python，MIT。`oauth_login` 支持默认浏览器、用户自己完成认证、手动粘贴；OAuth 与 token 模块独立 | 最方便复用 PKCE、回调解析和兑换模块。仍然需要粘贴，不会单独解决本次回跳缺口。不要直接采用它会打印上游正文的异常处理 |
| [FlanChanXwO/pixiv-cli](https://github.com/FlanChanXwO/pixiv-cli) | Go，MIT。当前用户协议处理器、loopback 回调接收、默认浏览器、远程 relay；Windows 实现能临时注册并恢复协议关联 | 最贴合“默认 Firefox 登录后自动连接”。可作为独立登录助手，也可按其协议桥接设计编写 Python 助手。引入完整 CLI 会增加二进制与账号存储管理 |
| [mikf/gallery-dl](https://github.com/mikf/gallery-dl) | Python，GPL-2.0；成熟下载工具，Pixiv OAuth 仍使用手动复制 code | 适合独立 CLI 联调及参数对照；不能解决 Firefox 的系统协议接收，也不直接复制 GPL 实现进当前 MIT 项目 |
| [piglig/pixiv-token](https://github.com/piglig/pixiv-token) | Python，MIT；通过 Chromium/CloakBrowser/CDP 自动捕获 code | 适合单独浏览器自动化；需要独立浏览器与登录凭据，不匹配用户要求的已有 Firefox/Google 登录状态 |

核对过的具体源码：

- [gppt OAuth](https://github.com/eggplants/get-pixivpy-token/blob/main/gppt/oauth.py)、[兑换](https://github.com/eggplants/get-pixivpy-token/blob/main/gppt/token.py)。
- [gallery-dl Pixiv OAuth](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/oauth.py)。
- [pixiv-cli Windows 协议注册](https://github.com/FlanChanXwO/pixiv-cli/blob/7100a4f1fe867da10ab882f18b5197243ece0676/internal/cli/commands/pixiv/auth/loginhelper/install_windows.go)、[回调接收](https://github.com/FlanChanXwO/pixiv-cli/blob/7100a4f1fe867da10ab882f18b5197243ece0676/internal/cli/commands/pixiv/auth/loginhelper/handler.go)、[loopback 桥接](https://github.com/FlanChanXwO/pixiv-cli/blob/7100a4f1fe867da10ab882f18b5197243ece0676/internal/cli/commands/pixiv/auth/loginhelper/endpoint.go)。

## 推荐的下一阶段实现

采用 pixiv-cli 的协议桥接思路，保留现有 pixivpy 推荐、关注与下载逻辑：

1. 在本机明确开启自动回跳模式，启动仅监听 loopback 的一次性回调接收器，绑定本次 Root 会话和随机证明。
2. 通过当前用户的 `pixiv://` 处理器接收授权结果；已有协议关联必须保留并在结束后恢复，不能无条件覆盖其他 Pixiv 应用。非登录地址不转发。
3. 继续用默认 Firefox 打开官方授权页，用户自己完成 Google/Pixiv 认证。
4. 回调立即用 POST 交给本次会话，校验后兑换；代码不进入普通 URL query、日志或明文 token 缓存。
5. PicManager 轮询脱敏状态，完成后关闭登录弹窗，显示已连接；取消、超时或重启清理接收器和临时协议关联。
6. 不支持系统接收器的环境保留手动回调作为备用，并清楚标明“仍需提交回调”。

本次检查没有安装外部 CLI，没有注册或改写 Windows 协议关联，也没有把任何测试视为真实账号连接成功。

## 本次验证

全量测试 287 项通过；Ruff 与 JavaScript 语法检查通过。另以公开 RFC PKCE 向量、实际 requests 请求准备阶段、默认浏览器登录与失败重试的页面模拟进行核对。所有测试均未代替用户完成 Google/Pixiv 认证，也未兑换截图里的旧授权码。


## 2026-10-03 pixiv-cli 接入

用户选择 pixiv-cli 后，主登录已接入 [FlanChanXwO/pixiv-cli v1.1.1](https://github.com/FlanChanXwO/pixiv-cli/releases/tag/v1.1.1)。Windows x64 发布包 SHA-256：`ec2bab3b337c40d052e5403078b0d344e9599eb7533c37661679429ca84daba9`。安装器保留 MIT 及第三方许可，二进制不提交 Git。

适配器固定检查版本，通过官方安装器同用的 `_install-handler` 注册当前用户协议处理器。登录命令使用 `auth login --json --no-open --use=false --timeout 10m --addr 127.0.0.1:<随机端口>`；CLI 准备好监听器后，适配器安装本轮共享 endpoint 并用系统默认浏览器打开 CLI 生成的受限登录页。这避免 CLI 的临时注册表切换在强制取消时无法执行清理。代理沿用 PicManager 配置。CLI 完成授权后，适配器 `auth export <本次 UID>` 仅在内存导入令牌；CLI 已验证账号，PicManager 不再立即刷新令牌。账号更新和会话 completed 在同一事务提交，取消或 Root 权限变化时禁止导入。

真实 v1.1.1 二进制已验证版本、参数、监听器启动及超时退出。独立数据库和真实子进程测试覆盖完成、取消、超时、脱敏错误、刷新恢复、权限撤销及既有偏好保留。真实 Pixiv 账号登录结果仍需用户授权后确认。


### 协议注册检查修复

v1.1.1 的 `_install-handler` 使用 `EnsurePersistentIfNeeded`，若 manifest 已记录同一个可执行文件，会直接跳过实际注册表修复。PicManager 原先仅执行该命令并严格比较命令字符串，实际关联缺失、旧路径或等价路径大小写差异会造成 `login_cli_handler_failed`。现在检查当前用户实际 `URL Protocol` 和回调命令，接受指向同一文件的等价路径；必要时备份待修改的三个值到 `DATA_PATH/pixiv-cli/handler-backup.json`，只修复当前用户协议类型和回调命令，再检查并通知 Windows 关联变化。其他注册表项保持不变，已正确的关联不会重复改写。

### Explorer 启动拦截修复

用户回跳打开终端并显示 `This is a command line tool`。固定版本引用 Cobra v1.10.1，其 [Windows 启动钩子](https://github.com/spf13/cobra/blob/v1.10.1/command_win.go) 在父进程为 Explorer 时，先显示提示再退出，不会执行 `_callback`。此前从 Python 调用 `os.startfile` 的测试没有覆盖由系统 Explorer 代理启动的情况。

当前用户的协议命令改为 `pythonw.exe protocol_handler.py --executable pixiv.exe "%1"`，路径均单独引用。独立入口只接受 `pixiv://account/login` 和唯一合法 code，静默使用参数列表调用未修改的官方 CLI，不通过 cmd/PowerShell 解释 URL；保留原 USERPROFILE，使 CLI 仍读取本轮 endpoint。CLI 继续负责 loopback fragment 中转和授权兑换。现有实际关联仍按上述方式备份与检查。

使用 Windows 进程父属性模拟 Explorer 启动，在隔离 CLI home 和模拟回调下复现：直接启动官方 CLI 退出且无法到达本地页；经 pythonw 入口退出码 0，系统默认浏览器到达无凭据本地验证页。测试未向 Pixiv 发送授权或令牌请求，不代表真实账号绑定成功。另增加 Windows Job Object，服务器进程异常结束时关闭其非继承句柄并终止本轮 CLI，避免下轮 `login_cli_busy`；真实父进程强制退出测试已覆盖。

### 本地结果页失败与代理修复

后续回跳到 CLI 本地 `/manual` 的 `Login failed` 页面，PicManager 只记录 `login_cli_failed`。v1.1.1 SDK 输出的是 `pixiv:Complete: upstream_unavailable` 等受控 reason，原分类器按 `oauth/exchange` 或底层网络文字查找，不能识别这种已脱敏格式。当前失败会话没有保存原始 stderr，因此无法恢复该次具体 reason。

现场发现 `PIXIV_PROXY` 为空，适配器显式传 `--no-proxy`，而 Windows 系统代理已开启。无凭据实测：直连 OAuth 主机超时，系统代理可收到 HTTP 响应。进一步使用真实 v1.1.1 CLI、受控 loopback 提交和模拟无效授权码，经系统代理收到 `pixiv:Complete: credentials_expired`，当前分类为 `login_exchange_failed`。这验证了 CLI 请求到达上游，并非真实账号登录成功。

新增 `PIXIV_USE_SYSTEM_PROXY`（Windows 默认为 true）：显式 `PIXIV_PROXY` 优先，为空时沿用系统/环境的 HTTP(S) 代理；可关闭继承以直连。CLI、API、手工兑换和 CDN 下载共用解析结果，HTTP 库不再隐式选择其他代理；PAC 不在本次支持范围。SDK reason 按白名单分类，授权、限流、网络与本地保存故障不会再一律回退为 `login_cli_failed`；不保存或输出 stderr、代理凭据和授权参数。

### 刷新推荐误掉线与作品解析修复

真实账号已成功绑定，但推荐和关注同步任务在取得客户端时被标记为 `reauth_required`。根因是 `plain()` 使用 `hasattr(value, "model_dump")` 判断响应类型：pixivpy 的 `JsonDict.__getattr__` 对不存在的属性返回 None，导致 hasattr 为真，再调用 None 产生 TypeError。该错误既影响登录刷新返回值，也影响推荐和关注 API 返回值；原客户端初始化又把所有异常都归类为凭据失效。

现在字典直接通过，其他对象仅调用可调用的 model_dump。令牌刷新同时兼容顶层与 response 嵌套格式，验证必要字段后初始化 API 凭据；刷新成功后的凭据仍先通过数据库 CAS 加密保存。网络、响应解析和客户端错误保留独立类别，只有明确的 invalid_grant 或 HTTP 401 才将账号标记为需要重新授权。

2026-10-03 在实际 D 盘项目的 8777 实例验证：现有绑定账号刷新收到 HTTP 200，更新凭据已保存；原生推荐任务返回 89 个候选、综合推荐返回 88 个候选，均无上游警告；关注更新任务读取 30 个投稿，缓存列表已有 80 个可展示作品。三类列表均返回 HTTP 200，对各自首个作品的预览请求均返回有效 image/webp，账号保持 connected。这些数量是验证时的快照，会随刷新和内容筛选变化。

回归测试使用真实 pixivpy 的解析对象与推荐/关注方法，仅替换 HTTP 传输，覆盖此前假客户端未能暴露的 JsonDict 行为；另覆盖两种刷新响应格式、凭据保存及网络/格式错误不触发掉线。完整测试共 342 项通过。

同一实际实例的无模拟浏览器检查通过：综合推荐点击“换一批”后任务完成，刷新页面账号仍为 connected；综合推荐、Pixiv 推荐与关注更新均显示每页 20 张卡片，实际预览图成功解码，未出现页面脚本异常。检查使用独立临时站内会话，结束后注销该会话。
