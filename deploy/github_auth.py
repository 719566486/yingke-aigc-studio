"""Use the existing Git credential manager, never expose tokens in arguments."""
import os
import subprocess


def token(owner):
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    result = subprocess.run(["git", "credential", "fill"], input=f"protocol=https\nhost=github.com\nusername={owner}\n\n", text=True, capture_output=True, env=env, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError("GitHub sign-in is unavailable. Please sign in to GitHub on this computer.")
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not values.get("password"):
        raise RuntimeError("GitHub did not return an authenticated credential.")
    return values["password"]
