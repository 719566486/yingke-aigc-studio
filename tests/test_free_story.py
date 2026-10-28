import pytest
from app import providers,store,story
from app.composition import caption_cues


def build(script,roles=None):
    return providers.make_template("三位朋友在门口接力递伞","cinema","9:16","dialogue",roles or [],story_script=script)


def test_three_characters_can_speak_in_any_order_with_actions():
    script="动作：小雨递出伞。\n小雨：拿着。\n阿南：谢谢。\n小雨（笑着）：别客气。\n小周：走吧。"
    plan=build(script)
    assert len(plan["characters"])==3 and len(plan["shots"])==1
    assert plan["shots"][0]["script"]==script
    checked=providers.validate_plan(plan)
    assert [t["speaker_name"] for t in checked["shots"][0]["turns"]]==["小雨","阿南","小雨","小周"]
    assert checked["timing"]["ready"]
    body=providers.request_body({**plan,**checked},store.DEFAULTS)
    assert body["sound"]=="on" and body["prompt"]
    assert "multi_prompt" not in body
    assert body["prompt"].index("拿着。")<body["prompt"].index("谢谢。")<body["prompt"].index("别客气。")


def test_one_person_can_monologue_and_action_only_can_have_no_dialogue():
    plan=build("小雨：钥匙在这儿。\n动作：小雨举起钥匙。")
    assert len(plan["characters"])==1
    assert providers.validate_plan(plan)["timing"]["ready"]
    pure=build("动作：机器人打开盒子，发现一朵花。")
    assert pure["characters"]==[] and pure["shots"][0]["turns"]==[]
    assert providers.validate_plan(pure)["timing"]["ready"]
    assert providers.request_body(pure,store.DEFAULTS)["sound"]=="off"


def test_user_controls_variable_scene_lengths():
    plan=build("0-3秒\n动作：门铃响起。\n3-11秒\n小雨：快进来。\n阿南：来了。\n11-15秒\n动作：两人进门，门合上。")
    checked=providers.validate_plan(plan)
    assert [s["duration"] for s in checked["shots"]]==[3,8,4]
    body=providers.request_body({**plan,**checked},store.DEFAULTS)
    assert [s["duration"] for s in body["multi_prompt"]]==["3","8","4"]
    assert sum(s["duration"] for s in checked["shots"])==15


def test_overloaded_story_is_preserved_but_paid_submission_is_blocked():
    text="小雨："+("这是一段必须完整保留的很长很长的台词。"*8)
    plan=build(text)
    assert plan["shots"][0]["script"]==text and not plan["timing"]["ready"]
    checked=providers.validate_plan(plan,strict=False)
    assert not checked["timing"]["ready"]
    with pytest.raises(providers.ProviderError,match="预计至少需要"):
        providers.validate_plan(plan)


def test_duration_edits_and_missing_roles_are_not_silently_fixed():
    plan=build("小雨：等我。")
    plan["shots"][0]["duration"]=14
    with pytest.raises(providers.ProviderError,match="总时长"):
        providers.validate_plan(plan)
    plan["shots"][0]["duration"]=15
    plan["shots"][0]["script"]="不存在的角色：等我。"
    with pytest.raises(providers.ProviderError,match="未找到角色"):
        providers.validate_plan(plan)


def test_multiple_turn_captions_keep_order_and_fit_scene():
    plan=build("小雨：拿着。\n阿南：谢谢。\n小雨：不客气。")
    shot=providers.validate_plan(plan)["shots"][0]
    cues=caption_cues(shot,"dialogue")
    assert len(cues)==3 and cues[0][2]=="小雨：拿着。"
    assert all(0<=a<b<=15 for a,b,_ in cues)
    assert all(cues[i][1]<=cues[i+1][0] for i in range(2))


def test_timed_script_cannot_drop_an_unassigned_preamble():
    with pytest.raises(providers.ProviderError,match="避免遗漏"):
        build("动作：不能丢掉的关键开场\n0-15秒\n动作：关门。")
