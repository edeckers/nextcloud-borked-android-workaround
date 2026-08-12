from dataclasses import dataclass

from .adb import LocalFile
from .webdav import RemoteFile


@dataclass(frozen=True)
class Comparison:
    matched: list[LocalFile]
    uncertain: list[LocalFile]
    local_only: list[LocalFile]


def compare(local: list[LocalFile], remote: list[RemoteFile]) -> Comparison:
    remote_name_size = {(f.name, f.size) for f in remote}
    remote_names = {f.name for f in remote}
    remote_sizes = {f.size for f in remote}

    matched: list[LocalFile] = []
    uncertain: list[LocalFile] = []
    local_only: list[LocalFile] = []

    for f in local:
        if (f.name, f.size) in remote_name_size:
            matched.append(f)
            continue
        if f.name in remote_names or f.size in remote_sizes:
            uncertain.append(f)
            continue
        local_only.append(f)

    return Comparison(matched=matched, uncertain=uncertain, local_only=local_only)
