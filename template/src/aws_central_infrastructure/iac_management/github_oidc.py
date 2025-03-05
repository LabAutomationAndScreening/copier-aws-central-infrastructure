from collections import defaultdict

from .lib import AwsLogicalWorkload
from .lib import GithubOidcConfig
from .lib import WorkloadName
from .lib import create_application_oidc_if_needed
from .lib import create_oidc_for_single_account_workload
from .lib.constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from .lib.constants import CENTRAL_INFRA_REPO_NAME


def generate_all_oidc(
    *, workloads_info: dict[WorkloadName, AwsLogicalWorkload]
) -> dict[WorkloadName, list[GithubOidcConfig]]:
    all_oidc: dict[WorkloadName, list[GithubOidcConfig]] = defaultdict(list)
    create_application_oidc_if_needed(all_oidc=all_oidc, workloads_info=workloads_info)

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
