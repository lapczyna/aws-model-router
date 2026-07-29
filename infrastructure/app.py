#!/usr/bin/env python
"""CDK app entry point (ADR-004: AWS CDK v2 with Python).

Usage:
    cdk synth -c env=dev
    cdk deploy -c env=dev
    cdk deploy -c env=prod
    cdk destroy -c env=dev   # see docs/operations/deployment-and-teardown.md first —
                             # prod resources use RemovalPolicy.RETAIN (ADR-018)

    cdk deploy GitHubOidc    # one-time, manual, human-run bootstrap (ADR-025) —
                             # never part of the automated CI/CD pipeline itself; see
                             # docs/operations/ci-cd.md

    CDK_NAG_ENABLED=true cdk synth -c env=dev   # IaC security scan (ADR-027); an
                             # un-suppressed Error-level finding fails synth non-zero —
                             # this is what the PR workflow runs, not a separate tool
"""

import os

import aws_cdk as cdk

from config import get_environment_config
from stacks.github_oidc_stack import GitHubOidcStack
from stacks.model_router_stack import ModelRouterStack

app = cdk.App()

env_name = app.node.try_get_context("env") or "dev"
environment_config = get_environment_config(env_name)

aws_env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

stack = ModelRouterStack(
    app,
    f"ModelRouter-{environment_config.env_name}",
    environment_config=environment_config,
    env=aws_env,
    description="aws-model-router: serverless, policy-driven model routing platform",
)

# AWS::CloudWatch::Dashboard is excluded: CloudFormation does not yet support a Tags
# property on this resource type (as of this writing — the underlying tagging *API*
# exists, but CloudFormation's own resource schema doesn't accept it yet), confirmed by
# cfn-lint (E3002) catching it in the PR workflow's IaC scan. Tagging the dashboard via
# CloudFormation would make `cdk deploy` fail outright; every other resource is
# unaffected.
_TAG_EXCLUDED_RESOURCE_TYPES = ["AWS::CloudWatch::Dashboard"]

cdk.Tags.of(stack).add(
    "Project", "aws-model-router", exclude_resource_types=_TAG_EXCLUDED_RESOURCE_TYPES
)
cdk.Tags.of(stack).add(
    "Environment",
    environment_config.env_name,
    exclude_resource_types=_TAG_EXCLUDED_RESOURCE_TYPES,
)
cdk.Tags.of(stack).add("ManagedBy", "cdk", exclude_resource_types=_TAG_EXCLUDED_RESOURCE_TYPES)

github_oidc_stack = GitHubOidcStack(
    app,
    "GitHubOidc",
    github_org=os.environ.get("GITHUB_OIDC_ORG", "lapczyna"),
    github_repo=os.environ.get("GITHUB_OIDC_REPO", "aws-model-router"),
    env=aws_env,
    description="GitHub Actions OIDC trust + per-environment CDK deploy roles (ADR-025)",
)
cdk.Tags.of(github_oidc_stack).add("Project", "aws-model-router")
cdk.Tags.of(github_oidc_stack).add("ManagedBy", "cdk")

if os.environ.get("CDK_NAG_ENABLED") == "true":
    from cdk_nag import AwsSolutionsChecks

    cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))

app.synth()
