from collections import defaultdict

from ..constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from ..constants import CENTRAL_INFRA_REPO_NAME
from .lib import AwsLogicalWorkload
from .lib import GithubOidcConfig
from .lib import WorkloadName
from .lib import create_oidc_for_single_account_workload


def generate_all_oidc(
    *, workloads_info: dict[WorkloadName, AwsLogicalWorkload]
) -> dict[WorkloadName, list[GithubOidcConfig]]:
    all_oidc: dict[WorkloadName, list[GithubOidcConfig]] = defaultdict(list)

    workload_name = "identity-center"
    identity_center_workload = workloads_info[workload_name]
    all_oidc[workload_name].extend(
        create_oidc_for_single_account_workload(
            aws_account_id=identity_center_workload.prod_accounts[0].id,
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=CENTRAL_INFRA_REPO_NAME,
            role_name_suffix="identity-center",
        )
    )

    return all_oidc
