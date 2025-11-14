# Edge CRX Downloader

一个用于从Microsoft Edge扩展商店下载crx文件的Python工具，支持GUI和CLI两种模式。

## 功能特点

- ✅ 支持通过URL或扩展ID下载Edge扩展
- ✅ GUI模式支持批量下载（单线程逐个处理）
- ✅ CLI模式支持命令行快速下载
- ✅ 实时显示下载进度
- ✅ 零日志系统，错误即时反馈
- ✅ 单文件Python脚本，易于维护
- ✅ 可打包为独立exe文件

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### GUI模式

直接运行脚本启动图形界面：

```bash
python main.py
```

或双击运行打包后的exe文件。

**GUI功能：**

- 在文本框中输入扩展URL或ID（每行一个）
- 选择保存位置
- 点击"开始下载"按钮
- 查看实时进度和状态信息

### CLI模式

通过命令行参数直接下载：

```bash
# 使用扩展ID
python main.py iikmkjmpaadaobahmlepeloendndfphd

# 使用完整URL
python main.py --https://microsoftedge.microsoft.com/addons/detail/篡改猴/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN
```

CLI模式会将文件下载到当前工作目录。

## 输入格式

支持两种输入格式：

1. **完整URL**：
   ```
   https://microsoftedge.microsoft.com/addons/detail/篡改猴/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN
   ```

2. **扩展ID**（32个小写字母）：
   ```
   iikmkjmpaadaobahmlepeloendndfphd
   ```

## 打包为exe

使用PyInstaller打包为独立可执行文件：

```bash
# CLI兼容版本（推荐）
pyinstaller --onefile --name EdgeCRXDownloader main.py

# 纯GUI版本（隐藏控制台）
pyinstaller --onefile --windowed --name EdgeCRXDownloader main.py
```

详细打包说明请参考 [打包说明.md](打包说明.md)

## 项目结构

```
EdgeCRX/
├── main.py              # 程序
├── requirements.txt     # Python依赖
├── README.md           # 项目说明
```

## 技术栈

- **GUI框架**：CustomTkinter
- **HTTP请求**：requests
- **打包工具**：PyInstaller
- **Python版本**：3.8+

## 注意事项

1. 下载的crx文件以扩展ID命名，格式为 `{ID}.crx`
2. GUI模式下可以选择保存位置，会话内记住选择
3. CLI模式下文件保存到当前工作目录
4. 批量下载采用单线程逐个处理，失败不影响后续下载
5. 所有错误即时输出，不创建日志文件

## 贡献

欢迎提交Issue和Pull Request！
