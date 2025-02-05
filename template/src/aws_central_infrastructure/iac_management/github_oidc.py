from collections import defaultdict

from ..constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from ..constants import CENTRAL_INFRA_REPO_NAME
from .github_oidc_lib import GithubOidcConfig
from .github_oidc_lib import WorkloadName
from .github_oidc_lib import create_oidc_for_single_account_workload
from .shared_lib import AwsLogicalWorkload


def generate_all_oidc(
    *, workloads_info: dict[WorkloadName, AwsLogicalWorkload], kms_key_arn: str
) -> dict[WorkloadName, list[GithubOidcConfig]]:
    all_oidc: dict[WorkloadName, list[GithubOidcConfig]] = defaultdict(list)

    workload_name = "identity-center"
    identity_center_workload = workloads_info[workload_name]
    all_oidc[workload_name].extend(
        create_oidc_for_single_account_workload(
            aws_account_id=identity_center_workload.prod_accounts[0].id,
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=CENTRAL_INFRA_REPO_NAME,
            kms_key_arn=kms_key_arn,
            role_name_suffix="identity-center",
        )
    )

    return all_oidc
