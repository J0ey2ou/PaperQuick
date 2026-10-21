# PaperQuick v3.7.0 macOS 试用构建

按用户要求，仅在原生 macOS 构建机打包，**未启动应用、未进行功能或界面测试**。包含 v3.7.0 的文献整理、PDF 阅读与笔记、位置链接、六家 AI 网页接入及兼容 API 模式代码。不能将打包成功理解为功能已验证。

## 选择与安装

- Apple 芯片（M 系列）：下载 `PaperQuick-v3.7.0-macOS-arm64.zip`。
- Intel 芯片：下载 `PaperQuick-v3.7.0-macOS-x86_64.zip`。
- 解压后，把 `PaperQuick.app` 拖到“应用程序”或用户自己的 `~/Applications` 文件夹，再打开应用。此构建面向 macOS 12 及以上；具体依赖与系统兼容性尚未实测。
- 包使用临时 ad-hoc 签名，**没有 Apple Developer ID 签名或 Apple 公证**。首次打开可能被 macOS 拦截；确认下载来源后，可使用系统“隐私与安全性”中的“仍要打开”。不需要关闭系统安全保护。

文献库和设置位于 `~/Library/Application Support/PaperQuick/`，与 `.app` 分开保存，替换应用时保留。请不要把正在使用的 Windows 文献库直接覆盖到这里；迁移前另存完整备份。API Key 通过 macOS 登录钥匙串保护的密钥加密，Windows DPAPI 密文不能直接迁移，请在 Mac 重新填写。

浏览器扩展位于 `PaperQuick.app/Contents/Resources/browser-extension`（在 Finder 中右键应用 → 显示包内容）。Chrome / Edge 中启用开发者模式，加载该文件夹；更新应用后重新加载扩展、刷新 AI 网页。Safari 扩展不包含在本包。

## 与 Windows 版的边界

- Windows 全局选词助手、托盘驻留和登录启动组件没有包含。Mac 版关闭窗口即正常退出；使用软件内选文右键、浏览器扩展或粘贴查询。
- Windows COM Word 实时引文、Word 分页预览 / Word 转 PDF 没有移植；相关操作会显示平台限制。可先从 Word 导出 PDF 后阅读。独立 CSL 格式化及 PDF 转 DOCX 的跨平台代码和原生 Node 运行时已包含，但未实测。
- 新增 Mac 文件打开、中文字体、右键/Control-click、Command 文本编辑快捷键及钥匙串适配；这些均未经过功能测试。
- 设置内检查更新继续连接 `J0ey2ou/PaperQuick`，使用独立 Mac 架构清单与安装包，绝不下载 Windows EXE。新版本校验后在正常退出时替换 `.app`，保留旧应用备份和独立文献数据；没有权限写入应用目录时提示先移至可写位置。更新安装本身亦未实测。

本包以独立 Mac 预览发布提供，不替换 Windows 最新正式版；后续维护应继续生成对应架构包和 `update-macos-<架构>.json`，正式 Mac 发布时把清单附到同一 GitHub 正式发布，使设置内入口保持有效。
