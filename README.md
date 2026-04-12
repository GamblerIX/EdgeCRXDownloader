# Edge CRX Downloader

一个用于批量下载 Microsoft Edge 扩展的 CRX 文件的桌面下载器。本项目提供两个实现版本：

- **Tauri 版本**：基于 Nuxt 4 + Tauri v2 + Rust，性能优异，包体积小。
- **PySide6 + QFluent 版本**：基于 Python + PySide6 + QFluentWidgets，易于修改和扩展。

## 功能

- 支持粘贴扩展 ID 或 Edge 商店详情页 URL
- 支持按行批量下载
- 支持选择本地保存目录
- 实时显示每个任务的下载进度
- 保留执行日志和最终结果摘要

---

## 📁 项目结构

```text
EdgeCRXDownloader/
├─ qfluent/                 # PySide6 + QFluent 版本
│  ├─ main.py
│  ├─ main_window.py
│  └─ requirements.txt
├─ tauri/                   # Tauri + Nuxt 版本
│  ├─ assets/
│  ├─ pages/
│  ├─ scripts/
│  ├─ src-tauri/
│  │  ├─ src/
│  │  ├─ Cargo.toml
│  │  └─ ...
│  ├─ utils/
│  ├─ app.vue
│  ├─ nuxt.config.ts
│  ├─ package.json
│  └─ tsconfig.json
├─ .github/
├─ LICENSE
└─ README.md
```

---

## 🦀 Tauri 版本（Rust + Nuxt）

### 技术栈

- 前端：Nuxt 4
- 桌面壳：Tauri v2
- 下载引擎：Rust
- 进度通信：Tauri `Channel`

### 启动方式

进入 `tauri` 目录：

```bash
cd tauri
```

安装前端依赖：

```bash
npm install
```

生成 Tauri 图标资源：

```bash
npm run tauri:icon
```

开发模式启动桌面应用：

```bash
npm run tauri:dev
```

构建静态前端并打包桌面应用：

```bash
npm run tauri:build
```

### GitHub Actions (Tauri)

- `CI.yml`：在 `push` 和 `pull_request` 时执行，校验 Nuxt 静态构建，并在 Windows 上执行 `tauri build -- --no-bundle`。
- `CD.yml`：在手动触发或推送 `v*` 标签时执行，构建 Windows NSIS 安装包并创建 GitHub Release。
- 发布建议使用与应用版本一致的标签，例如 `v0.1.0`。
- 如果 Release 创建失败，请到 GitHub 仓库 `Settings -> Actions -> General` 中确认 `GITHUB_TOKEN` 具备 `Read and write permissions`。

### 说明

- Tauri 打包图标由 `tauri/app-icon.svg` 生成。
- 首次运行前建议先执行 `npm install` 和 `npm run tauri:icon`。

### Tauri 项目结构

```text
tauri/
├─ assets/
├─ pages/
├─ scripts/
├─ src-tauri/
│  ├─ src/
│  ├─ Cargo.toml
│  └─ ...
├─ utils/
├─ app.vue
├─ nuxt.config.ts
├─ package.json
└─ tsconfig.json
```

---

## 🐍 PySide6 + QFluent 版本（Python）

### 技术栈

- Python 3.8+
- PySide6
- QFluentWidgets
- aiohttp

### 安装依赖

进入 `qfluent` 目录并安装依赖：

```bash
cd qfluent
pip install -r requirements.txt
```

### 运行程序

```bash
python main.py
```

### 构建可执行文件（可选）

可使用 `PyInstaller` 打包为独立可执行文件：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed main.py
```

---

## 输入格式

每行一个输入，支持两种格式：

1. 32 位扩展 ID
2. Edge 商店详情页 URL

真实样例示例：

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
- 无效输入会在队列中直接标红，不会阻塞其他条目
- 失败原因会同步到界面日志和结果面板
