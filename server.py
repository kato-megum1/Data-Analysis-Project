"""Flask adapter for the one-table analysis application."""

import json
import os
import sys

from flask import Flask, jsonify, request, send_file, send_from_directory

from services.analysis_service import AnalysisService, UploadedFile

app = Flask(__name__)

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_ROOT = sys._MEIPASS
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

service = AnalysisService(PROJECT_ROOT)


@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response


@app.route("/")
def index():
    return send_from_directory(PROJECT_ROOT, "config_page.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory(os.path.join(PROJECT_ROOT, "static"), path)


@app.route("/info")
def info():
    return jsonify({
        "service": "单表经营分析 AI 应用",
        "version": "5.0",
        "architecture": "profile -> config-chat -> facts -> critic -> report",
        "endpoints": [
            "POST /profile",
            "POST /config-chat",
            "POST /analyze",
            "POST /chat",
            "GET /report/<session_id>",
            "GET /context/<session_id>",
        ],
    })


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/profile", methods=["POST"])
def profile():
    try:
        api_key = request.form.get("api_key", "")
        prompts = _json_form("prompts", {})
        uploaded = request.files.get("file")
        field_doc = request.files.get("field_doc")
        result = service.create_profile(
            api_key=api_key,
            uploaded=_uploaded(uploaded),
            background=request.form.get("background", ""),
            field_doc=_uploaded(field_doc) if field_doc and field_doc.filename else None,
            prompts=prompts,
        )
        return jsonify(result)
    except Exception as e:
        return _error(e)


@app.route("/config-chat", methods=["POST"])
def config_chat():
    try:
        data = request.get_json(force=True)
        result = service.config_chat(
            api_key=data.get("api_key", ""),
            profile_session_id=data.get("profile_session_id", ""),
            message=data.get("message", ""),
            current_config=data.get("current_config"),
            prompts=data.get("prompts") or {},
            undo=bool(data.get("undo")),
        )
        return jsonify(result)
    except Exception as e:
        return _error(e)


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        config = _json_form("config", {})
        profile_session_id = request.form.get("profile_session_id", "")
        api_key = request.form.get("api_key", "") or config.get("api_key", "")
        prompts = _json_form("prompts", config.get("prompts", {}))
        uploaded = request.files.get("file")
        result = service.analyze(
            api_key=api_key,
            config=config,
            uploaded=_uploaded(uploaded) if uploaded and uploaded.filename else None,
            profile_session_id=profile_session_id or None,
            prompts=prompts,
        )
        return jsonify(result)
    except Exception as e:
        return _error(e)


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(force=True)
        result = service.chat(data.get("session_id", ""), data.get("question", ""))
        return jsonify(result)
    except Exception as e:
        return _error(e)


@app.route("/report/<session_id>")
def get_report_by_session(session_id):
    try:
        path = service.report_path(session_id)
        if os.path.exists(path):
            return send_file(path)
        return jsonify({"error": "报告不存在"}), 404
    except Exception as e:
        return _error(e)


@app.route("/context/<session_id>")
def get_context_by_session(session_id):
    try:
        path = service.context_path(session_id)
        if os.path.exists(path):
            return send_file(path, mimetype="application/json")
        return jsonify({"error": "上下文不存在"}), 404
    except Exception as e:
        return _error(e)


@app.route("/sessions")
def list_sessions():
    return jsonify(service.list_sessions())


def _uploaded(file_storage) -> UploadedFile:
    if file_storage is None:
        return UploadedFile(filename="")
    return UploadedFile(filename=file_storage.filename, file_obj=file_storage)


def _json_form(name: str, default):
    raw = request.form.get(name, "")
    if not raw:
        return default
    return json.loads(raw)


def _error(e: Exception):
    import traceback
    return jsonify({"success": False, "error": str(e), "detail": traceback.format_exc()}), 500


if __name__ == "__main__":
    port = 5050
    print("=" * 50)
    print("  单表经营分析 AI 应用")
    print(f"  访问: http://127.0.0.1:{port}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
