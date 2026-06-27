"""Netlify Functions adapter for the one-table analysis API."""

from __future__ import annotations

import base64
import cgi
import io
import json
import os
import sys
import tempfile
from urllib.parse import parse_qs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.analysis_service import AnalysisService, UploadedFile  # noqa: E402

SERVICE = AnalysisService(os.environ.get("ANALYSIS_APP_ROOT", tempfile.gettempdir()))


def handler(event, context):
    try:
        method = event.get("httpMethod", "GET").upper()
        path = event.get("path", "/")
        if method == "POST" and path.endswith("/profile"):
            fields, files = parse_body(event)
            result = SERVICE.create_profile(
                api_key=fields.get("api_key", ""),
                uploaded=files.get("file"),
                background=fields.get("background", ""),
                field_doc=files.get("field_doc"),
                prompts=json_loads(fields.get("prompts", "{}")),
            )
            return json_response(result)
        if method == "POST" and path.endswith("/config-chat"):
            data = json_body(event)
            return json_response(SERVICE.config_chat(
                api_key=data.get("api_key", ""),
                profile_session_id=data.get("profile_session_id", ""),
                message=data.get("message", ""),
                current_config=data.get("current_config"),
                prompts=data.get("prompts") or {},
                undo=bool(data.get("undo")),
            ))
        if method == "POST" and path.endswith("/analyze"):
            fields, files = parse_body(event)
            result = SERVICE.analyze(
                api_key=fields.get("api_key", ""),
                config=json_loads(fields.get("config", "{}")),
                uploaded=files.get("file"),
                profile_session_id=fields.get("profile_session_id") or None,
                prompts=json_loads(fields.get("prompts", "{}")),
            )
            return json_response(result)
        if method == "POST" and path.endswith("/chat"):
            data = json_body(event)
            return json_response(SERVICE.chat(data.get("session_id", ""), data.get("question", "")))
        if method == "GET" and "/report/" in path:
            session_id = path.rsplit("/", 1)[-1]
            with open(SERVICE.report_path(session_id), "r", encoding="utf-8") as f:
                return text_response(f.read(), "text/html; charset=utf-8")
        if method == "GET" and "/context/" in path:
            session_id = path.rsplit("/", 1)[-1]
            with open(SERVICE.context_path(session_id), "r", encoding="utf-8") as f:
                return text_response(f.read(), "application/json; charset=utf-8")
        return json_response({"success": False, "error": f"Unsupported route: {method} {path}"}, status=404)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)


def parse_body(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type", "")
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")

    if "multipart/form-data" in content_type:
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(len(raw)),
        }
        form = cgi.FieldStorage(fp=io.BytesIO(raw), environ=env, keep_blank_values=True)
        fields = {}
        files = {}
        for key in form.keys():
            item = form[key]
            if isinstance(item, list):
                item = item[0]
            if item.filename:
                files[key] = field_storage_to_upload(item)
            else:
                fields[key] = item.value
        return fields, files

    if "application/json" in content_type:
        return json.loads(raw.decode("utf-8") or "{}"), {}

    parsed = parse_qs(raw.decode("utf-8"))
    return {k: v[0] if v else "" for k, v in parsed.items()}, {}


def field_storage_to_upload(item) -> UploadedFile:
    suffix = os.path.splitext(item.filename or "upload.bin")[1]
    fd, path = tempfile.mkstemp(prefix="netlify_upload_", suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(item.file.read())
    return UploadedFile(filename=item.filename, source_path=path)


def json_body(event):
    body = event.get("body") or "{}"
    raw = base64.b64decode(body).decode("utf-8") if event.get("isBase64Encoded") else body
    return json.loads(raw or "{}")


def json_loads(text):
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


def json_response(payload, status=200):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, ensure_ascii=False),
    }


def text_response(body, content_type, status=200):
    return {
        "statusCode": status,
        "headers": {"content-type": content_type},
        "body": body,
    }
