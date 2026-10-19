# PaperQuick v3.4.1 预览 · 阅读互动与选框修复（2026-10-19）

- 阅读区新增选中文字 / 框选图片与 ChatGPT 网页互动，首次准备正文附件，发送后绑定同篇对话；需在默认浏览器加载新版扩展。网页适配尚需实际账号环境验证，详见 [接入说明](docs/chatgpt-reading.md)。
- 截图到笔记使用独立矩形选框，支持反向拖动、页面边界限制和 Esc 取消；无需提取选区文字，松开后直接裁剪页面。
- 跨页文字截图逐页裁剪并拼接，补渲染缓存外的页面；可在选区任一页右键，长图保存保留下方内容。
- 防止旧附件选区串用、无效选框、覆盖 ChatGPT 草稿和未确认上传后错误跳过正文。构建独立保留，不关闭或替换正在运行的程序。

# PaperQuick v3.4.0 · 单行阅读工具与自动保存（2026-10-15）

这一版把阅读工具收进单行图标，让正文和笔记获得更多空间，同时修复设置退出后未保留的问题。

## 本次更新

- **单行图标工具栏**：主阅读区、附件比对和笔记工具统一收成一行。悬停图标显示说明；窗口较窄时，剩余操作收进“更多”菜单，全部原有功能继续可用。页码可输入并按回车跳转。
- **设置自动保存**：皮肤、快捷键、邮箱、连续阅读、标记大小和研究笔记模板修改后自动保存；切换页面、收起到托盘、退出前保存待写入的修改。填写不完整的项目保留原有效值，其他有效设置继续保存。
- **关于信息**：设置底部新增版本号、开发者名称和 GitHub 项目入口。
- **完整继承近期改进**：包含琉璃皮肤、最近阅读、附件连续翻页、图谱分组与关系编辑、论文信息识别和显示名称整理；保留此前查询、分类、笔记批注、Word/PDF 转换、Word 引用、EndNote 交换等功能。

## 完整包与升级

下载 **PaperQuick-v3.4-Windows.zip**，适用于 Windows 10 / 11 64 位。这是包含主程序、选词助手、浏览器扩展和引用样式的完整包。

请在当前工作结束后自行从托盘退出软件和选词助手，备份原目录，再把新包内的程序文件覆盖到原目录。**保留完整“本地文献库”、settings.json、shortcut.json**，即可继续使用原有文献、附件、笔记、课题、阅读记录与设置。换安装目录时也要完整迁移这些内容。发布包不包含个人数据或空文献库。

本次仅进行后台及隐藏窗口验证，不操作桌面鼠标、键盘、剪贴板，不关闭或启动用户正在使用的程序。240 项测试中 237 项通过、3 项真实 Word 集成测试跳过；另完成图谱验证和独立构建检查。

