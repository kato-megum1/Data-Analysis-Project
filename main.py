#!/usr/bin/env python3
"""Command-line entrypoint for the new state+facts pipeline."""

import json
import os
import sys

from pipeline.runner import run_analysis


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _resolve_data_path(config: dict) -> str:
    data_path = config.get("file_path", "")
    if data_path and os.path.exists(data_path):
        return data_path

    file_name = config.get("file_name", "")
    if file_name:
        candidate = os.path.join(PROJECT_ROOT, "data", file_name)
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError(f"找不到数据文件: {file_name or data_path}")


def main(config_path: str) -> str:
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if not (config.get("api_key") or "").strip():
        raise ValueError("未配置 DeepSeek API Key")

    config["file_path"] = _resolve_data_path(config)
    config["file_name"] = config.get("file_name") or os.path.basename(config["file_path"])

    result = run_analysis(config, os.path.join(PROJECT_ROOT, "output"))
    print("分析完成")
    print(f"报告: {result['report_path']}")
    print(f"上下文: {result['context_path']}")
    if result["summary"].get("errors"):
        print("运行记录:")
        for err in result["summary"]["errors"]:
            print(f"- {err['step']}: {err['error']}")
    return result["report_path"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python main.py config.json")
        sys.exit(1)
    try:
        main(sys.argv[1])
    except Exception as e:
        print(f"运行失败: {e}")
        sys.exit(1)
