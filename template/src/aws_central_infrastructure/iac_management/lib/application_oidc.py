from .constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from .constants import CLOUD_COURIER_INFRA_REPO_NAME
from .constants import CONFIGURE_CLOUD_COURIER
from .github_oidc_lib import GithubOidcConfig
from .github_oidc_lib import WorkloadName
from .github_oidc_lib import create_oidc_for_standard_workload
from .shared_lib import AwsLogicalWorkload


def create_application_oidc_if_needed(
    *, all_oidc: dict[WorkloadName, list[GithubOidcConfig]], workloads_info: dict[WorkloadName, AwsLogicalWorkload]
) -> None:
    if not CONFIGURE_CLOUD_COURIER:
        return
    workload_name = "cloud-courier"
    cloud_courier_workload = workloads_info[workload_name]
    all_oidc[workload_name].extend(
        create_oidc_for_standard_workload(
            workload_info=cloud_courier_workload,
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name=CLOUD_COURIER_INFRA_REPO_NAME,
        )
    )
