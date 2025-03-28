from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import WorkloadName

from .lib import GithubOidcConfig


def generate_oidc(
    *, workloads_info: dict[WorkloadName, AwsLogicalWorkload], all_oidc: dict[WorkloadName, list[GithubOidcConfig]]
) -> None:
    # create OIDC here
    pass
