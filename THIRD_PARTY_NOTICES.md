# 第三方组件与数据来源

- Chart.js 4.4.7，MIT License，https://www.chartjs.org/ 。本地前端包含其压缩 UMD 文件。
- Lucide 0.468.0，ISC License，https://lucide.dev/ 。本地前端包含其压缩 UMD 文件。
- 标普 500 成分名单快照来自 `datasets/s-and-p-500-companies`，https://github.com/datasets/s-and-p-500-companies ，仓库声明 Open Data Commons Public Domain Dedication and License。应用对其返回的成分数据标注快照日期；实时成分仍需来源核对。
- Inno Setup 简体中文语言文件来自 Inno Setup 官方源码仓库，由社区翻译维护。安装器使用该文件生成中文向导。
- Python 与 Electron 依赖按 `requirements*.txt` 和 `electron/pnpm-lock.yaml` 安装，遵守各自许可证。

新闻标题、摘要、行情及分析师预期来自各发布方；本项目只在本机研究使用，公开发布或再分发前需逐一核对数据源条款、缓存和展示权限。来源连接失败或受限时，软件显示缺失或最近缓存，不能视作完整市场覆盖。
