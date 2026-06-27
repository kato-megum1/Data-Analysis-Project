#!/usr/bin/env python3
"""
数据分析 Agent 集群 — 一键启动脚本
功能：检查 Python → 检查依赖 → 安装缺失 → 启动服务 → 自动打开浏览器
支持：macOS / Windows / Linux
用法：双击运行 或 命令行执行 python start.py
"""
import os
import sys
import subprocess
import time
import webbrowser
import platform

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)

PORT = 5050
URL = f"http://127.0.0.1:{PORT}"
REQUIREMENTS = os.path.join(PROJECT_ROOT, "requirements.txt")


def print_banner():
    print("=" * 56)
    print("   数据分析 Agent 集群 — 一键启动")
    print("   自动检查环境 → 安装依赖 → 启动服务 → 打开浏览器")
    print("=" * 56)
    print()


def check_python():
    """检查 Python 版本 >= 3.9"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(f"错误: 需要 Python >= 3.9，当前 {version.major}.{version.minor}.{version.micro}")
        print("请安装新版 Python: https://python.org/downloads")
        sys.exit(1)
    print(f"Python 版本: {version.major}.{version.minor}.{version.micro}  通过")


def get_pip_cmd():
    """获取可用的 pip 命令"""
    for cmd in ["pip3", "pip"]:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print("错误: 未找到 pip，请安装 pip:")
    print("  python -m ensurepip --upgrade")
    sys.exit(1)


def install_requirements(pip_cmd):
    """安装 requirements.txt 中的依赖"""
    if not os.path.exists(REQUIREMENTS):
        print(f"警告: 未找到 {REQUIREMENTS}，跳过依赖安装")
        return

    print("正在检查依赖...")
    try:
        # 先尝试安装，如果已安装会快速跳过
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS],
            capture_output=False,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pip install 返回码 {result.returncode}")
    except Exception as e:
        print(f"依赖安装失败: {e}")
        print("请手动运行: pip install -r requirements.txt")
        sys.exit(1)

    print("依赖检查完成")
    print()


def open_browser_delayed():
    """延迟几秒后打开浏览器"""
    time.sleep(2)
    print(f"正在打开浏览器: {URL}")
    webbrowser.open(URL)


def run_server():
    """启动 Flask 服务器"""
    server_path = os.path.join(PROJECT_ROOT, "server.py")
    if not os.path.exists(server_path):
        print(f"错误: 未找到服务器文件 {server_path}")
        sys.exit(1)

    print(f"正在启动服务... (端口 {PORT})")
    print(f"浏览器将在 2 秒后自动打开: {URL}")
    print()
    print("-" * 56)
    print("  服务已启动，请勿关闭此窗口")
    print("  按 Ctrl+C 停止服务")
    print("-" * 56)
    print()

    # 在后台线程打开浏览器
    import threading
    browser_thread = threading.Thread(target=open_browser_delayed, daemon=True)
    browser_thread.start()

    try:
        subprocess.run([sys.executable, server_path], cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        print("\n服务已停止")
        sys.exit(0)


def main():
    print_banner()
    check_python()
    pip_cmd = get_pip_cmd()
    install_requirements(pip_cmd)
    run_server()


if __name__ == "__main__":
    main()