[升级与使用说明](https://github.com/J0ey2ou/PaperQuick/blob/v3.4.0/docs/v3.4-upgrade.md)


---

# PaperQuick v3.3.0 · 阅读与整理升级（2026-10-14）

- 文件夹导入先勾选文件，支持撤回最近一批导入；已继续编辑或阅读的文献保留。
- 文献分类支持删除与恢复，保留来源文件。
- 连续阅读、默认文字选择、专注阅读和可调整宽度的正文 / 笔记区域。
- 图片笔记、阅读选区截图、剪贴板图片、自定义研究笔记模板。
- 右键关联文献、添加本地文档 / 网址链接和页内标记；设置中可调整标记大小。
- 参考文献嵌入阅读页顶部，可直接查原文与下载归档；修复 BMJ 无标题、断行 DOI 和年份误编号。
- 阅读区 Word / TXT 原文编辑，保存归档副本并保留上一版本；兼容原 Word / PDF 批注。
- 笔记导出后自动关联为“笔记”附件，图谱显示笔记节点与手动文献关联。

下载 `PaperQuick-v3.3-Windows.zip`，解压后运行 `文献直达.exe`。完整操作见 [v3.3 阅读升级指南](docs/v3.3-reading.md)，分享介绍见 [微信更新文案](docs/微信更新文案-v3.3.md)。

升级前请从托盘退出并备份原文件夹，覆盖程序文件时保留 `本地文献库`、`settings.json`、`shortcut.json`。Word 编辑和分页预览需要桌面版 Microsoft Word；扫描 PDF 的文字选择需要文字层，本版不提供 OCR。

---

# PaperQuick v3.2.0 · 从阅读整理到 Word 写作

这一版把论文正文、附件、阅读发现与写作引用连接起来。下载 `PaperQuick-v3.2-Windows.zip`，解压后运行 `文献直达.exe`。完整步骤见 [README](README.md)。

## 本次新增

- **PDF / Word 导入**：按课题收纳 PDF、DOCX、DOC，支持多选和文件夹导入，保留来源文件；Word 可在阅读页分页预览。
- **正文与附件关联**：为一篇文献添加补充文件和相关网址，修改附件名称、设置正文；在正文旁调出 PDF / Word 附件，独立翻页和跳页比对。
- **Word / PDF 互转**：从阅读页或分类右键菜单进入，另存新文件；转换结果可自动关联到当前文献。PDF 转 Word 提供“可编辑文字”和“保留页面外观”两种方式，无需安装 Word。
- **Word 引用**：插入单篇或多篇正文引文，生成参考文献表，统一更新编号或切换格式。内置 31 套常用 CSL 样式，可导入更多期刊格式，支持手动编辑及按 DOI 补全文献信息。
- **阅读总结四栏目**：阅读回顾、主题与检索、引用与被引、主题追踪。按天或课题回顾阅读、整理关键词，生成 PubMed / Web of Science / Google Scholar / Europe PMC 检索式。
- **沿引用关系继续发现**：联网寻找起点论文引用的、或引用它的未收藏文献；保留线索，可继续查原文或收藏到课题。
- **新文献追踪**：保存主题、手动检查或在软件运行时每日检查。历史发现可以撤回和恢复，已收藏的文件与笔记保留。

## 整理与阅读更连贯

批量命名保留真实扩展名，补充材料拥有独立文件名，网址不参与重命名。“已归档正文”包括 PDF 和 Word，只有补充材料时仍可继续查找论文正文。重新导入能恢复丢失的归档副本，并保留附件与笔记、批注的关联；遇到不同内容的现存文件时另存，避免覆盖。

继续提供全文查询、快捷键和网页右键、课题分类、阅读笔记和批注、参考文献提取、离线关系图谱、皮肤、托盘及 Windows 登录后台启动。

## 使用与升级

- Word 分页预览、Word 转 PDF 和 Word 引用需要本机安装 **Windows 桌面版 Microsoft Word**；PDF 转 Word、PDF 阅读和 DOCX 导入归档无需 Word。需要 Word 的功能不支持用 WPS 或 Word 网页版替代；正文引用暂不支持脚注、尾注样式。
- 文档转换在本机完成，不调用外部 AI。PDF 转 Word 默认提取可编辑正文并保留逐页分隔，不恢复图表和复杂排版；无可提取文字的扫描页保留原页图片。“保留页面外观”模式将每页作为图片，文字不可直接编辑。两种方式都不提供 OCR。
- 引用探索与主题追踪通过 Europe PMC 联网，无需用户申请密钥，主要覆盖生命科学与医学。DOI 补全使用 Crossref；公开数据不保证覆盖所有文献或引用。
- EndNote 兼容仍为只读导入、差异预览和 XML 交换，**不是已有条目的全自动双向写回**。
- 升级前从托盘退出并备份完整旧目录，更新程序文件，保留 `本地文献库`、`settings.json` 和 `shortcut.json`。发布包和演示截图不含个人文献库。

[文档与附件操作](docs/documents-and-attachments.md) · [Word 引用操作](docs/word-citations.md) · [阅读总结与追踪](docs/v3.2-local.md)

## English

**PaperQuick v3.2.0 connects literature collection, attachment reading and Word writing.** Download `PaperQuick-v3.2-Windows.zip`, extract the complete folder and run `文献直达.exe` on Windows 10/11 x64.

New features include PDF/DOCX/DOC import, paginated Word previews, linked supplements and URLs, independent side-by-side page navigation, and Word/PDF conversion with optional automatic attachment. Word citations support single/multiple references, bibliography generation and style updates with 31 bundled CSL styles plus custom styles.

The four-tab recap provides reading review, local topic keywords and editable search queries, online reference/citing-paper exploration, and topic tracking with reversible discovery history. Collected files and notes are preserved when a discovery batch is withdrawn. Renaming preserves file types and supplement names; reimport can restore missing copies without losing attachment identity or overwriting different content already at the stored path.

Installed **Microsoft Word for Windows** is required for Word pagination, Word-to-PDF conversion and citation insertion. PDF-to-Word conversion, PDF reading and DOCX storage work without Word. WPS and Word Online are not supported substitutes for features requiring Word; footnote/endnote citation styles are not supported. PDF-to-Word runs locally in two modes: editable text with original-page separation (without reconstructing charts or complex layouts, and retaining scanned pages as images), or every page as an image whose text cannot be edited directly. Neither mode performs OCR or uses external AI.

Europe PMC discovery/tracking and Crossref DOI completion need internet access. Coverage is incomplete and mainly life-science/medical for discovery. EndNote remains read-only import and reviewed XML exchange, not automatic write-back. Exit, back up the complete library and retain library/settings when upgrading. No personal library data is included.
