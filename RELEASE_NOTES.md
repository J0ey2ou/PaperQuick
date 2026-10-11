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
