# Edge CRX Downloader

一个桌面下载器，用于批量下载 Microsoft Edge 扩展的 CRX 文件。项目提供两种技术实现，功能完全一致。

| 版本 | 技术栈 | 目录 |
|------|--------|------|
| **Tauri** | Nuxt 4 + Tauri v2 + Rust | `tauri/` |
| **QFluent** | Python + PySide6 + QFluentWidgets | `qfluent/` |

## 功能

- 支持粘贴扩展 ID 或 Edge 商店详情页 URL
- 支持按行批量下载
- 支持选择本地保存目录
- 实时显示每个任务的下载进度
- 保留执行日志和最终结果摘要

## 快速开始

### Tauri 版本（Nuxt + Rust）

```bash
cd tauri
npm install
npm run tauri:icon   # 首次运行：生成图标资源
npm run tauri:dev    # 开发模式
npm run tauri:build  # 构建发布包
```

### QFluent 版本（Python + PySide6）

```bash
cd qfluent
pip install -r requirements.txt
python main.py
```

## GitHub Actions

- **CI** (`CI.yml`)：
  - **Tauri 作业**：在 `push` / `pull_request` 时执行，校验版本配置、Nuxt 静态构建，并在 Windows 上验证 Tauri 构建。
  - **QFluent 作业**：使用 Python 3.12，运行 flake8 代码检查和 pytest 单元测试。
- **CD** (`CD.yml`)：
  - 在手动触发或推送 `v*` 标签时执行。
  - 构建 Tauri Windows NSIS 安装包并创建 GitHub Release。
  - （可选）使用 PyInstaller 打包 QFluent 可执行文件。
- 发布建议使用与应用版本一致的标签，例如 `v1.0.0`。
- 如果 Release 创建失败，请到 GitHub 仓库 `Settings → Actions → General` 中确认 `GITHUB_TOKEN` 具备 `Read and write permissions`。

## 输入格式

每行一个输入，支持两种格式：

1. 32 位扩展 ID
2. Edge 商店详情页 URL

示例：

```text
# 篡改猴
iikmkjmpaadaobahmlepeloendndfphd
```

```text
# 篡改猴
https://microsoftedge.microsoft.com/addons/detail/edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN
```

## 输出行为

- 下载文件会被保存为 `{extensionId}.crx`
- 如果目标文件已存在，会被覆盖
- 无效输入会在队列中直接标记，不会阻塞其他条目
- 失败原因会同步到界面日志和结果面板

## 项目结构

```text
EdgeCRXDownloader/
├─ tauri/                  # Tauri 版本 (Nuxt 4 + Tauri v2 + Rust)
│  ├─ assets/
│  ├─ pages/
│  ├─ scripts/
│  ├─ src-tauri/
│  ├─ tests/
│  ├─ utils/
│  ├─ app.vue
│  ├─ nuxt.config.ts
│  ├─ package.json
│  └─ tsconfig.json
├─ qfluent/                # QFluent 版本 (Python + PySide6 + QFluentWidgets)
│  ├─ core/
│  │  ├─ downloader.py     # CRX 下载引擎
│  │  ├─ error.py          # 用户级错误处理
│  │  └─ extension.py      # 输入解析与格式化
│  ├─ tests/
│  │  ├─ test_downloader.py
│  │  ├─ test_error.py
│  │  └─ test_extension.py
│  ├─ main.py              # 应用入口
│  ├─ main_window.py       # Fluent Design 主窗口
│  └─ requirements.txt
├─ .github/
│  ├─ actions/setup-project/
│  └─ workflows/
│     ├─ CI.yml
│     └─ CD.yml
├─ .gitignore
├─ LICENSE
└─ README.md
```

## 说明

- Tauri 打包图标由 `tauri/src-tauri/app-icon.svg` 生成。
- Tauri 版本首次运行前建议先执行 `npm install` 和 `npm run tauri:icon`。
- QFluent 版本需要 Python 3.10+ 和图形化桌面环境。
