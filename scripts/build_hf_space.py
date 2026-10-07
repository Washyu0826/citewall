#!/usr/bin/env python
"""Assemble — and optionally upload — the Hugging Face Space for the public demo.

    python scripts/build_hf_space.py --out build/hf-space
    python scripts/build_hf_space.py --out build/hf-space --upload OWNER/SPACE   # needs HF_TOKEN

The Space is a Docker Space built from docker/demo.Dockerfile (copied to the
Space root as ``Dockerfile``) and holds only what that image needs. Files come
from git (``git archive``), never from the working tree, so a local .env,
node_modules or data/*.db cannot reach the public Space (CLAUDE.md: public
snapshots via git archive).

``DEMO_VERSION`` (the commit) is served at /version.txt, so a deploy can wait
for the NEW build instead of smoke-testing the old one still running.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# What docker/demo.Dockerfile COPYs, nothing more.
PATHS = [
    "LICENSE",
    "NOTICE",
    "frontend",
    "backend",
    "data/case_registry.json",
    "data/tenant_dicts",
    "data/calendars",
    "docker/seed-data.sh",
    "docker/demo",
]
# Inside those paths: not needed by the build (e2e suites, screenshot baselines).
EXCLUDE_PREFIXES = ("frontend/tests/",)

SPACE_README = """\
---
title: Patent OA Assistant
emoji: 📄
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Privacy-first assistant for patent OA responses (demo)
---

# Patent OA Assistant — public demo

A privacy-first assistant that helps a patent attorney answer an Office Action:
it reads the OA, finds the cited prior art, drafts a response sentence by
sentence with citations that must come from the retrieved passages, and leaves
every sentence to the attorney to accept, edit or exclude before a signed-off
export.

**This demo runs in mock mode:** synthetic cases, no language model is called,
and nothing is kept — a restart resets everything. Click a demo user on the
login page (Alice is the attorney).

Source, architecture and design decisions:
https://github.com/Washyu0826/patent-oa-assistant

Not legal advice. Built from commit `{version}`.
"""


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def assemble(out: Path, ref: str) -> str:
    version = git("rev-parse", "--short=12", ref).decode().strip()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    archive = git("archive", "--format=tar", ref, "--", *PATHS)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = [
            m
            for m in tar.getmembers()
            if not (m.name + "/").startswith(EXCLUDE_PREFIXES)
        ]
        tar.extractall(out, members=members, filter="data")

    # From git too, like everything else: the Space must match the commit.
    dockerfile = git("show", f"{ref}:docker/demo.Dockerfile").decode("utf-8")
    dockerfile += (
        "\n# Added by scripts/build_hf_space.py: the commit this Space was built\n"
        "# from, so a deploy can tell the new build from the old one.\n"
        "COPY DEMO_VERSION /usr/share/nginx/html/version.txt\n"
    )
    (out / "Dockerfile").write_text(dockerfile, encoding="utf-8", newline="\n")
    (out / ".dockerignore").write_bytes(git("show", f"{ref}:docker/demo.Dockerfile.dockerignore"))
    (out / "DEMO_VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")
    (out / "README.md").write_text(
        SPACE_README.format(version=version), encoding="utf-8", newline="\n"
    )
    return version


def upload(out: Path, space_id: str, version: str) -> None:
    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("HF_TOKEN is not set")
    api = HfApi(token=token)
    api.create_repo(space_id, repo_type="space", space_sdk="docker", exist_ok=True)
    # Mirror: files that are no longer part of the Space are removed.
    api.upload_folder(
        repo_id=space_id,
        repo_type="space",
        folder_path=out,
        commit_message=f"Deploy {version}",
        delete_patterns="*",
    )


def space_url(space_id: str) -> str:
    owner, name = space_id.split("/", 1)
    host = f"{owner}-{name}".lower().replace("_", "-").replace(".", "-")
    return f"https://{host}.hf.space"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--upload", metavar="OWNER/SPACE")
    # For the deploy workflow: the app URL, without pasting the Space id into
    # Python source on a command line.
    ap.add_argument("--print-url", metavar="OWNER/SPACE")
    args = ap.parse_args()

    if args.print_url:
        print(space_url(args.print_url))
        return 0
    if args.out is None:
        ap.error("--out is required")
    version = assemble(args.out, args.ref)
    files = sum(1 for p in args.out.rglob("*") if p.is_file())
    print(f"assembled {files} files for {version} in {args.out}")
    if args.upload:
        upload(args.out, args.upload, version)
        print(f"uploaded to https://huggingface.co/spaces/{args.upload}")
        print(f"app: {space_url(args.upload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
