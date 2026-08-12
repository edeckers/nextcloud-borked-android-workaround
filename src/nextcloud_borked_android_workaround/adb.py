import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalFile:
    name: str
    size: int
    path: str


def _base(serial: str | None) -> list[str]:
    prefix = ["adb"]
    if serial:
        prefix += ["-s", serial]
    return prefix


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"adb command failed ({' '.join(args)}):\n{result.stderr.strip()}"
        )
    return result.stdout


def _parse_line(line: str) -> LocalFile | None:
    size_str, sep, path = line.strip().partition("|")
    if not sep or not size_str.isdigit():
        return None
    return LocalFile(name=path.rsplit("/", 1)[-1], size=int(size_str), path=path)


def list_local_files(root: str, serial: str | None) -> list[LocalFile]:
    # -printf keeps size and path on one delimited line so no per-file stat round-trips.
    command = f"find '{root}' -type f -printf '%s|%p\\n'"
    out = _run(_base(serial) + ["shell", command])
    parsed = (_parse_line(line) for line in out.splitlines())
    return [f for f in parsed if f is not None]


_ALGO_CMD = {"SHA1": "sha1sum", "MD5": "md5sum"}


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def hash_local_files(paths: list[str], serial: str | None, algo: str) -> dict[str, str]:
    """Hash files on the device itself, so only digests cross the USB link."""
    command = _ALGO_CMD[algo]
    digests: dict[str, str] = {}
    for chunk in _chunks(paths, 100):
        joined = " ".join(f"'{p}'" for p in chunk)
        out = _run(_base(serial) + ["shell", f"{command} {joined}"])
        for line in out.splitlines():
            digest, sep, path = line.strip().partition("  ")
            if sep and path:
                digests[path.strip()] = digest.strip().lower()
    return digests
