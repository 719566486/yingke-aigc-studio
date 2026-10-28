import uuid
import pytest
from fastapi.testclient import TestClient
from app import providers, store, main, share


def test_dialogue_prompt_preserves_speakers_and_enables_native_audio():
    plan=providers.make_template("A和B在街角久别重逢","cinema","9:16","dialogue")
    plan.update(bgm_mode="none")
    plan={**plan,**providers.validate_plan(plan)}
    body=providers.request_body(plan,store.DEFAULTS)
    assert body["sound"]=="on"
    assert "角色A用普通话" in body["multi_prompt"][0]["prompt"]
    assert "好久不见，你瘦了。" in body["multi_prompt"][0]["prompt"]
    assert "角色B用普通话" in body["multi_prompt"][1]["prompt"]
    assert "想你想的。" in body["multi_prompt"][1]["prompt"]
    assert "不要背景音乐" in body["multi_prompt"][0]["prompt"]


def test_optional_narration_and_ai_music_protocol():
    plan=providers.make_template("一叶小舟驶入山谷","ink","9:16","silent")
    validated=providers.validate_plan(plan)
    assert all(not s["narration"] for s in validated["shots"])
    assert providers.request_body(plan,store.DEFAULTS)["sound"]=="off"
    plan.update(bgm_mode="ai",bgm_prompt="轻柔钢琴")
    body=providers.request_body(plan,store.DEFAULTS)
    assert body["sound"]=="on" and "无人声" in body["multi_prompt"][0]["prompt"]
    assert "轻柔钢琴" in body["multi_prompt"][0]["prompt"]
    with pytest.raises(providers.ProviderError):
        providers.request_body(plan,{**store.DEFAULTS,"kling_model":"unsupported"})


def test_uploaded_music_never_requests_native_music_for_montage():
    plan=providers.make_template("晨光中的城市","cinema","9:16")
    plan["bgm_mode"]="upload"
    assert providers.request_body(plan,store.DEFAULTS)["sound"]=="off"


def test_dialogue_requires_a_known_speaker():
    plan=providers.make_template("A与B见面","cinema","9:16","dialogue")
    plan["shots"][0]["speaker"]=""
    with pytest.raises(providers.ProviderError):
        providers.validate_plan(plan)
