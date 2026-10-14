"""
Where the app keeps its data.

  GitHubStorage - saves everything into a PRIVATE GitHub repo through the GitHub API.
                  Survives Streamlit Cloud restarts and redeploys.
  LocalStorage  - plain folder on disk. Used automatically when no GitHub secrets are set
                  (e.g. running on your own computer).

Paths used by the app (same on both backends):
    games.json            list of all games
    xml/<id>.xml          the Sportscode XML for each game
    opponents/<file>      optional opponent crests
"""

import base64
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests


class StorageError(RuntimeError):
    pass


# ============================================================
# LOCAL DISK
# ============================================================
class LocalStorage:
    name = "local"
    label = "Local disk"

    def __init__(self, root):
        self.root = Path(root)

    def read(self, path):
        p = self.root / path
        return p.read_bytes() if p.exists() else None

    def write(self, path, data, message=""):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, path, message=""):
        (self.root / path).unlink(missing_ok=True)

    def check(self):
        return True, "Saving to a local folder (data/ next to app.py)."


# ============================================================
# GITHUB (contents API)
# ============================================================
class GitHubStorage:
    name = "github"
    label = "GitHub (permanent)"

    def __init__(self, token, repo, branch="main", folder=""):
        self.repo = repo
        self.branch = branch
        self.folder = folder.strip("/")
        self.base = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, path):
        full = f"{self.folder}/{path}" if self.folder else path
        return f"{self.base}/contents/{quote(full)}"

    @staticmethod
    def _raise(r, what):
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except Exception:  # noqa: BLE001
                msg = r.text
            raise StorageError(f"GitHub {what} failed ({r.status_code}): {msg}")

    def _sha(self, path):
        r = requests.get(self._url(path), params={"ref": self.branch}, timeout=30,
                         headers={**self.headers, "Accept": "application/vnd.github+json"})
        if r.status_code == 404:
            return None
        self._raise(r, f"lookup of {path}")
        return r.json()["sha"]

    def read(self, path):
        r = requests.get(self._url(path), params={"ref": self.branch}, timeout=60,
                         headers={**self.headers, "Accept": "application/vnd.github.raw+json"})
        if r.status_code == 404:
            return None
        self._raise(r, f"read of {path}")
        return r.content

    def write(self, path, data, message="Update from dashboard"):
        for attempt in range(2):
            body = {"message": message, "branch": self.branch,
                    "content": base64.b64encode(data).decode()}
            sha = self._sha(path)
            if sha:
                body["sha"] = sha
            r = requests.put(self._url(path), json=body, timeout=120,
                             headers={**self.headers, "Accept": "application/vnd.github+json"})
            if r.status_code == 409 and attempt == 0:  # stale sha - fetch again and retry once
                continue
            self._raise(r, f"write of {path}")
            return

    def delete(self, path, message="Delete from dashboard"):
        sha = self._sha(path)
        if sha is None:
            return
        r = requests.delete(self._url(path), timeout=60,
                            json={"message": message, "sha": sha, "branch": self.branch},
                            headers={**self.headers, "Accept": "application/vnd.github+json"})
        self._raise(r, f"delete of {path}")

    def check(self):
        """Returns (ok, message). Verifies the token can reach the repo and that it is private."""
        try:
            r = requests.get(self.base, timeout=30,
                             headers={**self.headers, "Accept": "application/vnd.github+json"})
        except requests.RequestException as e:
            return False, f"Couldn't reach GitHub: {e}"
        if r.status_code == 401:
            return False, "GitHub rejected the token (401). It may be wrong or expired."
        if r.status_code == 404:
            return False, (f"Repo `{self.repo}` not found. Check the name in your secrets, and that the "
                           "token has access to that repo.")
        if r.status_code >= 400:
            return False, f"GitHub error {r.status_code}: {r.text[:200]}"
        info = r.json()
        if not info.get("permissions", {}).get("push", True):
            return False, "The token can read the repo but not write to it. Give it Contents: Read and write."
        if not info.get("private", True):
            return True, "WARNING: this data repo is PUBLIC - anyone can read your match data. Make it private."
        return True, "Connected to private GitHub repo."


# ============================================================
# BACKUP / RESTORE (works with either backend)
# ============================================================
def build_backup_zip(store):
    raw = store.read("games.json") or b"[]"
    games = json.loads(raw)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("games.json", raw)
        for g in games:
            xml = store.read(f"xml/{g['xml_file']}")
            if xml is not None:
                z.writestr(f"xml/{g['xml_file']}", xml)
            if g.get("opp_logo"):
                logo = store.read(f"opponents/{g['opp_logo']}")
                if logo is not None:
                    z.writestr(f"opponents/{g['opp_logo']}", logo)
    return buf.getvalue()


def restore_backup_zip(store, zip_bytes):
    """Adds games from a backup zip that aren't already stored. Returns (added, skipped).

    Accepts zips from this version and from the earlier local-only version
    (it matches files by name, so folder layout inside the zip doesn't matter).
    """
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    by_name = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
    if "games.json" not in by_name:
        raise ValueError("That zip has no games.json - is it a backup from this dashboard?")
    incoming = json.loads(z.read(by_name["games.json"]))

    existing = json.loads(store.read("games.json") or b"[]")
    have = {g["id"] for g in existing}
    added = skipped = 0
    for g in incoming:
        if g["id"] in have:
            continue
        xml_member = by_name.get(g["xml_file"])
        if xml_member is None:
            skipped += 1
            continue
        store.write(f"xml/{g['xml_file']}", z.read(xml_member), f"Restore {g['opponent']}")
        logo = g.get("opp_logo")
        if logo and logo in by_name:
            store.write(f"opponents/{logo}", z.read(by_name[logo]), f"Restore crest {g['opponent']}")
        existing.append(g)
        added += 1
    if added:
        store.write("games.json", json.dumps(existing, indent=2).encode(), f"Restore {added} game(s)")
    return added, skipped
