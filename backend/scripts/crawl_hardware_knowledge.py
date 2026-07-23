from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.knowledge.config import CrawlerSettings
from app.knowledge.http import create_managed_client
from app.knowledge.pipeline import HardwareKnowledgePipeline, ProviderSet
from app.knowledge.providers.apify import ApifyProvider
from app.knowledge.providers.brightdata import BrightDataProvider
from app.knowledge.providers.ecb import EcbProvider
from app.knowledge.providers.firecrawl import FirecrawlProvider
from app.knowledge.providers.serpapi import SerpApiProvider
from app.knowledge.providers.zyte import ZyteProvider
from app.knowledge.validation import REQUIRED_SPECS


DEFAULT_OUTPUT = BACKEND_DIR / "data" / "knowledge" / "hardware"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect reviewable hardware knowledge via managed APIs."
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=sorted(REQUIRED_SPECS),
        default=sorted(REQUIRED_SPECS),
    )
    parser.add_argument("--per-category", type=int, default=1)
    parser.add_argument(
        "--minimum-per-category",
        type=int,
        default=None,
        help="Minimum cumulative catalog records required in each category.",
    )
    parser.add_argument(
        "--max-candidates-per-category",
        type=int,
        default=40,
        help="Maximum managed-search candidates inspected for one category.",
    )
    parser.add_argument("--market", default="US")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=BACKEND_DIR.parent / ".env",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    return parser


def _readiness(settings: CrawlerSettings) -> dict[str, str]:
    return {
        provider: (
            "ready" if settings.provider_ready(provider) else "not_ready"
        )
        for provider in [
            "serpapi",
            "firecrawl",
            "zyte",
            "brightdata",
            "apify",
            "ecb",
        ]
    }


def main(
    argv: Sequence[str] | None = None,
    settings_override: CrawlerSettings | None = None,
) -> int:
    args = _parser().parse_args(argv)
    settings = settings_override or CrawlerSettings.from_env(args.env_file)
    readiness = _readiness(settings)
    if args.dry_run:
        print("target page requests: managed providers only")
        for provider, status in readiness.items():
            print(f"{provider}: {status}")
        return 0
    if readiness["serpapi"] != "ready":
        print("serpapi: not_ready")
        return 2

    client = create_managed_client()
    providers = ProviderSet(
        serpapi=SerpApiProvider(settings.serpapi_key, client),
        firecrawl=(
            FirecrawlProvider(settings.firecrawl_api_key, client)
            if settings.provider_ready("firecrawl")
            else None
        ),
        zyte=(
            ZyteProvider(settings.zyte_api_key, client)
            if settings.provider_ready("zyte")
            else None
        ),
        brightdata=(
            BrightDataProvider(
                settings.brightdata_api_token,
                settings.brightdata_zone,
                client,
            )
            if settings.provider_ready("brightdata")
            else None
        ),
        apify=(
            ApifyProvider(
                settings.apify_api_token,
                settings.apify_actor_id,
                client,
            )
            if settings.provider_ready("apify")
            else None
        ),
        ecb=EcbProvider(client),
    )
    try:
        manifest = HardwareKnowledgePipeline(
            providers=providers,
            output_root=args.output,
            secrets=settings.secrets(),
        ).run(
            categories=args.categories,
            per_category=max(1, args.per_category),
            market=args.market,
            minimum_per_category=(
                max(1, args.minimum_per_category)
                if args.minimum_per_category is not None
                else None
            ),
            max_candidates_per_category=max(
                1,
                args.max_candidates_per_category,
            ),
        )
    finally:
        client.close()
    print(f"batch_id={manifest['batch_id']}")
    print(f"accepted={manifest['accepted_count']}")
    print(f"rejected={manifest['rejected_count']}")
    print(f"manifest={args.output / 'manifests' / (manifest['batch_id'] + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
