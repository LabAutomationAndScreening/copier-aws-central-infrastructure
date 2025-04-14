from ephemeral_pulumi_deploy import get_aws_account_id
from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import WorkloadName
from pulumi_aws.iam import get_policy_document
from pulumi_aws_native import iam

from ..github_oidc import generate_oidc
from .constants import CENTRAL_INFRA_GITHUB_ORG_NAME
from .constants import CENTRAL_INFRA_REPO_NAME
from .constants import CLOUD_COURIER_INFRA_REPO_NAME
from .constants import CONFIGURE_CLOUD_COURIER
from .github_oidc_lib import CODE_ARTIFACT_SERVICE_BEARER_STATEMENT
from .github_oidc_lib import PULL_FROM_CENTRAL_ECRS_STATEMENTS
from .github_oidc_lib import GithubOidcConfig
from .github_oidc_lib import create_oidc_for_single_account_workload
from .github_oidc_lib import create_oidc_for_standard_workload


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


def generate_all_oidc(
    *, workloads_info: dict[WorkloadName, AwsLogicalWorkload], all_oidc: dict[WorkloadName, list[GithubOidcConfig]]
) -> None:
    # Organization delegate accounts that have things deployed within this repo
    for workload_name in ("identity-center",):
        workload = workloads_info[workload_name]
        all_oidc[workload_name].extend(
            create_oidc_for_single_account_workload(
                aws_account_id=workload.prod_accounts[0].id,
                repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
                repo_name=CENTRAL_INFRA_REPO_NAME,
                role_name_suffix=workload_name,
            )
        )

    all_oidc["central-infra"].append(
        GithubOidcConfig(
            aws_account_id=get_aws_account_id(),
            role_name="CoreInfraBaseAccess",
            repo_org=CENTRAL_INFRA_GITHUB_ORG_NAME,
            repo_name="*",
            role_policy=iam.RolePolicyArgs(
                policy_name="ReadFromCentralArtifactStores",
                policy_document=get_policy_document(
                    statements=[
                        CODE_ARTIFACT_SERVICE_BEARER_STATEMENT,
                        *PULL_FROM_CENTRAL_ECRS_STATEMENTS,
                    ]
                ).json,
            ),
        ),
    )
    generate_oidc(workloads_info=workloads_info, all_oidc=all_oidc)
