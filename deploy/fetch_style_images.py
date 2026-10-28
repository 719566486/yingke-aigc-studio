from pathlib import Path
import hashlib,html,json,re,time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import httpx

ROOT=Path(__file__).resolve().parent.parent
DEST=ROOT/'static/assets/styles';DEST.mkdir(parents=True,exist_ok=True)
SOURCES=[
 ('cinema','Tears of Steel frame 00 1c.jpg','Blender Foundation / Project Mango','https://creativecommons.org/licenses/by/3.0/'),
 ('anime','SpringOpenMovie-final scene.jpg','Blender Institute','https://creativecommons.org/licenses/by-sa/4.0/'),
 ('fantasy','Sintel-screenshot-4.jpg','Blender Foundation / Sintel','https://creativecommons.org/licenses/by/3.0/'),
]
def fetch(item):
    key,title,author,license_url=item
    title=title.replace(' ','_');md5=hashlib.md5(title.encode()).hexdigest()
    url=f'https://upload.wikimedia.org/wikipedia/commons/{md5[0]}/{md5[:2]}/{quote(title)}'
    if key=='cinema':url=f'https://thumb.wikimedia.org/wikipedia/commons/thumb/{md5[0]}/{md5[:2]}/{quote(title)}/960px-{quote(title)}'
    with httpx.Client(timeout=35,follow_redirects=True,headers={'User-Agent':'YingkeStudio/1.0 (https://github.com/719566486/yingke-aigc-studio; licensed style reference downloader)'}) as client:
        r=client.get(url);r.raise_for_status();assert r.headers.get('content-type','').startswith('image/')
    (DEST/(key+'.jpg')).write_bytes(r.content)
    return {'style':key,'file':key+'.jpg','source':'https://commons.wikimedia.org/wiki/File:'+quote(title),'author':author,'license':license_url,'modifications':'Displayed with CSS cropping only; source image not edited.'}
with ThreadPoolExecutor(max_workers=2) as pool:
    entries=list(pool.map(fetch,SOURCES))
with httpx.Client(timeout=35,follow_redirects=True) as client:
    r=client.get('https://collectionapi.metmuseum.org/public/collection/v1/objects/49175');r.raise_for_status();obj=r.json();assert obj['isPublicDomain']
    picture=client.get(obj['primaryImageSmall']);picture.raise_for_status();assert picture.headers.get('content-type','').startswith('image/')
    (DEST/'ink.jpg').write_bytes(picture.content)
entries.append({'style':'ink','file':'ink.jpg','source':'https://www.metmuseum.org/art/collection/search/49175','author':'Shitao (Zhu Ruoji), dated 1699 / The Metropolitan Museum of Art','license':'https://creativecommons.org/publicdomain/zero/1.0/','modifications':'Displayed with CSS cropping only; source image not edited.'})
(DEST/'credits.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{'style':e['style'],'bytes':(DEST/e['file']).stat().st_size} for e in entries]))
