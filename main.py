#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge CRX Downloader
一个用于从Microsoft Edge扩展商店下载crx文件的工具
支持GUI模式（批量下载）和CLI模式（单个下载）
"""

import sys
import os
import re
import customtkinter as ctk
from tkinter import filedialog
import requests
from typing import Optional, Callable

# ==================== 常量定义 ====================
EDGE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.140 Safari/537.36 Edge/18.17763"
DOWNLOAD_URL_TEMPLATE = "https://edge.microsoft.com/extensionwebstorebase/v1/crx?response=redirect&prod=chromiumcrx&prodchannel=&x=id%3D{ID}%26installsource%3Dondemand%26uc"

# ==================== ID提取模块 ====================

def extract_extension_id(input_text: str) -> str:
    """
    从URL或纯ID中提取扩展ID
    
    参数:
        input_text: 用户输入的URL或ID
        
    返回:
        提取的扩展ID
        
    异常:
        ValueError: 当输入格式无效时
    """
    input_text = input_text.strip()
    
    if not input_text:
        raise ValueError("输入不能为空")
    
    # 检查是否为Edge扩展商店URL
    if "microsoftedge.microsoft.com" in input_text:
        # 使用正则表达式提取/detail/后的第二个路径段（扩展ID）
        pattern = r'/detail/[^/]+/([a-z]+)'
        match = re.search(pattern, input_text)
        if match:
            return match.group(1)
        else:
            raise ValueError("无法从URL中提取扩展ID")
    
    # 如果不是URL，验证是否为有效的扩展ID格式
    # Edge扩展ID通常是32个小写字母
    if re.match(r'^[a-z]{32}$', input_text):
        return input_text
    else:
        raise ValueError("无效的扩展ID格式（应为32个小写字母）")

# ==================== 下载引擎模块 ====================

class DownloadEngine:
    """CRX文件下载引擎"""
    
    def __init__(self):
        self.user_agent = EDGE_USER_AGENT
        self.url_template = DOWNLOAD_URL_TEMPLATE
    
    def download_crx(self, extension_id: str, save_path: str, 
                     progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """
        下载CRX文件
        
        参数:
            extension_id: 扩展ID
            save_path: 保存路径（包含文件名）
            progress_callback: 进度回调函数 callback(downloaded_bytes, total_bytes)
            
        返回:
            True表示成功，False表示失败
        """
        try:
            # 构建下载URL
            download_url = self.url_template.replace("{ID}", extension_id)
            
            # 创建请求头
            headers = {
                'User-Agent': self.user_agent
            }
            
            # 发送GET请求，启用流式传输
            response = requests.get(download_url, headers=headers, stream=True, timeout=30)
            
            # 检查HTTP状态码
            if response.status_code == 404:
                print(f"错误: 扩展不存在或ID无效 ({extension_id})", file=sys.stderr)
                return False
            elif response.status_code != 200:
                print(f"错误: 下载失败 HTTP {response.status_code}", file=sys.stderr)
                return False
            
            # 获取文件总大小
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            # 分块下载并写入文件
            chunk_size = 8192
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 调用进度回调
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded_size, total_size)
            
            return True
            
        except requests.Timeout:
            print(f"错误: 网络超时", file=sys.stderr)
            return False
        except requests.ConnectionError:
            print(f"错误: 网络连接失败，请检查网络", file=sys.stderr)
            return False
        except IOError as e:
            print(f"错误: 文件保存失败 - {str(e)}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"错误: {str(e)}", file=sys.stderr)
            return False

# ==================== GUI模块 ====================

class GUIApp:
    """CustomTkinter图形界面应用"""
    
    def __init__(self):
        # 设置主题
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        
        # 创建主窗口
        self.window = ctk.CTk()
        self.window.title("Edge CRX 下载器")
        self.window.geometry("600x550")
        
        # 初始化属性
        self.save_directory = os.getcwd()
        self.download_engine = DownloadEngine()
        self.is_downloading = False
        
        # 设置UI
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI组件"""
        # 设置边距
        padding = 15
        
        # 标题标签
        title_label = ctk.CTkLabel(
            self.window, 
            text="输入扩展URL或ID（每行一个）：",
            font=("Arial", 12)
        )
        title_label.pack(pady=(padding, 5), padx=padding, anchor="w")
        
        # 多行文本输入框
        self.input_textbox = ctk.CTkTextbox(
            self.window,
            height=150,
            font=("Arial", 11)
        )
        self.input_textbox.pack(pady=5, padx=padding, fill="both")
        
        # 保存位置区域
        save_frame = ctk.CTkFrame(self.window)
        save_frame.pack(pady=10, padx=padding, fill="x")
        
        save_label = ctk.CTkLabel(
            save_frame,
            text="保存位置：",
            font=("Arial", 11)
        )
        save_label.pack(side="left", padx=(5, 5))
        
        self.save_path_label = ctk.CTkLabel(
            save_frame,
            text=self.save_directory,
            font=("Arial", 10),
            text_color="gray"
        )
        self.save_path_label.pack(side="left", padx=5, fill="x", expand=True)
        
        self.select_dir_button = ctk.CTkButton(
            save_frame,
            text="选择目录",
            width=100,
            command=self.select_directory
        )
        self.select_dir_button.pack(side="right", padx=5)
        
        # 下载按钮
        self.download_button = ctk.CTkButton(
            self.window,
            text="开始下载",
            font=("Arial", 12, "bold"),
            height=35,
            command=self.on_download_click
        )
        self.download_button.pack(pady=10, padx=padding, fill="x")
        
        # 进度条
        progress_label = ctk.CTkLabel(
            self.window,
            text="下载进度：",
            font=("Arial", 11)
        )
        progress_label.pack(pady=(10, 5), padx=padding, anchor="w")
        
        self.progress_bar = ctk.CTkProgressBar(self.window)
        self.progress_bar.pack(pady=5, padx=padding, fill="x")
        self.progress_bar.set(0)
        
        # 状态信息文本框
        status_label = ctk.CTkLabel(
            self.window,
            text="状态信息：",
            font=("Arial", 11)
        )
        status_label.pack(pady=(10, 5), padx=padding, anchor="w")
        
        self.status_textbox = ctk.CTkTextbox(
            self.window,
            height=120,
            font=("Arial", 10)
        )
        self.status_textbox.pack(pady=5, padx=padding, fill="both", expand=True)
        self.status_textbox.configure(state="disabled")
    
    def select_directory(self):
        """选择保存目录"""
        directory = filedialog.askdirectory(initialdir=self.save_directory)
        if directory:
            self.save_directory = directory
            self.save_path_label.configure(text=directory)
            self.add_status_message(f"保存位置已更改为: {directory}")
    
    def add_status_message(self, message: str):
        """添加状态消息到状态文本框"""
        self.status_textbox.configure(state="normal")
        self.status_textbox.insert("end", f"{message}\n")
        self.status_textbox.see("end")
        self.status_textbox.configure(state="disabled")
        self.window.update()
    
    def on_download_click(self):
        """处理下载按钮点击"""
        if self.is_downloading:
            return
        
        # 获取输入文本
        input_text = self.input_textbox.get("1.0", "end").strip()
        
        if not input_text:
            self.add_status_message("错误: 请输入至少一个扩展URL或ID")
            return
        
        # 按行分割输入
        lines = [line.strip() for line in input_text.split('\n') if line.strip()]
        
        # 提取每行的ID
        id_list = []
        for i, line in enumerate(lines, 1):
            try:
                extension_id = extract_extension_id(line)
                id_list.append(extension_id)
            except ValueError as e:
                self.add_status_message(f"第{i}行错误: {str(e)}")
        
        if not id_list:
            self.add_status_message("错误: 没有有效的扩展ID")
            return
        
        # 开始下载
        self.add_status_message(f"\n开始下载 {len(id_list)} 个扩展...")
        self.process_downloads(id_list)
    
    def process_downloads(self, id_list: list):
        """处理批量下载队列"""
        self.is_downloading = True
        self.download_button.configure(state="disabled")
        
        success_count = 0
        fail_count = 0
        
        for i, extension_id in enumerate(id_list, 1):
            self.add_status_message(f"\n[{i}/{len(id_list)}] 正在下载: {extension_id}")
            self.progress_bar.set(0)
            
            # 构建保存路径
            save_path = os.path.join(self.save_directory, f"{extension_id}.crx")
            
            # 定义进度回调
            def progress_callback(downloaded, total):
                if total > 0:
                    progress = downloaded / total
                    self.progress_bar.set(progress)
                    self.window.update()
            
            # 执行下载
            success = self.download_engine.download_crx(
                extension_id, 
                save_path, 
                progress_callback
            )
            
            if success:
                self.add_status_message(f"✓ 下载成功: {save_path}")
                self.progress_bar.set(1.0)
                success_count += 1
            else:
                self.add_status_message(f"✗ 下载失败: {extension_id}")
                fail_count += 1
        
        # 显示完成消息
        self.add_status_message(f"\n下载完成! 成功: {success_count}, 失败: {fail_count}")
        
        self.is_downloading = False
        self.download_button.configure(state="normal")
    
    def run(self):
        """运行GUI应用"""
        self.window.mainloop()

