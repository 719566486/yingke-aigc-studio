"""Publish the audited local tree when Git HTTPS transport is unavailable."""
from datetime import datetime, timezone
import base64
import os
import subprocess


def publish_tree(client, endpoint, root, allowed, private, user):
    def git(*args, input=None, env=None):
        result = subprocess.run(["git", *args], cwd=root, input=input, env=env,
                                capture_output=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise RuntimeError("Local publication check failed")
        return result.stdout

    def request(method, path, body=None):
        response = client.request(method, endpoint + path, json=body)
        response.raise_for_status()
        return response.json()

    remote = request("GET", "/git/ref/heads/main")["object"]["sha"]
    original = git("rev-parse", "HEAD").decode().strip()
    if original == remote:
        return original
    # Never replace independent remote work; update the ref without force below.
    git("merge-base", "--is-ancestor", remote, original)
    changed = set(filter(None, git("diff", "--name-only", "-z", remote, original).decode().split("\0")))
    entries = []
    for row in filter(None, git("ls-tree", "-rz", original).decode().split("\0")):
        metadata, path = row.split("\t", 1)
        mode, kind, sha = metadata.split()
        if kind != "blob" or not any(path == p or path.startswith(p + "/") for p in allowed):
            raise RuntimeError("Unexpected tracked publication content")
        raw = git("show", original + ":" + path)
        if len(raw) > 2 * 1024 * 1024 or any(value.encode() in raw for value in private):
            raise RuntimeError("Source privacy check failed; publication stopped")
        if path in changed:
            blob = request("POST", "/git/blobs", {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
            if blob["sha"] != sha:
                raise RuntimeError("Uploaded file identity mismatch")
        entries.append({"path": path, "mode": mode, "type": "blob", "sha": sha})
    tree = request("POST", "/git/trees", {"tree": entries})["sha"]
    if tree != git("rev-parse", original + "^{tree}").decode().strip():
        raise RuntimeError("Uploaded source tree identity mismatch")
    when = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    name, email = user["login"], f"{user['id']}+{user['login']}@users.noreply.github.com"
    message = "Restore shared studio connection\n"
    who = {"name": name, "email": email, "date": when}
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": when,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": when}
    local = git("commit-tree", tree, "-p", remote, input=message.encode(), env=env).decode().strip()
    commit = request("POST", "/git/commits", {"message": message, "tree": tree, "parents": [remote], "author": who, "committer": who})
    if local != commit["sha"]:
        raise RuntimeError("Commit identity mismatch; remote ref not modified")
    request("PATCH", "/git/refs/heads/main", {"sha": local, "force": False})
    git("update-ref", "refs/heads/main", local, original)
    git("update-ref", "refs/remotes/origin/main", local)
    return local
