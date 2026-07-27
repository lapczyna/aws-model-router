#!/usr/bin/env python
"""CDK app entry point (ADR-004: AWS CDK v2 with Python).

Usage:
    cdk synth -c env=dev
    cdk deploy -c env=dev
    cdk deploy -c env=prod
    cdk destroy -c env=dev   # see docs/operations/deployment-and-teardown.md first —
                             # prod resources use RemovalPolicy.RETAIN (ADR-018)
"""

import os

import aws_cdk as cdk

from config import get_environment_config
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

cdk.Tags.of(stack).add("Project", "aws-model-router")
cdk.Tags.of(stack).add("Environment", environment_config.env_name)
cdk.Tags.of(stack).add("ManagedBy", "cdk")

app.synth()
