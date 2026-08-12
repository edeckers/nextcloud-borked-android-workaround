import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, unquote, quote

import requests

DAV = "{DAV:}"
OC = "{http://owncloud.org/ns}"

_PROPFIND_BODY = (
    '<?xml version="1.0"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop>'
    "<d:getcontentlength/><d:resourcetype/><oc:checksums/>"
    "</d:prop></d:propfind>"
)


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: int
    path: str
    checksums: tuple[str, ...]


@dataclass(frozen=True)
class _Entry:
    url: str
    name: str
    size: int
    is_dir: bool
    checksums: tuple[str, ...]


def _dav_root(cfg) -> str:
    root = f"{cfg.base_url}/remote.php/dav/files/{quote(cfg.username)}/"
    if cfg.remote_root:
        root += f"{quote(cfg.remote_root)}/"
    return root


def _parse(xml_text: str, request_url: str) -> list[_Entry]:
    tree = ET.fromstring(xml_text)
    self_path = urlsplit(request_url).path.rstrip("/")
    entries = []
    for response in tree.findall(f"{DAV}response"):
        href = response.findtext(f"{DAV}href")
        if href is None:
            continue
        href_path = urlsplit(href).path
        if href_path.rstrip("/") == self_path:
            continue
        is_dir = response.find(f".//{DAV}resourcetype/{DAV}collection") is not None
        size_text = response.findtext(f".//{DAV}getcontentlength")
        size = int(size_text) if size_text and size_text.isdigit() else 0
        name = unquote(href_path.rstrip("/").rsplit("/", 1)[-1])
        checksums = tuple(
            node.text.strip()
            for node in response.findall(f".//{OC}checksums/{OC}checksum")
            if node.text and node.text.strip()
        )
        entries.append(
            _Entry(
                url=urljoin(request_url, href),
                name=name,
                size=size,
                is_dir=is_dir,
                checksums=checksums,
            )
        )
    return entries


def _propfind(session: requests.Session, url: str) -> list[_Entry]:
    resp = session.request(
        "PROPFIND", url, headers={"Depth": "1"}, data=_PROPFIND_BODY, timeout=60
    )
    resp.raise_for_status()
    return _parse(resp.text, url)


def list_remote_files(cfg) -> list[RemoteFile]:
    session = requests.Session()
    session.auth = (cfg.username, cfg.app_password)
    files: list[RemoteFile] = []
    pending = [_dav_root(cfg)]
    while pending:
        url = pending.pop()
        for entry in _propfind(session, url):
            if entry.is_dir:
                pending.append(entry.url if entry.url.endswith("/") else entry.url + "/")
                continue
            files.append(
                RemoteFile(
                    name=entry.name,
                    size=entry.size,
                    path=urlsplit(entry.url).path,
                    checksums=entry.checksums,
                )
            )
    return files


def download_hash(session: requests.Session, url: str, algo: str) -> str:
    digest = hashlib.new(algo.lower())
    with session.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_content(65536):
            digest.update(chunk)
        return digest.hexdigest().lower()
