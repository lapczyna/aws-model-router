# ADR-017: Lambda packaging without experimental CDK constructs

## Status
Accepted

## Context
The project's stated policy (ADR-004) is to avoid experimental CDK constructs unless
their value is substantial and the stability risk is documented. The obvious, easiest
way to package a Python Lambda with pip dependencies is
`aws_lambda_python_alpha.PythonFunction` — but that module is explicitly published as
"alpha" (its PyPI/npm package name says so), meaning its API can change in a breaking
way between minor `aws-cdk-lib` releases without the normal v2 stability guarantee.

The stable alternative, `aws_cdk.aws_lambda.Function` with
`Code.from_asset(path, bundling=...)`, needs an explicit bundling strategy: by default
it shells out to Docker to install dependencies inside a Lambda-like container. On the
maintainer's Windows development machine, Docker Desktop is not always running, and
requiring it for every `cdk synth`/`cdk deploy` would be a real friction cost for local
development.

## Decision
Use the stable `Function` + `Code.from_asset(..., bundling=...)` API (never the alpha
`PythonFunction`). Bundling (`infrastructure/bundling.py`) tries a **local, Docker-free
path first**: `pip install --platform manylinux2014_x86_64 --implementation cp
--python-version 3.12 --only-binary=:all: --target <output> -r
infrastructure/lambda_requirements.txt`. Pip supports downloading pre-built wheels for a
*different* platform than the host running pip — this downloads genuine Linux
(manylinux) wheels, including compiled ones like `pydantic-core`
(`_pydantic_core.cpython-312-x86_64-linux-gnu.so`), even when `pip` itself runs on
Windows. This was verified directly: `cdk synth` succeeds end-to-end on this project's
Windows development machine with the Docker daemon not running.

If local bundling fails for any reason (implemented as CDK's `ILocalBundling` interface,
returning `False` on failure), CDK automatically falls back to its standard Docker-based
bundling against the `public.ecr.aws/sam/build-python3.12` image — implemented here, but
not itself exercised in this project's development environment (no local Docker daemon
available to verify it against).

The bundled Lambda package includes: the five top-level source packages (`domain`,
`application`, `adapters`, `handlers`, `shared`, copied directly — no wrapping `src/`
prefix, matching how they're already installed as independent top-level packages,
ADR from Phase 1), the bundled `policies/` configuration, and the pinned dependencies in
`infrastructure/lambda_requirements.txt` (kept manually in sync with `pyproject.toml`'s
runtime `dependencies` — boto3 is bundled explicitly rather than relying on the Lambda
runtime's built-in, unpredictable-version copy, since the Bedrock Converse API needs a
minimum botocore version).

## Consequences
* No dependency on an alpha-quality CDK module whose API could change unexpectedly.
* `cdk synth`/`cdk deploy` work without Docker Desktop running, removing a real local
  development friction point — verified, not just asserted.
* `infrastructure/lambda_requirements.txt` is a second place dependency versions must be
  kept consistent with `pyproject.toml` — a manual sync point, documented with a comment
  in both files pointing at each other.
* The `ILocalBundling.try_bundle()` callback's actual jsii runtime calling convention
  (positional `(output_dir, options)`) does not match its own generated Python stub
  (keyword-only `image=..., command=..., ...`) in the `aws-cdk-lib` version this project
  uses — confirmed empirically (a keyword-only implementation raised a `TypeError` at
  real bundle time). The implementation matches the verified runtime behavior; a
  `type: ignore` at the call site documents the discrepancy and where it was confirmed.
* If a future dependency has no manylinux wheel at all (pure-Python-incompatible,
  platform-specific with no prebuilt Linux wheel), local bundling fails cleanly and CDK's
  Docker fallback becomes load-bearing — at that point, a contributor without Docker
  running would be blocked on that specific dependency addition until Docker is
  available, a known and accepted limitation of this approach.

## Alternatives considered
* **`aws_lambda_python_alpha.PythonFunction`** — rejected per ADR-004's policy: alpha
  API stability risk with no documented, substantial value over the stable alternative
  this ADR implements.
* **Docker-only bundling (CDK's default)** — rejected as the sole/primary path: works,
  but forces every contributor to keep Docker Desktop running for `cdk synth`, adding
  friction this project's own development process doesn't otherwise require.
* **Pre-built deployment zip committed to the repo or built by a separate script outside
  CDK** — rejected: decouples the build from `cdk synth`/`cdk deploy`'s normal asset
  lifecycle (staleness risk, no automatic asset-hash-based change detection), trading a
  one-time bundling-strategy investment for an ongoing manual build-step discipline.
