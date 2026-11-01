import hashlib
import io
import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app import delivery, share, store

@pytest.fixture
def completed(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DATA",tmp_path)
    monkeypatch.setattr(store,"JOBS",tmp_path/"jobs")
    monkeypatch.setattr(share,"DB",tmp_path/"guest.sqlite3")
    monkeypatch.setattr(store,"settings",lambda:{"retention_hours":72})
    job={"id":"a"*32,"created":time.time(),"status":"completed","deleted":False,"payload":{"plan":{"title":"<测试短片>"}}}
    folder=store.JOBS/job["id"];folder.mkdir(parents=True)
    (folder/"final.mp4").write_bytes(b"test-video-data-for-range")
    monkeypatch.setattr(store,"get_job",lambda i:job if i==job["id"] else None)
    return job

def test_qr_can_be_claimed_without_original_browser_cookie(completed):
    with TestClient(share.app,base_url="https://testserver") as owner,TestClient(share.app,base_url="https://testserver") as phone:
        owner.post('/api/share/start')
        digest=hashlib.sha256(owner.cookies.get(share.COOKIE).encode()).hexdigest()
        with share.db() as db:
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",("test-key",digest,time.time(),"preview","x",completed["id"],"completed"))
        # Give tests an explicit public origin without using any real sharing configuration.
        original=delivery.public_origin
        delivery.public_origin=lambda r:"https://testserver"
        try:
            result=owner.get('/api/jobs/'+completed['id']+'/delivery');assert result.status_code==200
            data=result.json();qr=owner.get(data['qr_url']);assert qr.status_code==200
            assert Image.open(io.BytesIO(qr.content)).format=='PNG'
        finally:delivery.public_origin=original
        path=data['url'].replace('https://testserver','')
        landing=phone.get(path);assert landing.status_code==200
        assert '&lt;测试短片&gt;' in landing.text
        video=phone.get(path+'/video?download=true',headers={'Range':'bytes=0-3'})
        assert video.status_code==206 and video.content==b'test'
        assert 'attachment' in video.headers['content-disposition']
        assert phone.get('/api/jobs/'+completed['id']+'/delivery').status_code==401
        phone.post('/api/share/start')
        assert phone.get('/api/jobs/'+completed['id']+'/delivery').status_code==404
        assert phone.get(path+'/storyboard').status_code==404

def test_expired_deleted_and_unfinished_are_rejected(completed):
    data=delivery.create(completed['id'],'https://testserver');token=data['url'].split('/')[-1]
    assert delivery.create(completed['id'],'https://testserver')['url']==data['url']
    with delivery.database() as db:db.execute('UPDATE links SET expires=0')
    with pytest.raises(Exception) as exc:delivery.resolve(token)
    assert exc.value.status_code==410
    completed['deleted']=True
    with pytest.raises(Exception) as exc:delivery.create(completed['id'],'https://testserver')
    assert exc.value.status_code==410
    completed['deleted']=False;completed['status']='running'
    with pytest.raises(Exception) as exc:delivery.create(completed['id'],'https://testserver')
    assert exc.value.status_code==409
