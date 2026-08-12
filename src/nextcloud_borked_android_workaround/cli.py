import json
from urllib.parse import urljoin

import click

from .adb import hash_local_files, list_local_files
from .compare import Comparison, compare
from .config import Config, load_config
from .upload import make_session
from .verify import (
    VerifyResult,
    classify,
    index_by_name,
    needed_algos,
)
from .webdav import download_hash, list_remote_files


def _report(cfg: Config, result: Comparison, n_local: int, n_remote: int) -> None:
    click.echo(f"Local photos ({cfg.local_root}): {n_local}")
    click.echo(f"Remote files ({cfg.remote_root or '/'}): {n_remote}")
    click.echo("")
    click.echo(f"  matched (name+size):    {len(result.matched)}")
    click.echo(f"  uncertain (name|size):  {len(result.uncertain)}")
    click.echo(f"  local-only (missing):   {len(result.local_only)}")

    if result.uncertain:
        click.echo("\nUncertain — name OR size matches remote, but not both:")
        for f in sorted(result.uncertain, key=lambda x: x.name):
            click.echo(f"  ? {f.name}  ({f.size} bytes)")

    if result.local_only:
        click.echo("\nLocal-only — no name/size match on the server:")
        for f in sorted(result.local_only, key=lambda x: x.name):
            click.echo(f"  + {f.path}  ({f.size} bytes)")


def _report_verify(result: VerifyResult, downloaded: bool) -> None:
    suffix = " (+download)" if downloaded else ""
    click.echo(f"\nHash verification{suffix}:")
    click.echo(f"  verified:      {len(result.verified)}")
    click.echo(f"  MISMATCH:      {len(result.mismatch)}")
    click.echo(f"  unverifiable:  {len(result.unverifiable)}")

    if result.mismatch:
        click.echo("\n  !! CONTENT MISMATCH — server bytes differ from the phone:")
        for f in sorted(result.mismatch, key=lambda x: x.name):
            click.echo(f"     {f.path}")

    if result.unverifiable:
        click.echo(
            "\n  unverifiable — server stores no checksum; re-run with --download-verify:"
        )
        shown = sorted(result.unverifiable, key=lambda x: x.name)[:20]
        for f in shown:
            click.echo(f"     {f.name}")
        if len(result.unverifiable) > 20:
            click.echo(f"     ... and {len(result.unverifiable) - 20} more")


def _remote_url(cfg: Config, path: str) -> str:
    return urljoin(cfg.base_url + "/", path.lstrip("/"))


def _download_settle(cfg, result, index, local_hashes):
    session = make_session(cfg)
    still: list = []
    total = len(result.unverifiable)
    for n, f in enumerate(result.unverifiable, start=1):
        mine = local_hashes.get(f.path, {}).get("SHA1")
        if not mine:
            still.append(f)
            click.echo(f"  [{n}/{total}] {f.name}  no local hash — skipped", err=True)
            continue
        ok = any(
            download_hash(session, _remote_url(cfg, r.path), "SHA1") == mine
            for r in index.get(f.name, [])
        )
        (result.verified if ok else result.mismatch).append(f)
        verdict = "ok" if ok else "MISMATCH"
        click.echo(f"  [{n}/{total}] {f.name}  {verdict}", err=True)
    result.unverifiable = still
    return result


def _run_verify(cfg: Config, local, remote, download: bool) -> VerifyResult:
    index = index_by_name(remote)
    to_hash = [f for f in local if f.name in index]
    names = {f.name for f in to_hash}

    algos = needed_algos(remote, names)
    if download and "SHA1" not in algos:
        algos = algos + ["SHA1"]

    click.echo(
        f"Hashing {len(to_hash)} local files on device ({', '.join(algos) or 'none'})...",
        err=True,
    )
    local_hashes: dict[str, dict[str, str]] = {}
    for algo in algos:
        for path, digest in hash_local_files(
            [f.path for f in to_hash], cfg.adb_serial, algo
        ).items():
            local_hashes.setdefault(path, {})[algo] = digest

    result = classify(to_hash, index, local_hashes)
    if download and result.unverifiable:
        click.echo(
            f"Downloading {len(result.unverifiable)} files with no stored checksum...",
            err=True,
        )
        result = _download_settle(cfg, result, index, local_hashes)
    return result


def _to_json(
    result: Comparison, n_local: int, n_remote: int, verify: VerifyResult | None
) -> str:
    def rows(files):
        return [{"name": f.name, "size": f.size, "path": f.path} for f in files]

    payload = {
        "counts": {
            "local": n_local,
            "remote": n_remote,
            "matched": len(result.matched),
            "uncertain": len(result.uncertain),
            "local_only": len(result.local_only),
        },
        "local_only": rows(result.local_only),
        "uncertain": rows(result.uncertain),
    }
    if verify is not None:
        payload["counts"]["verified"] = len(verify.verified)
        payload["counts"]["mismatch"] = len(verify.mismatch)
        payload["counts"]["unverifiable"] = len(verify.unverifiable)
        payload["mismatch"] = rows(verify.mismatch)
        payload["unverifiable"] = rows(verify.unverifiable)
    return json.dumps(payload, indent=2)


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a text report.")
@click.option(
    "--name-contains",
    default=None,
    help="Only compare local files whose name contains this (e.g. _2026). "
    "Overrides PHONE_PHOTO_NAME_CONTAINS.",
)
@click.option(
    "--verify",
    is_flag=True,
    help="Content-verify matched files via stored checksums (oc:checksums).",
)
@click.option(
    "--download-verify",
    is_flag=True,
    help="For files the server has no checksum for, download and hash them. Implies --verify.",
)
def main(
    as_json: bool, name_contains: str | None, verify: bool, download_verify: bool
) -> None:
    """Compare local phone photos (via adb) against Nextcloud files (via WebDAV)."""
    cfg = load_config()
    local = list_local_files(cfg.local_root, cfg.adb_serial)

    needle = name_contains or cfg.local_name_contains
    if needle:
        local = [f for f in local if needle in f.name]

    remote = list_remote_files(cfg)
    result = compare(local, remote)

    verify_result = None
    if verify or download_verify:
        verify_result = _run_verify(cfg, local, remote, download_verify)

    if as_json:
        click.echo(_to_json(result, len(local), len(remote), verify_result))
        return

    _report(cfg, result, len(local), len(remote))
    if verify_result is not None:
        _report_verify(verify_result, download_verify)
