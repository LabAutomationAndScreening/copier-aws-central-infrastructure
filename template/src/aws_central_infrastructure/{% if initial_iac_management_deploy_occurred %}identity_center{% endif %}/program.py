import logging

from ephemeral_pulumi_deploy import get_aws_account_id
from ephemeral_pulumi_deploy import get_config
from pulumi import export

from ..iac_management.workload_params import load_workload_info

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    env = get_config("proj:env")
    export("env", env)
    aws_account_id = get_aws_account_id()
    export("aws-account-id", aws_account_id)

    # Create Resources Here
    organization_home_region = "us-east-1"
    workloads_dict, _ = load_workload_info(organization_home_region=organization_home_region)
    del workloads_dict
