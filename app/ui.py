"""Keep each rendered page tied to the current CSS and script contents."""
import hashlib
import re
from .store import ROOT

ASSETS = re.compile(r'((?:src|href)=")/(styles\.css|app\.js|share\.css|share-client\.js)(?:\?[^"]*)?(")')


def version_assets(html):
    def replace(match):
        name = match.group(2)
        version = hashlib.sha256((ROOT / "static" / name).read_bytes()).hexdigest()[:12]
        return f'{match.group(1)}/{name}?v={version}{match.group(3)}'
    return ASSETS.sub(replace, html)
