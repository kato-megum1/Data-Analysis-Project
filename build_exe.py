#!/usr/bin/env python3
"""
PyInstaller 打包脚本 — 数据分析 Agent 集群
生成可执行文件，无需 Python 环境即可运行
用法: python build_exe.py
输出: dist/数据分析Agent集群/ (包含可执行文件 + 资源)
"""
import os
import sys
import subprocess
import shutil

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)

APP_NAME = "数据分析Agent集群"


def clean():
    """清理之前的构建产物"""
    for d in ["build", "dist"]:
        if os.path.exists(d):
            print(f"清理 {d}/ ...")
            shutil.rmtree(d)
    for f in ["*.spec"]:
        import glob
        for p in glob.glob(f):
            os.remove(p)


def build():
    """运行 PyInstaller 打包"""
    print(f"正在打包: {APP_NAME}")
    print("-" * 50)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",           # 单目录模式（启动更快、文件结构清晰）
        "--noconsole",        # 不显示命令行窗口
        "--clean",
        # 资源文件
        "--add-data", f"static{os.pathsep}static",
        "--add-data", f"config_page.html{os.pathsep}.",
        "--add-data", f"README.md{os.pathsep}.",
        # Python 包（PyInstaller 应该自动检测，但显式声明更保险）
        "--hidden-import", "pipeline.schema",
        "--hidden-import", "pipeline.etl",
        "--hidden-import", "pipeline.metric",
        "--hidden-import", "pipeline.trend",
        "--hidden-import", "pipeline.anomaly",
        "--hidden-import", "pipeline.attribution",
        "--hidden-import", "pipeline.report",
        "--hidden-import", "pipeline.runner",
        "--hidden-import", "agents.config_advisor",
        "--hidden-import", "agents.metric_system_agent",
        "--hidden-import", "agents.config_copilot",
        "--hidden-import", "agents.critic_agent",
        "--hidden-import", "agents.formula_discovery",
        "--hidden-import", "services.analysis_service",
        "--hidden-import", "utils.llm_client",
        "--hidden-import", "pandas",
        "--hidden-import", "flask",
        "--hidden-import", "openpyxl",
        "--hidden-import", "scipy",
        "--hidden-import", "langchain",
        "--hidden-import", "langchain_deepseek",
        # 入口文件
        "server.py"
    ]

    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("打包失败！")
        sys.exit(1)

    print()
    print("-" * 50)
    print(f"打包成功！输出目录: dist/{APP_NAME}/")
    print()

    # 复制启动器到 dist
    dist_dir = os.path.join(PROJECT_ROOT, "dist", APP_NAME)

    # 创建 data/ output/ 目录（运行时数据存放）
    os.makedirs(os.path.join(dist_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(dist_dir, "output"), exist_ok=True)

    # 复制启动脚本
    if sys.platform == "darwin":
        launcher = os.path.join(dist_dir, f"启动{APP_NAME}.command")
        with open(launcher, "w") as f:
            f.write(f'#!/bin/bash\ncd "$(dirname "$0")"\n./{APP_NAME}\n')
        os.chmod(launcher, 0o755)
        print(f"  macOS 启动器: {launcher}")
    elif sys.platform == "win32":
        launcher = os.path.join(dist_dir, f"启动{APP_NAME}.bat")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(f'@echo off\ncd /d "%~dp0"\nstart "" "{APP_NAME}.exe"\n')
        print(f"  Windows 启动器: {launcher}")

    print()
    print("分发方式:")
    print(f"  1. 将 dist/{APP_NAME}/ 文件夹压缩发送")
    print(f"  2. 对方解压后双击启动器即可运行")
    print(f"  3. 服务启动后自动打开浏览器访问 http://127.0.0.1:5050")
    print()
    print(f"  ⚠️ 注意: 分析功能需要 DeepSeek API Key")


def main():
    clean()
    build()


if __name__ == "__main__":
    main()
