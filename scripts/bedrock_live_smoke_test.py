#!/usr/bin/env python
"""Manual, opt-in smoke test: invokes a REAL Amazon Bedrock model.

*** This makes a real, billable Amazon Bedrock API call. ***

This script is never run by the automated test suite or CI — it is not a pytest module,
and it additionally refuses to run unless both of the following are true, as an
independent second guard against accidental execution:

  1. The environment variable AWS_MODEL_ROUTER_ENABLE_LIVE_SMOKE_TEST=true is set.
  2. --confirm-cost is passed on the command line.

--model-alias has no default — you must explicitly name a model from the catalogue.

Prompt content is intentionally never logged: the message sent is a fixed, short,
non-sensitive string baked into this script, and only sanitized outcome metadata
(latency, stop reason, usage, estimated cost) is printed by default. The response text
IS printed (not logged to any persisted location) so a human running this interactively
can visually confirm the model behaved sensibly — pass --hide-response to suppress even
that.

Usage:
    export AWS_MODEL_ROUTER_ENABLE_LIVE_SMOKE_TEST=true
    python scripts/bedrock_live_smoke_test.py --model-alias economical-text-primary --confirm-cost

Requires AWS credentials resolvable by boto3's default credential chain (e.g. via
`aws configure`, environment variables, or SSO) with bedrock:InvokeModel /
bedrock:Converse permission for the target model/Region.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import boto3

from adapters.bedrock.bedrock_model_provider import BedrockModelProvider
from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from domain.cost_estimation import DefaultCostEstimator
from domain.enums import Role
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest

_ENV_FLAG = "AWS_MODEL_ROUTER_ENABLE_LIVE_SMOKE_TEST"
_FIXED_TEST_MESSAGE = (
    "Reply with a single short sentence confirming you received this test message."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model-alias",
        required=True,
        help="Model alias from the catalogue to invoke (required — no default)",
    )
    parser.add_argument(
        "--policies-dir",
        type=Path,
        default=Path("policies"),
        help="Directory containing model_catalogue.yaml",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS Region to invoke Bedrock in")
    parser.add_argument(
        "--confirm-cost",
        action="store_true",
        help="Required: acknowledges this makes a real, billable Bedrock call",
    )
    parser.add_argument(
        "--hide-response",
        action="store_true",
        help="Suppress printing the model's response text",
    )
    args = parser.parse_args(argv)

    if os.environ.get(_ENV_FLAG) != "true":
        print(
            f"Refusing to run: set {_ENV_FLAG}=true to enable this live smoke test.",
            file=sys.stderr,
        )
        return 1

    if not args.confirm_cost:
        print(
            "*** This makes a REAL Amazon Bedrock invocation and WILL incur AWS cost. ***",
            file=sys.stderr,
        )
        print("Re-run with --confirm-cost once you accept this.", file=sys.stderr)
        return 1

    catalogue = LocalFileModelCatalogue(args.policies_dir / "model_catalogue.yaml")
    model = catalogue.get_by_alias(args.model_alias)
    if model is None:
        print(f"Unknown model alias: {args.model_alias!r}", file=sys.stderr)
        return 1

    client = boto3.client("bedrock-runtime", region_name=args.region)
    provider = BedrockModelProvider(client=client, model_catalogue=catalogue)

    request = ProviderRequest(
        model_alias=args.model_alias,
        messages=(Message(role=Role.USER, content=_FIXED_TEST_MESSAGE),),
        max_output_tokens=50,
    )

    print(
        f"Invoking model_alias={args.model_alias!r} in region={args.region!r} ...", file=sys.stderr
    )
    start = time.monotonic()
    try:
        response = provider.invoke(request)
    except ProviderError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        print(
            f"FAILED after {elapsed_ms:.0f}ms — category={exc.category.value}: {exc}",
            file=sys.stderr,
        )
        return 1
    elapsed_ms = (time.monotonic() - start) * 1000

    estimated_cost = DefaultCostEstimator().estimate(response.usage, model.pricing)

    print(f"stop_reason={response.stop_reason.value}")
    print(f"usage={response.usage.model_dump()}")
    print(f"estimated_cost_usd={estimated_cost.amount_usd} (estimate only — not billed cost)")
    print(f"latency_ms={elapsed_ms:.0f}")
    if not args.hide_response:
        print(f"response_text={response.message.content!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
