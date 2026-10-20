# 本项目协作约束

- 用户要求仅在后台测试。禁止调用桌面虚拟鼠标、键盘模拟、前台窗口控制或屏幕截图；禁止测试抢焦点、移动鼠标或改动剪贴板。
- GUI 验证必须使用隐藏窗口或隔离环境，不运行会显示界面、唤起浏览器或启动全局选词助手的测试。
- 构建和安装不得主动关闭用户正在使用的程序或弹出新窗口。程序被占用时保留新构建，待安全更新。

## 版本发布与自动更新（用户要求长期保持）

- 设置内的“检查更新 / 下载并在退出后更新”固定连接 `J0ey2ou/PaperQuick` 的 GitHub Releases。后续更新必须保持此入口有效，不要求用户反复手动下载。
- 每次版本升级同步 `app_version.py`、`version.json`、README、RELEASE_NOTES 和升级说明；完整包名为 `PaperQuick-vX.Y.Z-Windows.zip`，内部根目录为 `PaperQuick-vX.Y.Z/`。
- 发布包必须包含 `version.json` 和 `update-manifest.json`（schema 1，版本号与各公开文件 SHA256）。使用 `scripts/write_update_manifest.py` 或 `scripts/package_release.py` 生成，不包含个人文献库、设置、快捷键配置或运行数据。
- GitHub 发布资产须上传完成并具备 SHA256 digest，附上 SHA256SUMS.txt 与更新说明；正式版设为最新发布，预览版只在启用“接收预览版”时提示。
- 正式发布必须额外上传 `scripts/package_release.py` 生成的 `update.json`；正式版客户端优先从 `releases/latest/download/update.json` 检查，以免 GitHub 匿名 API 限流导致更新入口不可用。发布后用真实客户端检查逻辑验证公开清单可读、版本和安装包 SHA256 正确，再结束发布工作。
- 自动更新仅在正常退出后安装；不得强制关闭程序、选词助手或 Word。替换失败回滚，保留文献库和设置。只做后台及隐藏/隔离验证。
- 源码提交与安装包发布不等于授权合并主分支；沿用已授权范围。
- 主分支要求验证签名。通过 GitHub 接口发布源码时使用 GraphQL `createCommitOnBranch`，检查提交 `verification.verified=true` 且远端 tree 与本地暂存 tree 一致后再创建 PR；不要再用未签名的 Git Database commit 发布，不得关闭保护规则。
