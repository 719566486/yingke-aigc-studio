import io, json, sqlite3, uuid
from pathlib import Path
from unittest.mock import Mock
import httpx, pytest
from fastapi.testclient import TestClient
from PIL import Image
from app import store, providers, main, media

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    for name in ("DATA","JOBS","UPLOADS"):
        p=tmp_path/name.lower();p.mkdir();monkeypatch.setattr(store,name,p)
    monkeypatch.setattr(store,"DB",tmp_path/"test.sqlite3")
    monkeypatch.setattr(store,"CONFIG",tmp_path/"settings.json")
    monkeypatch.setattr(main,"TASKS",__import__("queue").Queue())
    monkeypatch.setattr(main,"process",lambda job_id: None)
    store.init_db()
    return tmp_path

def payload():
    plan=providers.make_template("一只小猫在云端图书馆读信","cinema","9:16")
    return {"plan":plan,"voice":"zf_001","reference_id":None,"paid_consent":False}

def test_idempotency_preserves_single_job(isolated):
    data=payload();one,new=store.create_job(data,"preview","a"*32,10)
    two,again=store.create_job(data,"preview","a"*32,10)
    assert new and not again and one["id"]==two["id"]
    assert len(store.list_jobs())==1

def test_idempotency_rejects_changed_request(isolated):
    data=payload();store.create_job(data,"preview","a"*32,10)
    data["plan"]["title"]="另一个故事"
    with pytest.raises(ValueError):store.create_job(data,"preview","a"*32,10)

def test_budget_reservation_includes_unknown(isolated):
    one,_=store.create_job(payload(),"kling","a"*32,1)
    store.update(one["id"],status="unknown",submission_started=1)
    with pytest.raises(ValueError,match="上限"):store.create_job(payload(),"kling","b"*32,1)

def test_recovery_never_resubmits_ambiguous_paid_job(isolated):
    one,_=store.create_job(payload(),"kling","a"*32,10)
    store.update(one["id"],status="running",submission_started=1)
    assert store.recover()==[]
    assert store.get_job(one["id"])["status"]=="unknown"

def test_recovery_keeps_provider_id(isolated):
    one,_=store.create_job(payload(),"kling","a"*32,10)
    store.update(one["id"],status="running",submission_started=1,provider_id="known-123")
    assert store.recover()==[one["id"]]
    assert store.get_job(one["id"])["provider_id"]=="known-123"

def test_windows_secret_round_trip(isolated):
    store.save_settings({"kling_access_key":"test-secret-not-real","kling_secret_key":"sample-not-real"})
    raw=store.CONFIG.read_text()
    assert "test-secret-not-real" not in raw
    assert store.settings()["kling_access_key"]=="test-secret-not-real"

def test_timeout_is_unknown_not_safe_retry(monkeypatch):
    client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
    client.post.side_effect=httpx.ReadTimeout("simulated")
    monkeypatch.setattr(providers.httpx,"Client",lambda **kw:client)
    cfg={**store.DEFAULTS,"kling_access_key":"fake","kling_secret_key":"fake"}
    with pytest.raises(providers.SubmissionUnknown):providers.submit_kling(payload()["plan"],cfg)
    assert client.post.call_count==1

def test_reject_invalid_plan_and_endpoint():
    with pytest.raises(providers.ProviderError):providers.validate_plan({"title":"x","shots":[]})
    for url in ("file:///etc","http://service.example/v1","https://user:pass@example.com","https://localhost/v1"):
        with pytest.raises(ValueError):providers.validate_base(url)

def test_api_protects_mutations_and_secrets(isolated):
    with TestClient(main.app) as client:
        token=client.get("/api/bootstrap").json()["token"]
        assert client.post("/api/plan",json={"brief":"小猫读信"}).status_code==403
        headers={"X-Studio-Token":token}
        result=client.post("/api/plan",headers=headers,json={"brief":"小猫读信"})
        assert result.status_code==200 and len(result.json()["shots"])==3
        assert client.post("/api/plan",headers={**headers,"Origin":"https://attacker.example"},json={"brief":"小猫读信"}).status_code==403
        put=client.put("/api/settings",headers=headers,json={"kling_access_key":"not-real","kling_secret_key":"not-real"})
        assert put.status_code==200
        result=client.get("/api/settings").json()["settings"]
        assert result["kling_access_key_configured"] is True
        assert "kling_access_key" not in result and "kling_secret_key" not in result

