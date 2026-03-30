# Edge CRX Downloader

一个基于 **Nuxt 4 + Tauri v2 + Rust** 的桌面下载器，用于批量下载 Microsoft Edge 扩展的 CRX 文件。

## 功能

- 支持粘贴扩展 ID 或 Edge 商店详情页 URL
- 支持按行批量下载
- 支持选择本地保存目录
- 实时显示每个任务的下载进度
- 保留执行日志和最终结果摘要
- 无需 Python 运行时

## 技术栈

- 前端：Nuxt 4
- 桌面壳：Tauri v2
- 下载引擎：Rust
- 进度通信：Tauri `Channel`

## 启动方式

先安装依赖：

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

## 输入格式

每行一个输入，支持两种格式：

1. 32 位扩展 ID
2. Edge 商店详情页 URL

示例：

```text
iikmkjmpaadaobahmlepeloendndfphd
https://microsoftedge.microsoft.com/addons/detail/edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN
```

## 输出行为

- 下载文件会被保存为 `{extensionId}.crx`
- 如果目标文件已存在，会被覆盖
- 无效输入会在队列中直接标红，不会阻塞其他条目
- 失败原因会同步到界面日志和结果面板

## 项目结构

```text
EdgeCRXDownloader/
├─ assets/
├─ pages/
├─ src-tauri/
├─ utils/
├─ app.vue
├─ nuxt.config.ts
├─ package.json
└─ tsconfig.json
```

## 说明

- 本项目不再使用旧版 Python 入口。
- Tauri 打包图标由 `src-tauri/app-icon.svg` 生成。
- 首次运行前建议先执行 `npm install` 和 `npm run tauri:icon`。
