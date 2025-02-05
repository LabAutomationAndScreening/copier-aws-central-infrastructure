import logging

from ephemeral_pulumi_deploy import get_aws_account_id
from ephemeral_pulumi_deploy import get_config
from pulumi import export

from ..iac_management.workload_params import load_workload_info
from .permissions import create_permissions
from .users import create_users

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    env = get_config("proj:env")
    export("env", env)
    aws_account_id = get_aws_account_id()
    export("aws-account-id", aws_account_id)

    # Create Resources Here
    workloads_dict, _ = load_workload_info()
    # Note: you must create any new users and deploy them before you can assign any permissions to them (otherwise the Preview will fail)
    create_users()
    create_permissions(workloads_dict)
