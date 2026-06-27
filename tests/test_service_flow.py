"""Service-level profile -> config-chat -> analyze flow."""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.analysis_service import AnalysisService, UploadedFile  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_service_flow_generates_session_scoped_report():
    tmp = tempfile.mkdtemp(prefix="analysis_service_")
    try:
        service = AnalysisService(tmp)
        source = os.path.join(ROOT, "data", "test_retail.xlsx")
        profile = service.create_profile(
            api_key="sk-test",
            uploaded=UploadedFile(filename="test_retail.xlsx", source_path=source),
            background="零售经营分析",
        )
        assert profile["profile_session_id"]
        assert profile["metric_system"]["primary_metrics"]

        chat = service.config_chat(
            api_key="sk-test",
            profile_session_id=profile["profile_session_id"],
            message="把销售额设为核心指标",
            current_config=profile["editable_config"],
        )
        assert "销售额" in chat["updated_config"].get("primary_metrics", [])

        result = service.analyze(
            api_key="sk-test",
            config=chat["updated_config"],
            profile_session_id=profile["profile_session_id"],
        )
        assert os.path.exists(result["report_path"])
        assert os.path.exists(result["context_path"])
        answer = service.chat(result["session_id"], "有哪些异常？")
        assert answer["success"] and answer["answer"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_service_requires_api_key():
    tmp = tempfile.mkdtemp(prefix="analysis_service_")
    try:
        service = AnalysisService(tmp)
        source = os.path.join(ROOT, "data", "test_retail.xlsx")
        try:
            service.create_profile(api_key="", uploaded=UploadedFile(filename="test_retail.xlsx", source_path=source))
            raise AssertionError("expected missing API key")
        except ValueError as e:
            assert "API Key" in str(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(funcs)} passed")
    sys.exit(0 if passed == len(funcs) else 1)
