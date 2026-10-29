from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import store
from github_auth import token
from github_fallback import publish_tree

PROJECT = json.loads((ROOT / "deploy/project.json").read_text(encoding="utf-8"))
OWNER, REPO = PROJECT["owner"], PROJECT["repository"]
REMOTE = f"https://github.com/{OWNER}/{REPO}.git"
DESCRIPTION = "映刻 AIGC 创作体验平台：GitHub 访问入口与本机生成后台"
ALLOWED = ["app", "static", "tests", "deploy", "docs", ".github/workflows", "Dockerfile", ".dockerignore", "compose.yaml", "render.yaml", ".gitignore", "README.md", "requirements.txt", "requirements-lock.txt", "run.py", "run_share.py", "start.ps1", "stop.ps1", "启动平台.cmd", "停止平台.cmd", "share_start.ps1", "share_stop.ps1", "启动分享.cmd", "停止分享.cmd"]


def git(*arguments, check=True, timeout=150):
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", PYTHONIOENCODING="utf-8")
    result = subprocess.run(["git", "-c", "core.quotepath=false", "-c", "http.version=HTTP/1.1", *arguments], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check and result.returncode:
        raise RuntimeError("Git operation failed: " + result.stderr[-1200:])
    return result


def audit_staged():
    paths = git("diff", "--cached", "--name-only", "-z").stdout.split("\0")
    private = [v for key, v in store.settings().items() if key in store.SECRETS and v]
    manifest = []
    for name in filter(None, paths):
        if not any(name == prefix or name.startswith(prefix + "/") for prefix in ALLOWED):
            raise RuntimeError("Unexpected staged path: " + name)
        if git("diff", "--cached", "--name-status", "--", name).stdout.startswith("D\t"):
            continue
        raw = subprocess.run(["git", "show", ":" + name], cwd=ROOT, capture_output=True, timeout=20).stdout
        if len(raw) > 2 * 1024 * 1024:
            raise RuntimeError("Unexpected large source file: " + name)
        if any(value.encode() in raw for value in private):
            raise RuntimeError("A configured private credential was found in staged source. Upload stopped.")
        manifest.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    if manifest:
        (ROOT / "work/github-source-audit.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(manifest)


def publish(initial=False):
    headers = {"Authorization": "Bearer " + token(OWNER), "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    with httpx.Client(timeout=40, headers=headers) as client:
        identity = client.get("https://api.github.com/user")
        identity.raise_for_status()
        user = identity.json()
        if user["login"].lower() != OWNER.lower():
            raise RuntimeError("The signed-in GitHub account does not own the selected project.")
        if initial:
            if not (ROOT / ".git").exists():
                git("init", "-b", "main")
            git("config", "user.name", user["login"])
            git("config", "user.email", f"{user['id']}+{user['login']}@users.noreply.github.com")
            git("config", "core.autocrlf", "false")
            paths = [name for name in ALLOWED if (ROOT / name).exists()]
            git("add", "--", *paths)
        else:
            if not (ROOT / ".git").exists():
                raise RuntimeError("The source repository has not been published yet.")
            git("add", "--", "docs/connection.json")
        count = audit_staged()
        endpoint = f"https://api.github.com/repos/{OWNER}/{REPO}"
        repository = client.get(endpoint)
        if repository.status_code == 404:
            if not initial:
                raise RuntimeError("The selected GitHub repository does not exist yet.")
            repository = client.post("https://api.github.com/user/repos", json={"name": REPO, "description": DESCRIPTION, "private": False, "auto_init": False, "homepage": PROJECT["pages_url"]})
            repository.raise_for_status()
        else:
            repository.raise_for_status()
        repo = repository.json()
        previous = git("remote", "get-url", "origin", check=False)
        if previous.returncode:
            git("remote", "add", "origin", REMOTE)
        elif previous.stdout.strip() != REMOTE:
            raise RuntimeError("The existing Git remote differs from the selected repository.")
        if git("diff", "--cached", "--quiet", check=False).returncode:
            args = ["commit", "-m", "Publish Yingke local-backed experience" if initial else "Update active experience connection"]
            if not initial:
                args.extend(["--", "docs/connection.json"])
            git(*args)
        try:
            git("push", "-u", "origin", "main", timeout=40)
        except (RuntimeError, subprocess.TimeoutExpired):
            private = [value for key, value in store.settings().items() if key in store.SECRETS and value]
            publish_tree(client, endpoint, ROOT, ALLOWED, private, user)
        pages = client.get(endpoint + "/pages")
        if pages.status_code == 404:
            pages = client.post(endpoint + "/pages", json={"source": {"branch": "main", "path": "/docs"}, "build_type": "legacy"})
            pages.raise_for_status()
        else:
            pages.raise_for_status()
        info = pages.json()
        result = {"repository_url": repo["html_url"], "pages_url": info.get("html_url", PROJECT["pages_url"]), "commit": git("rev-parse", "HEAD").stdout.strip(), "staged_source_files_checked": count}
        (ROOT / "data/github-publication.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial", action="store_true")
    args = parser.parse_args()
    print(json.dumps(publish(args.initial), ensure_ascii=False))