def test_upload_validation_and_local_storage(isolated):
    with TestClient(main.app) as client:
        token=client.get("/api/bootstrap").json()["token"];headers={"X-Studio-Token":token}
        assert client.post("/api/uploads",headers=headers,files={"image":("bad.png",b"not-an-image","image/png")}).status_code==400
        image=Image.new("RGB",(100,100),"red");buf=io.BytesIO();image.save(buf,format="PNG")
        result=client.post("/api/uploads",headers=headers,files={"image":("photo.png",buf.getvalue(),"image/png")})
        assert result.status_code==200
        assert client.get(result.json()["url"]).status_code==200

def test_paid_submit_requires_credentials(isolated):
    with TestClient(main.app) as client:
        token=client.get("/api/bootstrap").json()["token"]
        body={**payload(),"mode":"kling","idempotency":uuid.uuid4().hex}
        result=client.post("/api/jobs",headers={"X-Studio-Token":token},json=body)
        assert result.status_code==400
        assert not store.list_jobs()

def test_download_is_scoped_and_waits_for_completion(isolated):
    one,_=store.create_job(payload(),"preview","z"*32,10)
    with TestClient(main.app) as client:
        assert client.get("/api/jobs/"+one["id"]+"/file/video").status_code==409
        assert client.get("/api/jobs/invalid/file/video").status_code==400
        assert client.get("/api/jobs/"+one["id"]+"/file/not-allowed").status_code==404

def test_api_key_uses_direct_bearer_without_jwt(monkeypatch):
    def unexpected_jwt(*args): raise AssertionError("API Key must not be converted to a JWT")
    monkeypatch.setattr(providers,"jwt_token",unexpected_jwt)
    cfg={**store.DEFAULTS,"kling_api_key":"fake-new-api-key","kling_access_key":"old","kling_secret_key":"old"}
    assert providers.headers(cfg)=={"Authorization":"Bearer fake-new-api-key"}
    assert providers.has_credentials(cfg)

def test_legacy_credentials_still_work():
    cfg={**store.DEFAULTS,"kling_api_key":"","kling_access_key":"fake-old-access","kling_secret_key":"fake-old-secret"}
    assert providers.has_credentials(cfg)
    assert len(providers.headers(cfg)["Authorization"].split("."))==3

def test_api_key_encrypted_and_never_returned(isolated):
    with TestClient(main.app) as client:
        token=client.get("/api/bootstrap").json()["token"]
        h={"X-Studio-Token":token}
        result=client.put("/api/settings",headers=h,json={"kling_api_key":"fake-only-key-not-real"})
        assert result.status_code==200
        data=result.json()
        assert data["capabilities"]["kling"] is True
        assert data["settings"]["kling_api_key_configured"] is True
        assert "fake-only-key-not-real" not in result.text
        assert "fake-only-key-not-real" not in store.CONFIG.read_text(encoding="utf-8")
        # Re-saving blank fields retains the stored secret.
        assert client.put("/api/settings",headers=h,json={}).status_code==200
        assert store.settings()["kling_api_key"]=="fake-only-key-not-real"
        assert client.put("/api/settings",headers=h,json={"kling_api_key":"__DELETE__"}).status_code==200
        assert not store.settings()["kling_api_key"]

def test_api_key_validation_and_bearer_prefix(isolated):
    with TestClient(main.app) as client:
        h={"X-Studio-Token":client.get("/api/bootstrap").json()["token"]}
        assert client.put("/api/settings",headers=h,json={"kling_api_key":"Bearer fake-key"}).status_code==200
        assert store.settings()["kling_api_key"]=="fake-key"
        assert client.put("/api/settings",headers=h,json={"kling_api_key":"bad\nkey"}).status_code==400

def test_api_key_check_is_readonly_and_keeps_key_out_of_url(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={"code":0,"data":[]})
    real_client=httpx.Client
    monkeypatch.setattr(providers.httpx,"Client",lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    cfg={**store.DEFAULTS,"kling_api_key":"fake-check-key"}
    assert providers.check_kling(cfg)["ok"]
    assert len(calls)==1 and calls[0].method=="GET"
    assert calls[0].headers["Authorization"]=="Bearer fake-check-key"
    assert "fake-check-key" not in str(calls[0].url)

def test_v3_sends_three_timed_storyboards():
    plan=payload()["plan"]
    result=providers.request_body(plan,store.DEFAULTS,external_id="test-only")
    assert result["multi_shot"] is True and result["shot_type"]=="customize"
    assert result["prompt"]==""
    assert [shot["index"] for shot in result["multi_prompt"]]==[1,2,3]
    assert sum(int(shot["duration"]) for shot in result["multi_prompt"])==15
    assert all(len(shot["prompt"])<=512 for shot in result["multi_prompt"])
