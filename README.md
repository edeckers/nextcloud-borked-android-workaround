# nextcloud-borked-android-workaround

Compares the photos physically on an Android phone against what actually exists in Nextcloud, to answer "which camera photos never made it to the server?", without relying on the Nextcloud Android app's own sync state.

A workaround for the Nextcloud Android auto-upload reliability problems tracked in [nextcloud/android#16550](https://github.com/nextcloud/android/issues/16550): when auto-upload silently misses files, this finds the gaps by comparing the phone directly against the server. See [Background](#background-nextcloudandroid16550) for details.

## Why this exists

The obvious way to get the full picture would be to read the Nextcloud Android app's SQLite file index. On a non-rooted phone that's impossible: the DB sits in `/data/data/com.nextcloud.client/`, `run-as` is refused because the release build isn't debuggable, and the app ships with `allowBackup="false"` so `adb backup` returns an empty archive. So this tool sidesteps the app entirely: it reads the raw photo files off the phone over adb, reads the authoritative file list off the server over WebDAV, and diffs the two.

## Background: nextcloud/android#16550

This tool exists because the Nextcloud Android app's auto-upload can miss files, and the app's own UI doesn't always make that visible. The upstream issue is [nextcloud/android#16550, "Auto-upload: Call for debug help"](https://github.com/nextcloud/android/issues/16550): the Nextcloud team posted it to ask the community for help debugging auto-upload reliability, referencing versions 33.0.1 to 34.1.0. Symptoms listed there include job cancellation, duplicated database entries, pending media that never triggers, conflict-handling edge cases, files stuck in a `LOCKED` state, and battery optimization stopping the upload worker. The practical takeaway: check independently that your photos made it across, rather than assuming. That's what this repo does.

It's a common experience. In [one comment](https://github.com/nextcloud/android/issues/16550#issuecomment-5062597581), a user ran their own checker and found roughly 1200 files (about 16 GB) that hadn't been backed up since their previous run. Their suggestion, to have the app keep a small `uploaded_files.db` and reconcile it against the camera folder (the way pCloud does), is a design the app doesn't currently have, which is part of why an external comparison like this one is useful today.

### An alternative to this repository

That same commenter maintains [MateuszKubuszok/ncimgupload](https://github.com/MateuszKubuszok/ncimgupload), a script that does much the same thing as this repo: scan the phone for images and videos that aren't on the server, and upload the missing ones. If you'd like a second, independently written tool for the same job, or just a cross-check against this one, it's a good option.

### Failure modes worth knowing about

Everything in [this comment](https://github.com/nextcloud/android/issues/16550#issuecomment-5077364561) lines up with what I ran into. Useful to know before settling on an auto-upload config:

- "Move to app folder" plus "always ask on duplicates": the setup that feels safest (moving uploaded files aside so you can see what's left) caused trouble for me, with some photos not uploaded and the queue holding entries for files that had already been moved out of the source folder.
- "Rename duplicates": led to hundreds of duplicate copies on the server, with repeated upload retries.
- "Move to app folder" plus "skip duplicates": the combination that reliably uploaded and moved everything for me.
- Settings changes may not take effect until you wipe the app, because the existing queue keeps using the config it was created with.
- An upload replacing a non-empty file with a 0-byte one: the kind of silent truncation that `--download-verify` is meant to catch.

## How the comparison works

Neither side gives you a cheap content hash for free (Nextcloud's WebDAV ETags are opaque server tokens, not MD5s of the file body), so matching is done on **basename + size**, bucketed into three tiers:

- **matched**: same filename *and* same byte size exists remotely. Almost certainly the same photo.
- **uncertain**: filename *or* size matches, but not both. Usually an instant-upload rename or a size coincidence; worth a glance.
- **local-only**: no name or size match on the server. These are the real "not backed up" candidates.

This is intentionally a no-download comparison. A byte-for-byte guarantee would require pulling every remote file down to hash it locally, which defeats the point; the name+size heuristic is the pragmatic sweet spot.

## Setup

```sh
cp .env.example .env   # then edit .env
```

Generate the app password in Nextcloud under **Settings → Security → Devices & sessions → Create new app password**. Plug it, your username, and (optionally) a specific server folder into `.env`.

Make sure the phone is attached and authorized:

```sh
adb devices   # should list your device as "device", not "unauthorized"
```

## Usage

```sh
uv run nextcloud-borked-android-workaround           # text report
uv run nextcloud-borked-android-workaround --json    # machine-readable
```

### Content verification (hashes)

Name+size says a file is *present*; it doesn't prove the bytes are intact. `--verify` adds a content check:

```sh
uv run nextcloud-borked-android-workaround --verify
uv run nextcloud-borked-android-workaround --download-verify   # settle the unverifiable ones
```

How it works, cheapest path first:

- **Free path (`--verify`)**: hashes each local file *on the phone* (`sha1sum`/`md5sum`, so only digests cross USB) and compares against the server's stored checksum, read from the `oc:checksums` WebDAV property. No download.
- **Fallback (`--download-verify`)**: for files the server has no stored checksum for, downloads the remote copy and hashes it. Authoritative but bandwidth-heavy. Implies `--verify`.

Result buckets: **verified** (hashes match), **MISMATCH** (present but bytes differ, i.e. corruption or truncation), **unverifiable** (server exposes no checksum; needs `--download-verify`).

> Note: the stock Nextcloud Android client does **not** send checksums on instant upload, so existing camera photos come back `unverifiable` on the free path. Use `--download-verify` for those. Files pushed by `nextcloud-upload-missing` *do* carry a checksum (see below), so they verify for free afterward.

### Uploading the missing files

A second entry point, `nextcloud-upload-missing`, reads a compare `--json` payload on **stdin**, pulls each `local_only` file off the phone (`adb exec-out cat`), and `PUT`s it to Nextcloud over WebDAV. It **defaults to a dry run**: it prints the plan and does nothing until you pass `--yes`.

```sh
# Dry run: see exactly what would go up
uv run nextcloud-borked-android-workaround --json \
  | uv run nextcloud-upload-missing --since 20260601 --dest InstantUpload/DCIM/Camera/2026

# Actually upload
uv run nextcloud-borked-android-workaround --json \
  | uv run nextcloud-upload-missing --since 20260601 --dest InstantUpload/DCIM/Camera/2026 --yes
```

- `--since YYYYMMDD`: only upload files whose filename date is on/after this. An essential safety valve when piping a whole-account JSON, since it stops pre-cutover photos (which live on another medium, not Nextcloud) from being pushed up.
- `--dest`: remote folder to upload into; defaults to `NEXTCLOUD_REMOTE_ROOT`.
- `--yes`: perform the upload. Omit it to preview.

Every PUT carries an `OC-Checksum: SHA1:…` header, so the server rejects a corrupted transfer outright and stores the checksum, meaning a later `--verify` confirms these uploads without downloading them.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXTCLOUD_URL` | `https://cloud.example.com` | Server base URL |
| `NEXTCLOUD_USER` | *(required)* | Nextcloud username |
| `NEXTCLOUD_APP_PASSWORD` | *(required)* | App password, not your login password |
| `NEXTCLOUD_REMOTE_ROOT` | *(whole account)* | Restrict the remote side to one folder |
| `PHONE_PHOTO_ROOT` | `/sdcard/DCIM/Camera` | Where photos live on the phone |
| `PHONE_PHOTO_NAME_CONTAINS` | *(all)* | Only compare local files whose name contains this (e.g. `_2026`) |
| `ADB_SERIAL` | *(auto)* | Needed only with multiple devices attached |

The phone stores every year flat in one folder, while Nextcloud's instant-upload splits by year (`InstantUpload/DCIM/Camera/2026`). To compare like-for-like, scope the remote with `NEXTCLOUD_REMOTE_ROOT` **and** the local side with `PHONE_PHOTO_NAME_CONTAINS=_2026` (or pass `--name-contains _2026`). Otherwise every photo from a different year reports as a false "missing".

## Limitations

- Name+size matching, not content hashing, unless you pass `--verify` / `--download-verify`.
- Remote walk is a recursive `PROPFIND Depth: 1`; on a huge account it's many requests. Scope it with `NEXTCLOUD_REMOTE_ROOT`.
- Requires the phone's photo files to be readable over adb (they live on shared storage, so no root needed).
