# 文献直达 / PaperQuick v2.3.0

Windows 软件包解压后运行 `文献直达.exe`，无需安装 Python。快捷键助手、浏览器扩展和操作说明均在包内。

本版新增：

- 自定义全局快捷键：主界面“设置”或系统托盘“自定义快捷键”；保存后立即生效，下次启动保留。
- 快捷键冲突检测，切换失败时保留原组合；状态栏和托盘显示实际可用快捷键。
- 查询结果陆续显示，DOI / arXiv 入口立即可用，其他原文版本后台补齐。
- 中英文 README，三种使用方式的详细步骤，以及带实际界面截图的一键复制推送页。

下载 `PaperQuick-v2.3-Windows.zip` 并解压整个包。浏览器扩展更新后需在扩展管理页重新加载。原文访问需要联网，付费文献可能需要机构订阅。

---

Extract `PaperQuick-v2.3-Windows.zip` and run `文献直达.exe`. No Python installation is required. The archive includes the shortcut helper, browser extension and usage guides.

- Custom global shortcuts in Settings or the tray menu, applied immediately and saved across restarts.
- Conflict detection retains the previous shortcut when a change fails.
- Progressive results, immediate DOI / arXiv entry points, background enrichment.
- Bilingual README and a promotion page with one-click rich-text / screenshot copying.

Reload an installed browser extension after updating its folder. Internet access is required; subscription papers may require institutional access.

Validation: 35 Python tests; desktop GUI / frozen bundle checks; native registration, conflict, live-reload and restart checks; real Chromium extension and clipboard integration tests with public-paper fixtures.
