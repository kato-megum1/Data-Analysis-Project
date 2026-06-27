"""Application service layer shared by Flask and future serverless adapters."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from agents.config_copilot import ConfigCopilot
from agents.metric_system_agent import MetricSystemAgent
from pipeline.report import answer_question
from pipeline.runner import run_analysis


SESSION_TTL_SECONDS = 24 * 60 * 60


@dataclass
class UploadedFile:
    filename: str
    source_path: Optional[str] = None
    file_obj: Any = None


class AnalysisService:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.sessions_dir = os.path.join(root_dir, "output", "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

    # ------------------------------------------------------------ Public API

    def create_profile(self, api_key: str, uploaded: UploadedFile,
                       background: str = "", field_doc: UploadedFile | None = None,
                       prompts: Dict[str, str] | None = None) -> Dict[str, Any]:
        api_key = resolve_api_key(api_key)
        profile_session_id = short_id("profile")
        session_dir = self._session_dir(profile_session_id)
        os.makedirs(session_dir, exist_ok=True)

        data_path = self._save_upload(uploaded, session_dir)
        field_doc_path = self._save_upload(field_doc, session_dir, optional=True) if field_doc else ""
        df = read_data_file(data_path)
        field_doc_content = load_field_doc(field_doc_path)
        llm = build_llm(api_key, prompts)

        draft = MetricSystemAgent(llm=llm).draft(df, field_doc_content, background)
        config = draft["recommended_config"]
        config["file_path"] = data_path
        config["file_name"] = os.path.basename(data_path)
        config["background"] = background

        profile_state = {
            "type": "profile",
            "profile_session_id": profile_session_id,
            "created_at": time.time(),
            "data_path": data_path,
            "field_doc_path": field_doc_path,
            "background": background,
            "metric_system": draft["metric_system"],
            "current_config": strip_secrets(config),
            "patch_history": [],
            "chat_history": [],
        }
        self._write_json(profile_session_id, "profile.json", profile_state)
        return {
            "success": True,
            "profile_session_id": profile_session_id,
            "metric_system": draft["metric_system"],
            "recommended_config": strip_secrets(config),
            "editable_config": strip_secrets(config),
            "warnings": draft.get("warnings", []),
            "data_preview": preview_df(df),
        }

    def config_chat(self, api_key: str, profile_session_id: str,
                    message: str, current_config: Dict[str, Any] | None = None,
                    prompts: Dict[str, str] | None = None,
                    undo: bool = False) -> Dict[str, Any]:
        api_key = resolve_api_key(api_key)
        profile = self._read_json(profile_session_id, "profile.json")
        if undo:
            return self._undo_patch(profile_session_id, profile)

        config = current_config or profile["current_config"]
        llm = build_llm(api_key, prompts)
        result = ConfigCopilot(llm=llm).propose_patch(message, config, profile.get("metric_system", {}))
        profile["patch_history"].append({
            "message": message,
            "before": config,
            "patch": result["patch"],
            "after": result["updated_config"],
            "warnings": result["warnings"],
        })
        profile["chat_history"].append({"role": "user", "content": message})
        profile["chat_history"].append({"role": "assistant", "content": result["reply"]})
        profile["current_config"] = strip_secrets(result["updated_config"])
        self._write_json(profile_session_id, "profile.json", profile)
        return {"success": True, **result}

    def analyze(self, api_key: str, config: Dict[str, Any],
                uploaded: UploadedFile | None = None,
                profile_session_id: str | None = None,
                prompts: Dict[str, str] | None = None) -> Dict[str, Any]:
        api_key = resolve_api_key(api_key or config.get("api_key", ""))
        session_id = short_id("analysis")
        session_dir = self._session_dir(session_id)
        os.makedirs(session_dir, exist_ok=True)

        config = {**config, "api_key": api_key or config.get("api_key", "")}
        if profile_session_id:
            profile = self._read_json(profile_session_id, "profile.json")
            data_path = profile["data_path"]
        elif uploaded:
            data_path = self._save_upload(uploaded, session_dir)
        else:
            data_path = config.get("file_path", "")
        if not data_path or not os.path.exists(data_path):
            raise FileNotFoundError("找不到分析数据文件")

        if not data_path.startswith(session_dir):
            copied = os.path.join(session_dir, os.path.basename(data_path))
            if os.path.abspath(data_path) != os.path.abspath(copied):
                shutil.copy2(data_path, copied)
            data_path = copied

        config["file_path"] = data_path
        config["file_name"] = config.get("file_name") or os.path.basename(data_path)
        llm = build_llm(config["api_key"], prompts)
        result = run_analysis(config, session_dir, session_id=session_id, llm=llm)

        state = {
            "type": "analysis",
            "session_id": session_id,
            "created_at": time.time(),
            "config": strip_secrets(config),
            "report_path": result["report_path"],
            "context_path": result["context_path"],
            "summary": result["summary"],
            "chat_history": [],
        }
        self._write_json(session_id, "session.json", state)
        return {
            "success": True,
            "session_id": session_id,
            "message": "分析完成",
            "summary": result["summary"],
            "report_path": result["report_path"],
            "context_path": result["context_path"],
        }

    def chat(self, session_id: str, question: str) -> Dict[str, Any]:
        session = self._read_json(session_id, "session.json")
        with open(session["context_path"], "r", encoding="utf-8") as f:
            context = json.load(f)
        answer = answer_question(context, question)
        session.setdefault("chat_history", []).append({"role": "user", "content": question})
        session["chat_history"].append({"role": "assistant", "content": answer})
        self._write_json(session_id, "session.json", session)
        return {"success": True, "answer": answer, "session_id": session_id}

    def report_path(self, session_id: str) -> str:
        return self._read_json(session_id, "session.json")["report_path"]

    def context_path(self, session_id: str) -> str:
        return self._read_json(session_id, "session.json")["context_path"]

    def list_sessions(self) -> Dict[str, Any]:
        sessions = []
        if not os.path.exists(self.sessions_dir):
            return {"sessions": []}
        for sid in os.listdir(self.sessions_dir):
            path = os.path.join(self.sessions_dir, sid, "session.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    item = json.load(f)
                sessions.append({
                    "session_id": sid,
                    "created_at": item.get("created_at"),
                    "file_name": item.get("config", {}).get("file_name", ""),
                    "summary": item.get("summary", {}),
                })
        return {"sessions": sessions}

    # ------------------------------------------------------------ Internals

    def _undo_patch(self, profile_session_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        history = profile.get("patch_history", [])
        if not history:
            return {"success": True, "reply": "没有可撤销的配置修改。", "patch": [], "updated_config": profile["current_config"], "warnings": []}
        last = history.pop()
        profile["current_config"] = last["before"]
        self._write_json(profile_session_id, "profile.json", profile)
        return {"success": True, "reply": "已撤销上一轮配置修改。", "patch": [], "updated_config": profile["current_config"], "warnings": []}

    def _session_dir(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, session_id)

    def _write_json(self, session_id: str, name: str, payload: Dict[str, Any]) -> None:
        session_dir = self._session_dir(session_id)
        os.makedirs(session_dir, exist_ok=True)
        with open(os.path.join(session_dir, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _read_json(self, session_id: str, name: str) -> Dict[str, Any]:
        path = os.path.join(self._session_dir(session_id), name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"无效 session: {session_id}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_upload(self, uploaded: UploadedFile | None, session_dir: str,
                     optional: bool = False) -> str:
        if uploaded is None:
            if optional:
                return ""
            raise ValueError("请上传数据文件")
        filename = secure_filename(uploaded.filename)
        if not filename:
            if optional:
                return ""
            raise ValueError("上传文件名无效")
        target = os.path.join(session_dir, filename)
        if uploaded.source_path:
            shutil.copy2(uploaded.source_path, target)
        elif uploaded.file_obj is not None:
            uploaded.file_obj.save(target)
        else:
            raise ValueError("上传文件为空")
        return target


def require_api_key(value: str) -> None:
    if not (value or "").strip():
        raise ValueError("未配置 DeepSeek API Key")


def resolve_api_key(value: str) -> str:
    resolved = (value or "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    require_api_key(resolved)
    return resolved


def short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def secure_filename(name: str) -> str:
    base = os.path.basename(name or "").replace("\\", "_").replace("/", "_")
    return base or "upload.xlsx"


def read_data_file(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path)
    return pd.read_excel(path)


def load_field_doc(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(path).to_string(index=False)
        if ext == ".csv":
            return pd.read_csv(path).to_string(index=False)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"(字段说明读取失败: {e})"


def build_llm(api_key: str, prompts: Dict[str, str] | None = None):
    try:
        from utils.llm_client import LLMClient
        return LLMClient(api_key, prompts=prompts or {})
    except Exception:
        return None


def preview_df(df: pd.DataFrame) -> Dict[str, Any]:
    sample = df.head(20).where(pd.notna(df), None)
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "column_names": [str(c) for c in df.columns],
        "sample_rows": [
            {str(k): json_scalar(v) for k, v in row.items()}
            for row in sample.to_dict("records")
        ],
    }


def json_scalar(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def strip_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(config or {})
    clean.pop("api_key", None)
    return clean
