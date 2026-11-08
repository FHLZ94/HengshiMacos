# 衡势 Mac 构建

Mac 版使用 Electron 窗口和同一套 Python 数据分析服务；Electron 渲染进程开启隔离与沙箱，只通过受限本地桥接调用后端。用户数据保存在 macOS 应用数据目录，不写入应用程序包。

## GitHub Actions

在仓库 Actions 中手动运行“构建衡势 Intel 与 Apple Silicon Mac 安装包”。工作流矩阵分别在 Intel runner 和 Apple Silicon runner 上执行测试、打包对应架构的 Python 后端、构建 Electron 应用并上传两个 DMG artifact。工作流不会自动发布公开 Release。

## 本机构建

本地脚本 `build_macos_intel.py` 适用于 Intel Mac，需 Python 3.11、Node.js 24 和 pnpm 11。Apple Silicon 请使用上述工作流的 arm64 构建目标。1.2.0 安装包分别为 `衡势-1.2.0-macOS-Intel.dmg` 和 `衡势-1.2.0-macOS-Apple-Silicon.dmg`。

未配置 Apple Developer ID 时生成的 DMG 不带签名和公证。公开分发前，需要在 macOS 上进行签名、公证及安装验收。Windows 本机不能代表这些验证。
