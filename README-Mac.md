# 衡势 Mac 构建

Mac 版使用 Electron 窗口和同一套 Python 数据分析服务；Electron 渲染进程开启隔离与沙箱，只通过受限本地桥接调用后端。用户数据保存在 macOS 应用数据目录，不写入应用程序包。

## GitHub Actions

在仓库 Actions 中手动运行“构建衡势 Intel 与 Apple Silicon Mac 安装包”。工作流矩阵分别在 Intel runner 和 Apple Silicon runner 上执行测试、打包对应架构的 Python 后端、构建 Electron 应用并上传两个 DMG artifact。工作流不会自动发布公开 Release。

## 本机构建

安装对应架构的 Python 3.11、Node.js 24 和 pnpm 11 后，在源码目录运行 `python3.11 build_macos_intel.py`。Intel 输出为 `electron/dist/衡势-1.1.0-macOS-Intel.dmg`；Apple Silicon 输出为 `衡势-1.1.0-macOS-Apple-Silicon.dmg`。

未配置 Apple Developer ID 时生成的 DMG 不带签名和公证。公开分发前，需要在 macOS 上进行签名、公证及安装验收。Windows 本机不能代表这些验证。
