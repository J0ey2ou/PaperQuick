# 文献直达 · PaperQuick

**导师发来一段引用，合作者转来一篇推送——选中论文标题，直接到原文入口。**

Windows 本地小工具 + Edge / Chrome 扩展。支持论文标题、DOI、arXiv 编号和可读取的推送链接；自动匹配论文、查找开放 PDF / 全文，匹配明确时打开网站。**无需 Python、无需账号；支持自定义全局快捷键。**

[下载 Windows 软件包](https://github.com/J0ey2ou/PaperQuick/releases/latest) · [English](#english) · [完整中文说明](使用说明.md)

![浏览器扩展查询结果：公开论文示例](docs/images/browser.png)

![选词查询流程动图](docs/images/demo.gif)

动图使用公开论文固定数据演示选词查询流程，未展示原生右键菜单，演示等待不代表实际网速。[微信推送文案及素材](推送文案.md)；下载推送 HTML 后打开，可一键复制图文，也可单独保存截图 / 动图。

## 三种用法

### 1. 复制 → 粘贴并查找

1. 下载 Release 中的 `PaperQuick-v2.3-Windows.zip`，**先解压整个软件包**。
2. 双击 `文献直达.exe`，不需要安装 Python。
3. 复制完整英文论文标题、DOI、arXiv 链接或推送链接，点击 **粘贴并查找**。也可以手动粘贴，点击 **查找原文** 或按 `Ctrl + Enter`。
4. 结果陆续显示，链接出现即可点击 **开放 PDF / 开放原文 / 出版社**；可复制单个地址或全部链接。
5. 接口较慢时，点击 **直接学术搜索**，当前标题会自动带入 Google Scholar。

### 2. Word / PDF / 微信 → 选中后按快捷键

1. 在文献直达中点击 **全局快捷键**，助手会驻留系统托盘。也可双击 `全局选词助手.exe`。
2. 在原软件中选中可复制的论文标题 / DOI。
3. 按软件状态栏或托盘菜单显示的快捷键，自动查询，匹配明确时打开原文网站。
4. **自定义快捷键**：点击主界面 **设置**，点击快捷键输入框并按下想使用的组合（也可手动填入），点击 **保存并启用**。例如 `Ctrl + Alt + J`。也可右键托盘图标 → **自定义快捷键…** → 按键 → 保存。
5. 支持至少两个修饰键（`Ctrl` / `Alt` / `Shift`）+ 字母、数字或 `F1–F24`。设置立即生效、下次启动继续使用。发生占用时以状态栏 / 托盘显示的实际组合为准。
6. 默认尝试 `Ctrl + Alt + F`；占用时依次尝试 `Ctrl + Alt + Shift + F`、`Ctrl + Alt + F8`。右键托盘图标可退出助手；关闭主窗口不会退出助手。

### 3. Edge / Chrome → 选中后右键

1. 地址栏打开 `edge://extensions` 或 `chrome://extensions`。
2. 开启开发者模式 → **加载已解压的扩展** → 选择软件包内的 `browser-extension` 文件夹。
3. 选中英文论文标题 / DOI → 右键 → **查找文献并打开原文**。
4. 在已显示正文的推送页面，也可右键 **查找当前页面中的论文**，或点击扩展图标。公众号要求验证时，先在浏览器手动完成验证，再查询。
5. 扩展独立工作，无需开启桌面软件。更新文件后，在扩展管理页点击 **重新加载**。单位策略可能限制加载本地扩展。

## 自动打开与访问范围

- 单一 DOI 查询先打开 DOI / 出版社入口；arXiv 编号先打开 PDF，其他开放版本后台补齐。标题仅在候选检索阶段结束且唯一完全匹配时自动打开；同名或近似结果需要核对。
- 开放版本来自 Europe PMC、arXiv、Semantic Scholar，可选 Unpaywall；Crossref 提供元数据和出版社入口。预印本 / 作者稿可能与正式版本不同；付费文献可能需要机构订阅，链接也可能失效。
- 软件提供下载入口，由浏览器打开 / 下载，**不自动保存论文文件**。扫描版 PDF 需要 OCR，禁复制或管理员窗口可能无法选词。
- 本地运行仍需要联网。标题 / DOI 会发送到检索服务；输入网页链接时读取该网页。无查询历史、无鼠标跟随、无自动开机启动。快捷键触发后会复制选词，剪贴板会变为该文字。
- 可选邮箱保存在 `settings.json`，快捷键保存在 `shortcut.json`；二者不随 Release 分发。直接学术搜索仅在点击时将查询发送到 Google Scholar。

## 源码运行 / 打包

Python 3.10+，桌面检索仅使用标准库；全局助手使用 Windows 自带 .NET Framework。

```powershell
python app.py
python -m unittest discover -s tests -v
python tests/gui_smoke.py
# 打包需要 PyInstaller 和 Pillow
python -m pip install pyinstaller pillow
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

`tests/live_check.py` / `tests/speed_check.py` 使用公开论文示例联网检查。浏览器扩展集成测试需要 Node.js 和 Playwright：`npm install --no-save playwright`，`npx playwright install chromium`，然后 `node tests/extension_check.cjs`。截图为公开论文示例演示，响应时间受网络和接口影响。

---

## English

**A citation from your supervisor. A research post from a collaborator. Select the paper title and get to the full text.**

PaperQuick is a small Windows desktop app plus an Edge / Chrome extension. It accepts paper titles, DOIs, arXiv IDs and readable article links, finds full-text / PDF entry points, and opens a website when the match is clear. No Python installation or account is needed for the packaged app.

### Download and paste a query

1. Download `PaperQuick-v2.3-Windows.zip` from [Releases](https://github.com/J0ey2ou/PaperQuick/releases/latest), then **extract the complete archive**.
2. Run `文献直达.exe`. Keep the helper, extension folder and guide beside it.
3. Copy an English paper title, DOI, arXiv link or research-post link. Click **粘贴并查找** (Paste & Search), or paste manually and use **查找原文** (Find Full Text) / `Ctrl + Enter`.
4. Results appear as services respond. Open or copy PDF, full-text and publisher links. **直接学术搜索** (Search Google Scholar) opens the current query directly when an API is slow.

### Selected text in Word, PDF readers or desktop WeChat

1. Click **全局快捷键** (Global Shortcut), or run `全局选词助手.exe`. The helper stays in the system tray.
2. Select a copyable title / DOI in your original app, then press the shortcut shown in the status bar or tray menu.
3. To customize it, open **设置** (Settings), click the shortcut field, press your combination (or type it), and click **保存并启用** (Save & Enable). Alternatively, right-click the tray icon → **自定义快捷键…** (Customize Shortcut) → press a combination → save.
4. Use at least two modifiers from `Ctrl`, `Alt`, `Shift`, followed by a letter, digit or `F1–F24`, e.g. `Ctrl + Alt + J`. Changes apply immediately and persist across restarts. If a new combination is occupied, the active shortcut stays available; check the displayed status.
5. Default: `Ctrl + Alt + F`, falling back to `Ctrl + Alt + Shift + F`, then `Ctrl + Alt + F8`. Exit the helper from its tray menu. Closing the main app leaves the helper running.

### Browser context menu

1. Open `edge://extensions` or `chrome://extensions`.
2. Enable Developer Mode → Load Unpacked → choose the included `browser-extension` folder.
3. Select a title / DOI, then right-click → **查找文献并打开原文** (Find Paper and Open Full Text).
4. On a visible article, use **查找当前页面中的论文** (Find Papers on This Page) or click the extension icon. Complete WeChat verification manually before querying the rendered page.
5. The extension works without the desktop app. Reload it from the extensions page after an update. Managed browsers may prohibit unpacked extensions.

### Behavior and limits

A single DOI opens its publisher / DOI page immediately; an arXiv ID opens its PDF. Other versions are added in the background. Title searches auto-open only after candidate discovery and a unique exact title match; ambiguous results require review. Open versions may be preprints or accepted manuscripts. Subscription papers may require institutional access, and links may become unavailable.

The app returns download links; the browser handles files. It needs internet access and sends titles / DOIs to literature services. It does not keep query history, track the mouse or start automatically with Windows. The hotkey copies selected text into your clipboard. Scanned / protected PDFs and elevated windows may not support copying.

Optional Unpaywall email and shortcut preferences are stored locally in `settings.json` and `shortcut.json`; neither is shipped. Google Scholar receives a query only when you click its search button. Source run / build commands are shown above. Screenshots demonstrate a public paper; response time depends on the network.

The GIF demonstrates the selection-to-results flow with a public-paper fixture. The native context menu is not captured, and the timing is not a network benchmark. [Promotion materials](推送文案.md) include a self-contained HTML page with rich-text copying and downloadable screenshots / GIF.
