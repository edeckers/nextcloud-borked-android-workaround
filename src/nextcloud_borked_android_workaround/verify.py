from dataclasses import dataclass

from .adb import LocalFile
from .webdav import RemoteFile

SUPPORTED = ("SHA1", "MD5")


def parse_checksums(tokens: tuple[str, ...]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for token in tokens:
        algo, sep, hexval = token.partition(":")
        if sep:
            parsed[algo.upper()] = hexval.strip().lower()
    return parsed


def index_by_name(remote: list[RemoteFile]) -> dict[str, list[RemoteFile]]:
    index: dict[str, list[RemoteFile]] = {}
    for r in remote:
        index.setdefault(r.name, []).append(r)
    return index


def needed_algos(remote: list[RemoteFile], names: set[str]) -> list[str]:
    seen: set[str] = set()
    for r in remote:
        if r.name in names:
            seen.update(parse_checksums(r.checksums))
    return [a for a in SUPPORTED if a in seen]


def remote_checksums_for(candidates: list[RemoteFile]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for r in candidates:
        merged.update(parse_checksums(r.checksums))
    return merged


@dataclass
class VerifyResult:
    verified: list[LocalFile]
    mismatch: list[LocalFile]
    unverifiable: list[LocalFile]


def classify(
    local: list[LocalFile],
    index: dict[str, list[RemoteFile]],
    local_hashes: dict[str, dict[str, str]],
) -> VerifyResult:
    verified: list[LocalFile] = []
    mismatch: list[LocalFile] = []
    unverifiable: list[LocalFile] = []

    for f in local:
        candidates = index.get(f.name)
        if not candidates:
            continue
        remote_cs = remote_checksums_for(candidates)
        usable = {a: h for a, h in remote_cs.items() if a in SUPPORTED}
        if not usable:
            unverifiable.append(f)
            continue
        mine = local_hashes.get(f.path, {})
        ok = any(mine.get(algo) == hexval for algo, hexval in usable.items())
        (verified if ok else mismatch).append(f)

    return VerifyResult(verified=verified, mismatch=mismatch, unverifiable=unverifiable)
