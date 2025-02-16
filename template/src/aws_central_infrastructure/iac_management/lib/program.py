import logging

from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import get_aws_account_id
from ephemeral_pulumi_deploy import get_config
from ephemeral_pulumi_deploy import get_config_str
from pulumi import export
from pulumi_aws_native import Provider
from pulumi_aws_native import s3

from ..github_oidc import generate_all_oidc
from .github_oidc_lib import AwsAccountId
from .github_oidc_lib import deploy_all_oidc
from .pulumi_bootstrap import AwsWorkloadPulumiBootstrap
from .pulumi_bootstrap import create_bucket_policy
from .workload_params import WorkloadParams
from .workload_params import load_workload_info

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    aws_account_id = get_aws_account_id()
    export("aws-account-id", aws_account_id)
    env = get_config("proj:env")
    export("env", env)

    # Create Resources Here
    central_state_bucket_name = get_config_str("proj:backend_bucket_name")
    kmy_key_arn = get_config_str("proj:kms_key_id")
    _ = s3.BucketPolicy(
        append_resource_suffix("central-iac-state"),
        bucket=central_state_bucket_name,
        policy_document=create_bucket_policy(central_state_bucket_name),
    )

    workloads_dict, params_dict = load_workload_info()
    providers: dict[AwsAccountId, Provider] = {}
    for workload_info in workloads_dict.values():
        if workload_info.name == "central-infra":
            continue  # don't bootstrap the Central Infra 'workload'---it's unique and has been bootstrapped already by the AWS Organization stack
        bootstrap = AwsWorkloadPulumiBootstrap(
            workload=workload_info,
            central_state_bucket_name=central_state_bucket_name,
            central_iac_kms_key_arn=kmy_key_arn,
        )
        providers.update(bootstrap.providers)
    _ = WorkloadParams(
        name="identity-center",
        params_dict=params_dict,
        provider=providers[workloads_dict["identity-center"].prod_accounts[0].id],
    )
    all_oidc = generate_all_oidc(workloads_info=workloads_dict)
    deploy_all_oidc(
        all_oidc=[(workloads_dict[workload_name], value) for workload_name, value in all_oidc.items()],
        providers=providers,
    )
