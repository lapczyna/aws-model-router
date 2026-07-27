"""CDK stacks. A single `ModelRouterStack` per environment (dev/prod) — see
`docs/adr/0016-single-shared-lambda-handler.md` for why this project doesn't split
API/Lambda/storage into independently-deployed stacks at this size.
"""
