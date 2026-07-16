from .lib import EcrRepo  # noqa: F401  # used in docstring example
from .lib import ExternalCredConfig


def define_external_creds(external_creds: list[ExternalCredConfig]) -> None:
    """Define IAM users with static credentials for external organizations.

    Example:
    external_creds.append(
        ExternalCredConfig(
            organization="acme-corp",
            description="Acme Corp Jenkins CI — pulls images for on-prem deployment pipeline",
            ecr_repos=[
                EcrRepo(name="orchestrator-health-app/backend"),
            ],
        )
    )
    """
