#!/usr/bin/env python3
"""
FB Tools Gateway -- the one script devops wires into a pipeline that runs on
every push to THIS repo. It discovers every apps/*/source.yaml, clones that
app's own repo at the pinned ref, builds its Dockerfile, tags and pushes the
image, then (unless SKIP_DEPLOY=1) redeploys the whole stack.

Onboarding a brand new tool never touches this script or needs a new
pipeline -- it's just a new apps/<slug>/source.yaml (see docs/RUNBOOK.md).
That's the entire point of routing every app through one manifest instead of
giving each tool its own build pipeline.

Requires on whatever machine runs this: git, docker, python3 with PyYAML,
and the container already authenticated to REGISTRY (docker login /
gcloud auth configure-docker) before this runs -- this script doesn't handle
registry auth itself, that's environment setup, not build logic.

Env vars:
  REGISTRY     required. e.g. europe-west1-docker.pkg.dev/PROJECT/fb-tools
  SKIP_DEPLOY  set to "1" to only build+push images, skipping the final
               `docker compose up -d` -- use this if your pipeline's build
               step runs somewhere other than the actual deploy box (e.g. a
               CI runner) and you redeploy through your own existing
               mechanism afterward.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = REPO_ROOT / "apps"


def run(cmd, **kwargs):
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def build_app(slug: str, manifest_path: Path, workdir: Path, registry: str) -> str:
    manifest = yaml.safe_load(manifest_path.read_text())
    repo = manifest["repo"]
    ref = manifest.get("ref", "main")
    dockerfile = manifest.get("dockerfile", "Dockerfile")
    context = manifest.get("context", ".")

    clone_dir = workdir / slug
    print(f"\n=== {slug}: cloning {repo}@{ref} ===", flush=True)
    run(["git", "clone", "--depth", "1", "--branch", ref, repo, str(clone_dir)])

    image = f"{registry}/{slug}:latest"
    print(f"=== {slug}: building {image} ===", flush=True)
    run(["docker", "build", "-f", str(clone_dir / dockerfile), "-t", image,
         str(clone_dir / context)])
    run(["docker", "push", image])
    return image


def main():
    registry = os.environ.get("REGISTRY")
    if not registry:
        sys.exit("Set REGISTRY, e.g. europe-west1-docker.pkg.dev/PROJECT/fb-tools")

    manifests = sorted(APPS_DIR.glob("*/source.yaml"))
    if not manifests:
        print("No apps/*/source.yaml found -- nothing to build from a manifest.")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for manifest_path in manifests:
            slug = manifest_path.parent.name
            build_app(slug, manifest_path, workdir, registry)

    print("\n=== building auth-service (this repo's own image) ===", flush=True)
    auth_image = f"{registry}/auth-service:latest"
    run(["docker", "build", "-t", auth_image, str(REPO_ROOT / "auth-service")])
    run(["docker", "push", auth_image])

    if os.environ.get("SKIP_DEPLOY") == "1":
        print("\nSKIP_DEPLOY=1 set -- built and pushed only, not redeploying.")
        return

    print("\n=== redeploying (docker compose, on this machine) ===", flush=True)
    env = {**os.environ, "REGISTRY": registry}
    run(["docker", "compose", "pull"], cwd=REPO_ROOT, env=env)
    run(["docker", "compose", "up", "-d"], cwd=REPO_ROOT, env=env)


if __name__ == "__main__":
    main()
