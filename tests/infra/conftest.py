"""Fixtures for CDK template-assertion tests (`pytest.mark.infra`).

These tests are excluded from the default `pytest` run (`pyproject.toml`:
`addopts = ... -m "not infra"`) because a real `cdk synth` — even with the Docker-free
local bundling path (`infrastructure/bundling.py`) — costs tens of seconds (a `pip
install` of the Lambda runtime dependencies plus the `aws_cdk`/jsii import itself) versus
low single digits of seconds for the rest of the suite combined. Run them explicitly with
`pytest -m infra` (see `docs/operations/deployment-and-teardown.md`).

To keep that cost paid exactly once regardless of how many assertions run against it,
`synthesized_stacks` is session-scoped and synthesizes both the `dev` and `prod` stacks
from a single `cdk.App`/`app.synth()` call — CDK's asset staging cache then bundles the
(identical, since Lambda source doesn't vary per environment) Lambda code asset only
once, not twice.

All `aws_cdk`/`stacks.*` imports are deferred to inside the fixture body (not at module
import time) so that collecting this file under the default `-m "not infra"` run never
pays the `aws_cdk` import cost — only actually *running* an infra test does.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from aws_cdk.assertions import Template

    from config import EnvironmentConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INFRA_DIR = _REPO_ROOT / "infrastructure"
_FIXED_ACCOUNT = "123456789012"
_FIXED_REGION = "us-east-1"


@dataclass(frozen=True)
class SynthesizedStack:
    config: "EnvironmentConfig"
    template: "Template"


@pytest.fixture(scope="session")
def synthesized_stacks() -> dict[str, SynthesizedStack]:
    if str(_INFRA_DIR) not in sys.path:
        sys.path.insert(0, str(_INFRA_DIR))

    import aws_cdk as cdk
    from aws_cdk.assertions import Template as _Template

    from config import get_environment_config
    from stacks.model_router_stack import ModelRouterStack

    app = cdk.App()
    env = cdk.Environment(account=_FIXED_ACCOUNT, region=_FIXED_REGION)

    raw_stacks = {}
    for env_name in ("dev", "prod"):
        environment_config = get_environment_config(env_name)
        stack = ModelRouterStack(
            app,
            f"ModelRouter-{env_name}",
            environment_config=environment_config,
            env=env,
        )
        # Mirrors infrastructure/app.py's tagging, which happens at the app entry
        # point rather than inside ModelRouterStack itself.
        cdk.Tags.of(stack).add("Project", "aws-model-router")
        cdk.Tags.of(stack).add("Environment", environment_config.env_name)
        cdk.Tags.of(stack).add("ManagedBy", "cdk")
        raw_stacks[env_name] = stack

    app.synth()

    return {
        env_name: SynthesizedStack(
            config=get_environment_config(env_name), template=_Template.from_stack(stack)
        )
        for env_name, stack in raw_stacks.items()
    }


@pytest.fixture(scope="session")
def dev_stack(synthesized_stacks: dict[str, SynthesizedStack]) -> SynthesizedStack:
    return synthesized_stacks["dev"]


@pytest.fixture(scope="session")
def prod_stack(synthesized_stacks: dict[str, SynthesizedStack]) -> SynthesizedStack:
    return synthesized_stacks["prod"]
