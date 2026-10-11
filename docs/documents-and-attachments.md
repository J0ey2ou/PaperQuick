# 文档与附件：把一篇研究的材料放在一起

适用于 [PaperQuick v3.2](https://github.com/J0ey2ou/PaperQuick/releases/tag/v3.2.0)。你可以把论文正文、补充材料、研究方案、Word 稿件和相关网址关联到同一篇文献，在阅读时随时调出附件比对，也可以直接在软件里转换 Word 和 PDF。

![正文与附件并排阅读，虚构演示数据](images/v32-attachments.png)

## 导入 PDF 或 Word

1. 进入 **文献分类**，点击 **导入 PDF / Word**。
2. 选择一份或多份 `.pdf`、`.docx`、`.doc` 文档，再选择或新建课题。
3. 完成后检查标题、作者、年份及 DOI；未能正确识别的信息可通过 **编辑信息** 补充。
4. 双击条目，或点击 **阅读正文**，进入文献阅读。也可在阅读页直接点击 **打开 PDF / Word**；从这里新导入的文档先放入默认课题，之后可重新分配。

**导入文件夹** 会读取所选文件夹及子目录内的 PDF / Word。文件复制到文献库中，原始文件保留。DOCX 的标题、作者、正文和参考文献尽量在本机提取；旧版 DOC 首先使用文件名作为标题，可手动补全。仍需核对提取结果，尤其是 DOI、作者和参考文献。

PDF 阅读和 DOCX 导入归档不要求安装 Word。**Word 分页阅读需要本机安装桌面版 Microsoft Word**：软件准备分页预览后，在原有阅读区翻页、缩放和记录笔记。这里是阅读预览；如需修改 Word 正文，在附件列表选择该文件后点击 **外部打开**，用 Word 编辑。

## 让正文与补充材料保持关联

在分类列表选中一篇文献，右键 **附件管理 / 比对阅读**，或在文献阅读页点击 **正文与附件**。

| 操作 | 用途 |
| --- | --- |
| 添加文件 | 一次收纳多份 PDF、Word、表格或其他补充材料；保留来源文件 |
| 添加网址 | 保存补充材料下载页、数据仓库或其他 HTTP / HTTPS 链接，并填写容易辨认的名称 |
| 修改名称 | 给附件起一个清楚的显示名称，例如“补充表 1”“研究方案”“Word 稿件” |
| 设为正文 | 将当前文献的一份 PDF / Word 作为主要阅读文件；原正文保留为补充材料 |
| 并排阅读 | 在正文旁调出选中的 PDF / Word 附件 |
| 外部打开 | 用浏览器打开网址，或用本机对应软件打开文件 |

每篇文献同时只有一份正文，可以有多份补充材料。仅关联网址或补充 PDF 不会让软件误以为正文已经下载；你仍可继续查找、下载论文全文。若条目尚无正文，添加 PDF / Word 后选中它，点击 **设为正文**。

网址保存的是链接，不会自动下载对应文件。打开网页并下载后，再通过 **添加文件** 关联到这篇文献。表格等非 PDF / Word 文件可以收纳并外部打开，当前不在页内预览。

## 一边看正文，一边翻附件

1. 在阅读页点击 **正文与附件**，选中 PDF 或 Word 附件，点击 **并排阅读**。
2. 左侧继续显示正文，右侧出现 **附件比对**。两边的页码互相独立，可分别上一页、下一页和跳页。
3. 右侧下拉框可以切换其他附件；点击 **适宽** 调整显示，拖动正文与附件之间的分隔线分配宽度。
4. 需要更大空间时点击 **显示 / 收起笔记**；要专心阅读正文，点击附件区 **收起**。以后可从顶部 **附件比对** 再次打开。

右侧附件区用于比对翻阅；正文阅读区继续提供高亮、批注、书签和右键笔记。整篇文献共用一份阅读笔记，方便把正文和补充材料的发现写在一起。高亮、批注及书签跟随各自文件：将附件设为正文后，不会把另一份文件的批注放到错误页面；切回原文件即可继续查看。阅读时长按整个前台阅读页面计算，不会因打开第二份附件而重复累加。

## Word 转 PDF，PDF 转 Word

![Word / PDF 转换窗口](images/v32-conversion.png)

1. 在阅读页点击 **Word / PDF 转换**，或在分类列表右键 **Word / PDF 互转**。
2. 核对文件，也可以点击 **选择文件** 换一份。选择 Word 时转换为 PDF；选择 PDF 时转换为 `.docx`，并选择 **可编辑文字** 或 **保留页面外观**。
3. 点击 **转换并另存为**，使用新的文件名保存。软件保留输入文件，也不会覆盖已有输出文件。
4. 从某篇文献进入时，可以勾选 **转换后，将新文件作为附件收纳到当前文献**。转换完成后，新文件自动关联，之后仍可重命名、设为正文或并排阅读。
5. 等待窗口提示完成，核对转换结果后关闭窗口。若文件已转换成功但暂时未能关联，输出文件仍保留，可稍后重新添加附件。

PDF 转 Word 无需安装 Word，提供两种本地转换方式：

| 方式 | 适合的需要 | 输出内容 |
| --- | --- | --- |
| 可编辑文字（默认） | 提取文章文字，继续整理或编辑 | 保留可提取正文与逐页分隔，不还原图表、公式布局、复杂分栏或其他复杂排版；没有可提取文字的扫描页保留为原页图片 |
| 保留页面外观 | 把原页面放进 Word，便于查看和排入其他文档 | 每页保存为图片，图片中的文字不能直接编辑 |

两种模式都不进行 OCR。请按需要选择并核对结果；提取文字的顺序仍可能受 PDF 分栏影响。

**Word 转 PDF 和 Word 分页预览需要本机的桌面版 Microsoft Word**，使用本机字体；缺失字体可能影响排版。依赖 Word 的功能目前不支持用 WPS 或 Word 网页版替代。所有转换均在本机完成，不上传文档，不调用外部 AI。即使没有安装 Word，也可生成和保存 DOCX；若要在文献直达中对生成的 DOCX 分页预览，仍需安装 Word。

整份 PDF 都没有可提取文字时，软件会提示选择“保留页面外观”。混合文档中的无文字页会保留为图片，不会被跳过。

## 命名、恢复和备份

**命名规则** 适用于库内的本地文件。正文按所选课题的规则命名；补充材料保留名称并带独立后缀，PDF、DOCX、DOC 和其他文件的扩展名不会被改错。网址附件不参与文件重命名。**修改名称** 改的是附件显示名称，如需同步调整归档文件名，再对该文献执行 **按规则重新命名**。

同一篇文献重复添加相同文件时复用已有附件。若归档副本被误移走，重新导入或关联原文件会恢复该附件，保留原附件标识、名称和已有批注；若原位置已经有不同内容，软件另存一份，不覆盖那份文件。

退出软件与托盘后，备份完整 `本地文献库` 文件夹。它包含正文、附件、笔记、批注、课题和阅读记录。只备份几份 PDF 或 Word 无法恢复这些关联。升级时保留旧库和设置；软件会保留原有文献，把旧文献的第一份文件作为正文，其余文件作为补充材料。

## English

Available in [PaperQuick v3.2](https://github.com/J0ey2ou/PaperQuick/releases/tag/v3.2.0). Keep a paper's main document, supplements, Word draft and related URLs together, compare documents side by side, and convert Word/PDF from the reader.

### Import and read

Use **Library → 导入 PDF / Word** to select `.pdf`, `.docx` or `.doc` and choose a project. Folder import also reads subfolders. Source files are copied and preserved. Review extracted metadata; legacy DOC uses the filename as its initial title. Double-click the paper or use **阅读正文** to read it. **Reader → 打开 PDF / Word** imports new documents into the default project, which can be changed later.

PDF-to-Word conversion, PDF reading and DOCX import/storage do not require Word. **Paginated Word previews, Word-to-PDF conversion and citation insertion require installed desktop Microsoft Word for Windows.** Word appears as a reading preview, not an embedded text editor. To edit its contents, select it in the attachment list and choose **外部打开**. WPS and Word Online are not supported substitutes for features that require Word.

### Add and compare attachments

Open **Library → right-click → 附件管理 / 比对阅读**, or **Reader → 正文与附件**. Choose **添加文件** for documents, tables and other materials, or **添加网址** for an HTTP/HTTPS URL. **修改名称** changes the display label. Each paper has one main document; select PDF/Word and choose **设为正文** to change it. The previous main file stays as a supplement. A URL or supplement alone is not treated as downloaded full text.

Select a PDF/Word supplement and choose **并排阅读**. Main text stays on the left; the comparison pane has independent page navigation, a document dropdown, fit-width and a resizable divider. **显示 / 收起笔记** toggles notes for more space, and **收起** hides the comparison pane. Other file types open in their local applications and URLs open in a browser; storing a URL does not download its content automatically.

Notes are shared by the paper. Highlights, comments and bookmarks remain attached to their original file, so changing the main document does not move annotations onto unrelated pages. The right comparison pane is for reading; annotation tools remain in the main reader. Opening a supplement does not add a second reading timer.

### Convert and retain the result

Use **Reader → Word / PDF 转换** or **Library → right-click → Word / PDF 互转**. Select the source, choose **转换并另存为**, and save under a new name. Word converts to PDF; PDF converts to DOCX. Existing source/output files are not overwritten. When opened for a library paper, enable **转换后，将新文件作为附件收纳到当前文献** to attach the output automatically.

PDF-to-Word conversion runs locally without Microsoft Word. Choose one of two modes:

- **Editable text (`可编辑文字`, default)** extracts available text and retains original-page separation. It does not reconstruct charts, tables, equation layout or complex columns. Pages with no extractable text, including scanned pages, are retained as page images. Reading order may need correction for complex PDFs.
- **Preserve page appearance (`保留页面外观`)** inserts every page as an image. The image text cannot be edited directly.

Neither mode performs OCR. Word-to-PDF conversion and paginated Word previews use installed Microsoft Word and local fonts; missing fonts can affect layout. All conversion stays on your computer and uses no AI. Generating a DOCX does not require Word, but previewing that DOCX as pages inside PaperQuick does.

If no text is extractable anywhere in the PDF, choose **Preserve page appearance**. In a mixed document, textless pages stay as images instead of being omitted.

### Naming and recovery

Bulk renaming preserves each file's extension and gives supplements distinct readable names; URL attachments are skipped. Display-label changes do not immediately rename files—apply the paper's naming rule when desired. Reimporting a missing copy restores the same attachment and keeps its notes and annotations. If different content already exists at the stored path, PaperQuick saves another copy rather than overwriting it.

Exit PaperQuick and its tray process before backing up the entire `本地文献库` directory. Preserve it and settings when upgrading. Existing metadata is retained; the first file of a legacy paper becomes its main document and the remaining files become supplements.
