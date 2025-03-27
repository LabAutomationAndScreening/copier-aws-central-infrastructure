import logging

from pulumi_aws.organizations import get_organization

from aws_central_infrastructure.iac_management.lib import load_workload_info

from ..subnets import define_subnets
from .constants import CREATE_PRIVATE_SUBNET
from .network import GENERIC_CENTRAL_PRIVATE_SUBNET_NAME
from .network import GENERIC_CENTRAL_PUBLIC_SUBNET_NAME
from .network import GENERIC_CENTRAL_VPC_NAME
from .network import AllAccountProviders
from .network import CentralNetworkingVpc
from .network import SharedSubnet
from .network import SharedSubnetConfig
from .network import tag_shared_resource

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    # Create Resources Here
    workloads_info, _ = load_workload_info()
    all_providers = AllAccountProviders(workloads_info=workloads_info)
    org_info = get_organization()
    # TODO: ensure all VPCs have unique names
    # TODO: ensure all subnets have unique names
    # TODO: ensure CIDR ranges don't conflict between subnets (and are valid within the VPC)
    # TODO: define ENUMs for cidr range sizes...in a private subnet, 5 of the IP addresses seem to be consumed by default already, so keep that in mind
    all_vpcs: dict[str, CentralNetworkingVpc] = {}
    all_subnets: dict[str, SharedSubnet] = {}
    generic_vpc = CentralNetworkingVpc(name=GENERIC_CENTRAL_VPC_NAME, all_providers=all_providers, all_vpcs=all_vpcs)
    generic_public = SharedSubnet(
        config=SharedSubnetConfig(
            name=GENERIC_CENTRAL_PUBLIC_SUBNET_NAME,
            vpc=generic_vpc,
            map_public_ip_on_launch=True,
            cidr_block="10.0.1.0/28",
            create_nat=CREATE_PRIVATE_SUBNET,
            route_to_internet_gateway=True,
            accounts_to_share_to=["all"],
        ),
        all_subnets=all_subnets,
        org_arn=org_info.arn,
        all_providers=all_providers,
    )
    tag_shared_resource(
        providers=all_providers.all_classic_providers,
        tags=generic_vpc.vpc_tags,
        resource_name=generic_vpc.tag_name,
        resource_id=generic_vpc.vpc.vpc_id,
        parent=generic_vpc,
        depends_on=[
            generic_public.subnet_share
        ],  # the VPC itself isn't actually shared with the other accounts directly, it's only shared via the subnet, so need to wait for that RAM share to be created
        accounts_to_share_to=["all"],
    )
    if CREATE_PRIVATE_SUBNET:
        _ = SharedSubnet(  # this should only be used for quick proof of concepts, dedicated subnets should be made for long term use
            config=SharedSubnetConfig(
                name=GENERIC_CENTRAL_PRIVATE_SUBNET_NAME,
                vpc=generic_vpc,
                cidr_block="10.0.1.16/28",
                route_to_nat_gateway=generic_public.nat_gateway,
                accounts_to_share_to=["all"],
            ),
            all_subnets=all_subnets,
            org_arn=org_info.arn,
            all_providers=all_providers,
        )
    subnet_configs: list[SharedSubnetConfig] = []
    define_subnets(vpcs=all_vpcs, subnet_configs=subnet_configs, all_subnets=all_subnets, workloads_info=workloads_info)
    for subnet_config in subnet_configs:
        _ = SharedSubnet(
            config=subnet_config, org_arn=org_info.arn, all_providers=all_providers, all_subnets=all_subnets
        )
