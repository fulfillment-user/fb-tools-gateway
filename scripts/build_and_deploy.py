#!/usr/bin/env python3
"""
FB Tools Gateway - Build and push Docker images.

This script:
1. Discovers apps/*/source.yaml
2. Clones external repositories when necessary
3. Builds Docker images
4. Pushes Docker images to Artifact Registry

Deployment to GKE is handled separately by GitHub Actions.

Required environment variables:
  REGISTRY
    Example:
    europe-west1-docker.pkg.dev/tourathy-project/prod-images

  IMAGE_TAG
    Docker image tag.
    In GitHub Actions this should normally be github.sha.
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


def build_app(
    slug: str,
    manifest_path: Path,
    workdir: Path,
    registry: str,
    image_tag: str,
) -> str:

    manifest = yaml.safe_load(manifest_path.read_text())

    dockerfile = manifest.get("dockerfile", "Dockerfile")
    context = manifest.get("context", ".")
    repo = manifest.get("repo", "local")

    if repo == "local":
        build_dir = manifest_path.parent

        print(
            f"\n=== {slug}: building from local apps/{slug}/ ===",
            flush=True,
        )

    else:
        ref = manifest.get("ref", "main")
        build_dir = workdir / slug

        print(
            f"\n=== {slug}: cloning {repo}@{ref} ===",
            flush=True,
        )

        run([
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            ref,
            repo,
            str(build_dir),
        ])

    image = f"{registry}/{slug}:{image_tag}"

    print(
        f"=== {slug}: building {image} ===",
        flush=True,
    )

    run([
        "docker",
        "build",
        "-f",
        str(build_dir / dockerfile),
        "-t",
        image,
        str(build_dir / context),
    ])

    print(
        f"=== {slug}: pushing {image} ===",
        flush=True,
    )

    run([
        "docker",
        "push",
        image,
    ])

    return image


def main():

    registry = os.environ.get("REGISTRY")
    image_tag = os.environ.get("IMAGE_TAG")

    if not registry:
        sys.exit(
            "REGISTRY is required. Example: "
            "europe-west1-docker.pkg.dev/"
            "tourathy-project/prod-images"
        )

    if not image_tag:
        sys.exit(
            "IMAGE_TAG is required. "
            "Use the Git commit SHA in CI/CD."
        )

    print(f"\nRegistry: {registry}")
    print(f"Image tag: {image_tag}")

    manifests = sorted(
        APPS_DIR.glob("*/source.yaml")
    )

    if not manifests:
        print(
            "No apps/*/source.yaml found."
        )

    with tempfile.TemporaryDirectory() as tmp:

        workdir = Path(tmp)

        for manifest_path in manifests:

            slug = manifest_path.parent.name

            build_app(
                slug,
                manifest_path,
                workdir,
                registry,
                image_tag,
            )

    # Build auth-service

    print(
        "\n=== building auth-service ===",
        flush=True,
    )

    auth_image = (
        f"{registry}/auth-service:{image_tag}"
    )

    run([
        "docker",
        "build",
        "-t",
        auth_image,
        str(REPO_ROOT / "auth-service"),
    ])

    run([
        "docker",
        "push",
        auth_image,
    ])

    print("\n=== Build and push completed ===")
    print("Deployment to GKE is handled by GitHub Actions.")


if __name__ == "__main__":
    main()
