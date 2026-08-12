import hashlib
import subprocess
from urllib.parse import quote

import requests


def make_session(cfg) -> requests.Session:
    session = requests.Session()
    session.auth = (cfg.username, cfg.app_password)
    return session


def _files_url(base_url: str, user: str) -> str:
    return f"{base_url}/remote.php/dav/files/{quote(user)}/"


def pull_bytes(path: str, serial: str | None) -> bytes:
    # exec-out streams raw bytes with no newline translation, unlike `adb shell`.
    args = ["adb"] + (["-s", serial] if serial else []) + ["exec-out", "cat", path]
    proc = subprocess.run(args, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip())
    return proc.stdout


def ensure_dir(session: requests.Session, base_url: str, user: str, dest: str) -> None:
    if not dest:
        return
    url = _files_url(base_url, user)
    for segment in [s for s in dest.strip("/").split("/") if s]:
        url += quote(segment) + "/"
        resp = session.request("MKCOL", url, timeout=60)
        if resp.status_code in (201, 405, 301):
            continue
        resp.raise_for_status()


def upload_bytes(
    session: requests.Session,
    base_url: str,
    user: str,
    dest: str,
    name: str,
    data: bytes,
) -> int:
    url = _files_url(base_url, user)
    if dest:
        url += quote(dest.strip("/")) + "/"
    url += quote(name)
    # Server rejects the PUT (400) if the bytes don't match, and stores the checksum
    # so later --verify runs are free.
    headers = {"OC-Checksum": f"SHA1:{hashlib.sha1(data).hexdigest()}"}
    resp = session.put(url, data=data, headers=headers, timeout=600)
    resp.raise_for_status()
    return resp.status_code