# ==================== CLI模块 ====================

def run_cli_mode(args: list) -> int:
    """
    运行CLI模式
    
    参数:
        args: 命令行参数列表
        
    返回:
        退出码：0表示成功，1表示失败
    """
    if not args:
        print("错误: 请提供扩展URL或ID", file=sys.stderr)
        print("用法: main.py --[URL或ID] 或 main.py [URL或ID]")
        return 1
    
    # 获取输入（移除可能的--前缀）
    input_text = args[0].lstrip('-')
    
    try:
        # 提取扩展ID
        extension_id = extract_extension_id(input_text)
        print(f"扩展ID: {extension_id}")
        
        # 使用当前工作目录作为保存位置
        save_path = os.path.join(os.getcwd(), f"{extension_id}.crx")
        print(f"保存路径: {save_path}")
        
        # 创建下载引擎
        engine = DownloadEngine()
        
        # 定义终端进度回调
        last_progress = [0]  # 使用列表以便在闭包中修改
        
        def progress_callback(downloaded, total):
            if total > 0:
                progress = int((downloaded / total) * 100)
                # 只在进度变化时更新（避免过多输出）
                if progress != last_progress[0]:
                    last_progress[0] = progress
                    downloaded_mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    bar_length = 20
                    filled = int(bar_length * downloaded / total)
                    bar = '█' * filled + '░' * (bar_length - filled)
                    print(f"\r进度: [{bar}] {progress}% ({downloaded_mb:.2f}MB / {total_mb:.2f}MB)", end='', flush=True)
        
        print(f"\n下载中: {extension_id}")
        
        # 执行下载
        success = engine.download_crx(extension_id, save_path, progress_callback)
        
        print()  # 换行
        
        if success:
            print(f"✓ 下载成功: {save_path}")
            return 0
        else:
            print(f"✗ 下载失败", file=sys.stderr)
            return 1
            
    except ValueError as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        return 1

# ==================== 主入口点 ====================
if __name__ == "__main__":
    # 检查命令行参数决定运行模式
    if len(sys.argv) > 1:
        # CLI模式
        exit_code = run_cli_mode(sys.argv[1:])
        sys.exit(exit_code)
    else:
        # GUI模式
        app = GUIApp()
        app.run()
