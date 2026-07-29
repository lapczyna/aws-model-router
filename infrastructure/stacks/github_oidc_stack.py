"""GitHub Actions OIDC trust + per-environment deploy roles (ADR-025).

Deployed **manually, once, by a human with real AWS credentials** — this is the
chicken-and-egg root of trust that lets `deploy.yml` authenticate to AWS at all. It is
never deployed by the GitHub Actions workflows it enables (`cdk deploy GitHubOidc`, not
part of any automated pipeline). See `docs/operations/ci-cd.md` for the bootstrap steps.

Each deploy role is granted only `sts:AssumeRole` on the three roles `cdk bootstrap`
itself already created in this account/Region — never broad permissions directly. CDK's
actual resource-creation permissions live on those bootstrap roles (customizable via
`cdk bootstrap --cloudformation-execution-policies`, a separate, well-documented CDK
concern this stack does not re-implement). This keeps the GitHub-trusted role's own
policy tiny and independent of whatever this project's stacks happen to provision.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

_CDK_QUALIFIER = "hnb659fds"  # the default CDK bootstrap qualifier (cdk.json's default)
_BOOTSTRAP_ROLE_KINDS = ("deploy-role", "file-publishing-role", "lookup-role")
_ENVIRONMENTS = ("dev", "prod")


class GitHubOidcStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_org: str,
        github_repo: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOidcProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        self.deploy_roles: dict[str, iam.Role] = {}
        for env_name in _ENVIRONMENTS:
            role = iam.Role(
                self,
                f"DeployRole{env_name.capitalize()}",
                role_name=f"github-actions-deploy-{env_name}",
                description=(
                    f"Assumed by GitHub Actions (environment={env_name}) via OIDC to "
                    f"deploy ModelRouter-{env_name} through the CDK bootstrap roles"
                ),
                assumed_by=iam.WebIdentityPrincipal(
                    provider.open_id_connect_provider_arn,
                    conditions={
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                        },
                        "StringLike": {
                            "token.actions.githubusercontent.com:sub": (
                                f"repo:{github_org}/{github_repo}:environment:{env_name}"
                            )
                        },
                    },
                ),
                max_session_duration=Duration.hours(1),
            )
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["sts:AssumeRole"],
                    resources=[
                        (
                            f"arn:aws:iam::{self.account}:role/"
                            f"cdk-{_CDK_QUALIFIER}-{role_kind}-{self.account}-{self.region}"
                        )
                        for role_kind in _BOOTSTRAP_ROLE_KINDS
                    ],
                )
            )
            self.deploy_roles[env_name] = role
