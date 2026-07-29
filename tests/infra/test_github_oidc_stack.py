"""Template-assertion tests for `GitHubOidcStack` (ADR-025): the OIDC provider trusts
exactly `token.actions.githubusercontent.com`, each per-environment deploy role's trust
policy is scoped to that environment's GitHub Environment `sub` claim, and each role's
own IAM policy grants nothing beyond `sts:AssumeRole` on the three CDK bootstrap roles —
never a broad permission directly.
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from aws_cdk.assertions import Template

pytestmark = pytest.mark.infra


def test_oidc_provider_trusts_github_actions(github_oidc_template: "Template") -> None:
    github_oidc_template.has_resource_properties(
        "Custom::AWSCDKOpenIdConnectProvider",
        {
            "Url": "https://token.actions.githubusercontent.com",
            "ClientIDList": ["sts.amazonaws.com"],
        },
    )


def test_exactly_two_deploy_roles_exist(github_oidc_template: "Template") -> None:
    # AWS::IAM::Role also includes the CDK-managed custom-resource provider's own
    # execution role (created automatically by iam.OpenIdConnectProvider's underlying
    # custom resource, not something this stack defines) — filter to the two roles
    # this stack actually declares.
    template_json = github_oidc_template.to_json()
    deploy_roles = [
        resource
        for resource in template_json["Resources"].values()
        if resource["Type"] == "AWS::IAM::Role"
        and resource["Properties"].get("RoleName", "").startswith("github-actions-deploy-")
    ]
    assert len(deploy_roles) == 2


@pytest.mark.parametrize("env_name", ["dev", "prod"])
def test_deploy_role_trust_policy_scoped_to_its_own_environment(
    github_oidc_template: "Template", env_name: str
) -> None:
    github_oidc_template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": f"github-actions-deploy-{env_name}",
            "AssumeRolePolicyDocument": {
                "Statement": [
                    {
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Effect": "Allow",
                        "Condition": {
                            "StringEquals": {
                                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                            },
                            "StringLike": {
                                "token.actions.githubusercontent.com:sub": (
                                    f"repo:lapczyna/aws-model-router:environment:{env_name}"
                                )
                            },
                        },
                    }
                ]
            },
        },
    )


def test_dev_role_cannot_be_assumed_via_prod_environment_claim(
    github_oidc_template: "Template",
) -> None:
    template_json = github_oidc_template.to_json()
    dev_role = next(
        resource
        for resource in template_json["Resources"].values()
        if resource["Type"] == "AWS::IAM::Role"
        and resource["Properties"].get("RoleName") == "github-actions-deploy-dev"
    )
    sub_claim = dev_role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"][
        "StringLike"
    ]["token.actions.githubusercontent.com:sub"]
    assert sub_claim == "repo:lapczyna/aws-model-router:environment:dev"
    assert "prod" not in sub_claim


def test_deploy_roles_only_grant_assume_role_on_bootstrap_roles(
    github_oidc_template: "Template",
) -> None:
    template_json = github_oidc_template.to_json()
    policies = [
        resource
        for resource in template_json["Resources"].values()
        if resource["Type"] == "AWS::IAM::Policy"
    ]
    assert len(policies) == 2
    for policy in policies:
        statements = policy["Properties"]["PolicyDocument"]["Statement"]
        assert len(statements) == 1
        statement = statements[0]
        assert statement["Action"] == "sts:AssumeRole"
        assert statement["Effect"] == "Allow"
        resources = statement["Resource"]
        assert len(resources) == 3
        for resource_arn in resources:
            assert resource_arn.startswith("arn:aws:iam::123456789012:role/cdk-hnb659fds-")
            assert resource_arn != "*"


def test_no_deploy_role_has_permissions_beyond_assume_role(
    github_oidc_template: "Template",
) -> None:
    template_json = github_oidc_template.to_json()
    for resource in template_json["Resources"].values():
        if resource["Type"] != "AWS::IAM::Policy":
            continue
        for statement in resource["Properties"]["PolicyDocument"]["Statement"]:
            actions = statement["Action"]
            actions = actions if isinstance(actions, list) else [actions]
            assert actions == ["sts:AssumeRole"]
