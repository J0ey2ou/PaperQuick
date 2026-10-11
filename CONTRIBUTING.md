# 参与 PaperQuick / Contributing

公开协作仓库：https://github.com/J0ey2ou/PaperQuick

- 问题：Issues → New issue，提供复现步骤、版本和脱敏截图。
- 讨论：Discussions 适合使用方法、功能设计与协作招募。
- 代码：Fork → 建立功能分支 → 修改和验证 → 向 main 提交 Pull Request。
- 邀请：所有者打开 Settings → Collaborators（[入口](https://github.com/J0ey2ou/PaperQuick/settings/access)）→ Add people，输入对方 GitHub 用户名。对方接受邀请后获得协作权限。分享链接不等于邀请，不要发送密码或 token。

欢迎参与 PDF 引用解析、图谱布局、可访问性、EndNote 交换、阅读体验、文档与测试。新增功能先讨论范围；EndNote 已有记录自动写回仍待实现。

## 本地开发

使用 Windows、Python 3.13（开发环境版本），在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
python scripts/prepare_word_assets.py --node "C:\path\to\node.exe"
powershell -File scripts/build_word_bridge.ps1
powershell -File scripts/build_document_converter.ps1
python -m unittest discover -s tests -v
python app.py
```

引用格式使用随包提供的 citeproc-js、CSL 样式和语言文件。开发环境第一次准备资源时需要联网，并提供官方 Windows `node.exe`；Node 已在 PATH 中时可省略 `--node`。准备脚本记录来源与校验信息，之后引用排版离线完成。`node.exe` 和编译后的助手不提交到源码仓库，但要包含在发布包中；原始许可证和来源说明必须保留，引用窗口中的 citeproc-js 署名也应保留。

原生 GUI 回归包括 `tests/*gui_smoke.py`、`tests/reader_routes_smoke.py`，文档功能重点验证 `tests/attachment_reader_smoke.py`、Word 引用及转换测试。测试使用 `build` 下临时库，不要替换成真实库。需要实际 Word 的测试必须使用独立测试文档，不操作用户正在写作的文档。Word 分页预览、Word 转 PDF 和引用插入需要桌面版 Microsoft Word；PDF 转 Word 的文字与页面图片两种方式应在未连接 Word 的情况下验证。

退出正式程序和托盘助手后执行 `powershell -File build.ps1`；C# 助手使用 Windows .NET Framework 编译器。重建转换助手可单独执行 `powershell -File scripts/build_document_converter.ps1`。`python scripts/package_local_preview.py` 使用公开文件清单打包新版，发布前检查其中包含新文档和许可证，且不含个人库或测试文稿。

架构：`paper_finder.py` 检索；`library_core.py` 文档与附件归档；`library_ui.py` 分类；`reader_ui.py` / `pdf_reader_core.py` 阅读；`attachment_ui.py` 附件与比对；`document_conversion.py` / `document_conversion_ui.py` 转换；`references.py` 参考文献；`word_citations.py` / `word_bridge.py` / `citation_styles.py` Word 引用；`graph_*` 图谱；`reading_stats.py` / `summary_ui.py` 阅读回顾与主题探索；`desktop_runtime.py` 单实例；`ui_theme.py` 皮肤；`selection-helper` 快捷键。

截图演示：`scripts/make_library_demo.py` → `scripts/prepare_v31_demo.py` → `scripts/preview_library_ui.py`，使用虚构文献和时长。不要把模拟时长当成真实测速。

不要提交 PDF、个人库、EndNote 数据、设置邮箱、账号、运行日志或 token。归档改动需验证重名与缺失文件、笔记保留；计时需验证离开前台、休眠和跨午夜。

## English

Use Issues for reproducible bugs, Discussions for workflows, and fork/PR for code. Owners invite collaborators via Settings → Collaborators → Add people; invitees must accept. A public link alone does not grant write access.

Develop on Windows with Python 3.13 and install `requirements-build.txt` in a virtual environment. Prepare citation resources with `scripts/prepare_word_assets.py --node <official-node.exe>` (initial network access required), then compile `scripts/build_word_bridge.ps1` and `scripts/build_document_converter.ps1`. Keep vendor licenses and visible citeproc-js attribution. The portable Node executable and compiled helpers are bundled in releases but not committed as source.

Run unit/relevant GUI tests and launch `app.py`. Desktop Microsoft Word is needed for Word pagination, Word-to-PDF and citation integration tests; use an isolated test document, never a user's open manuscript. Test both PDF-to-Word modes without attaching to Word. Close the app/helper before `build.ps1`. Tests and demos must use isolated fictional libraries. Never commit personal PDFs, databases, credentials or logs. Describe behavior, validation and limitations in each PR.
