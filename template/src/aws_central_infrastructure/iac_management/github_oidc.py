from .lib import AwsLogicalWorkload
from .lib import GithubOidcConfig
from .lib import WorkloadName


def generate_oidc(
    *, workloads_info: dict[WorkloadName, AwsLogicalWorkload], all_oidc: dict[WorkloadName, list[GithubOidcConfig]]
) -> None:
    # create OIDC here
    pass
