from lab_auto_pulumi import AwsLogicalWorkload
from lab_auto_pulumi import WorkloadName

from .lib import CentralNetworkingVpc
from .lib import SharedSubnet
from .lib import SharedSubnetConfig


def define_subnets(
    *,
    vpcs: dict[str, CentralNetworkingVpc],
    subnet_configs: list[SharedSubnetConfig],
    all_subnets: dict[str, SharedSubnet],
    workloads_info: dict[WorkloadName, AwsLogicalWorkload],
) -> None:
    """Create subnets to share with accounts within the AWS organization.

    Example:
    subnet_configs.append(
        SharedSubnetConfig(
            name="my-app",
            vpc=vpcs[GENERIC_VPC_NAME],
            cidr_block="10.0.1.0/28",
            accounts_to_share_to=[workloads_info["my-app-workload"].prod_accounts[0].id],
        )
    )
    """
