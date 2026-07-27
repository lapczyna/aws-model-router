"""Lambda deployment package bundling (ADR-017).

Uses the *stable* `aws_cdk.aws_lambda.Function` + `Code.from_asset(..., bundling=...)`
API, not the experimental `aws_lambda_python_alpha.PythonFunction` construct (its
package name says "alpha" — the project's policy is to avoid experimental CDK
constructs unless their value is substantial and the risk is documented; a stable
`Code.from_asset` with a custom bundling command provides the same outcome without it).

Bundling tries a local, Docker-free path first: `pip install --platform
manylinux2014_x86_64 --only-binary=:all: --python-version 3.12`, which downloads
Linux-compatible wheels for every dependency — including compiled ones like
`pydantic-core` — regardless of the host OS running `cdk synth`/`cdk deploy`. This is
what lets `cdk synth` succeed on a Windows machine with no Docker daemon running. If
local bundling fails for any reason (e.g. a future dependency ships no manylinux wheel),
CDK automatically falls back to its standard Docker-based bundling using the matching
`public.ecr.aws/sam/build-python3.12` image — that Docker fallback path is implemented
here but was not itself exercised in this project's development environment (no local
Docker daemon), only the local pip-download path was.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import jsii
from aws_cdk import BundlingOptions, DockerImage, ILocalBundling

_LAMBDA_PYTHON_VERSION = "3.12"
_LAMBDA_PLATFORM = "manylinux2014_x86_64"
_SOURCE_PACKAGES = ("domain", "application", "adapters", "handlers", "shared")


@jsii.implements(ILocalBundling)
class _LocalPipBundling:
    """Installs Lambda dependencies and copies source/config, without Docker."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def try_bundle(self, output_dir: str, options: Any = None) -> bool:
        requirements_path = self._repo_root / "infrastructure" / "lambda_requirements.txt"
        try:
            subprocess.run(
                [
                    "pip",
                    "install",
                    "--platform",
                    _LAMBDA_PLATFORM,
                    "--implementation",
                    "cp",
                    "--python-version",
                    _LAMBDA_PYTHON_VERSION,
                    "--only-binary=:all:",
                    "--target",
                    output_dir,
                    "-r",
                    str(requirements_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

        output_path = Path(output_dir)
        for package in _SOURCE_PACKAGES:
            shutil.copytree(
                self._repo_root / "src" / package, output_path / package, dirs_exist_ok=True
            )
        shutil.copytree(self._repo_root / "policies", output_path / "policies", dirs_exist_ok=True)
        return True


def lambda_code_bundling_options(repo_root: Path) -> BundlingOptions:
    """`BundlingOptions` for the Lambda asset: local pip-download first, Docker fallback."""
    copy_commands = " && ".join(
        f"cp -r /asset-input/src/{package} /asset-output/{package}" for package in _SOURCE_PACKAGES
    )
    docker_command = (
        "pip install -r /asset-input/infrastructure/lambda_requirements.txt -t /asset-output "
        f"&& {copy_commands} "
        "&& cp -r /asset-input/policies /asset-output/policies"
    )
    return BundlingOptions(
        image=DockerImage.from_registry(f"public.ecr.aws/sam/build-python{_LAMBDA_PYTHON_VERSION}"),
        command=["bash", "-c", docker_command],
        # The generated ILocalBundling stub declares try_bundle as keyword-only
        # (`*, image, command, ...`), but the actual jsii runtime callback invokes it
        # positionally (`try_bundle(output_dir, options)`) — confirmed empirically via
        # a real `cdk synth` (a keyword-only signature raises "takes 2 positional
        # arguments but 3 were given" at bundle time). Matching the verified runtime
        # behavior over the stub is deliberate here.
        local=_LocalPipBundling(repo_root),  # type: ignore[arg-type]
    )
