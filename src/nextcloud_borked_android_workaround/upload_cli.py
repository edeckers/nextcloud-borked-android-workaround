import json
import re
import sys

import click

from .config import load_config
from .upload import ensure_dir, make_session, pull_bytes, upload_bytes

_DATE = re.compile(r"_(\d{8})_")


def _date_ge(name: str, since: str) -> bool:
    m = _DATE.search(name)
    return bool(m) and m.group(1) >= since


@click.command()
@click.option("--dest", default=None, help="Remote folder to upload into. Default: NEXTCLOUD_REMOTE_ROOT.")
@click.option("--since", default=None, help="Only upload files whose name date (YYYYMMDD) >= this.")
@click.option("--yes", is_flag=True, help="Actually upload. Without it, prints the plan and exits.")
def main(dest: str | None, since: str | None, yes: bool) -> None:
    """Upload the local_only files from a compare JSON (read on stdin) to Nextcloud."""
    payload = json.load(sys.stdin)
    items = payload.get("local_only", [])
    if since:
        items = [x for x in items if _date_ge(x["name"], since)]

    cfg = load_config()
    target = dest if dest is not None else cfg.remote_root
    total = sum(x.get("size", 0) for x in items)
    click.echo(f"{len(items)} files, {total / 1e9:.2f} GB -> {target or '/'}", err=True)

    if not items:
        return

    if not yes:
        for x in items:
            click.echo(f"  would upload {x['name']}", err=True)
        click.echo("dry run — pass --yes to upload.", err=True)
        return

    session = make_session(cfg)
    ensure_dir(session, cfg.base_url, cfg.username, target)

    done = 0
    failed = 0
    for x in items:
        try:
            data = pull_bytes(x["path"], cfg.adb_serial)
            code = upload_bytes(session, cfg.base_url, cfg.username, target, x["name"], data)
            done += 1
            click.echo(f"  [{done + failed}/{len(items)}] {x['name']} ({code})", err=True)
        except Exception as exc:
            failed += 1
            click.echo(f"  FAIL {x['name']}: {exc}", err=True)

    click.echo(f"done: {done} uploaded, {failed} failed", err=True)
