#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from rulesgen.engine import GeneratorConfig, run_generation

DEFAULT_TARGETS = ("surge", "mihomo", "shadowrocket", "loon", "sing-box")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate multi-client rules from platform-neutral source rules")
    parser.add_argument(
        "--source-root",
        required=True,
        help="Source directory containing *.conf and *.py rule definitions",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Output directory for generated rule artifacts",
    )
    parser.add_argument(
        "--ruleset-baseline",
        required=True,
        help="Baseline target name stored in manifest metadata",
    )
    parser.add_argument(
        "--targets",
        default=",".join(DEFAULT_TARGETS),
        help="Comma-separated target list, defaults to all targets",
    )
    parser.add_argument(
        "--github-repo",
        required=True,
        help="GitHub repository in owner/name format for README external links",
    )
    parser.add_argument(
        "--publish-branch",
        required=True,
        help="Publish branch name used in README external links",
    )
    parser.add_argument(
        "--skip-sing-box-compile",
        action="store_true",
        help="Skip sing-box .srs compilation (keeps .json only)",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> GeneratorConfig:
    targets = tuple(part.strip() for part in args.targets.split(",") if part.strip())
    if not targets:
        raise RuntimeError("At least one target must be specified via --targets")

    source_root = Path(args.source_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    cache_root = source_root.parent / "cache"

    if not source_root.exists() or not source_root.is_dir():
        raise RuntimeError(f"--source-root does not exist or is not a directory: {source_root}")

    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return GeneratorConfig(
        source_root=source_root,
        output_root=output_root,
        cache_root=cache_root,
        ruleset_baseline=args.ruleset_baseline,
        targets=targets,
        github_repo=args.github_repo,
        publish_branch=args.publish_branch,
        compile_srs=not args.skip_sing_box_compile,
        generated_at=generated_at,
    )


def main() -> None:
    config = build_config(parse_args())
    run_generation(config)


if __name__ == "__main__":
    main()
