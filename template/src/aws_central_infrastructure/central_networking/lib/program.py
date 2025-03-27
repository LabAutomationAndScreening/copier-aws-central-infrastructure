import logging

from pulumi_aws.organizations import get_organization

from ..subnets import define_subnets
from .constants import CREATE_PRIVATE_SUBNET
from .network import AllAccountProviders
from .network import CentralNetworkingVpc
from .network import SharedSubnet
from .network import SharedSubnetConfig
from .network import tag_shared_resource

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    # Create Resources Here
    all_providers = AllAccountProviders()
    org_info = get_organization()
    # TODO: ensure all VPCs have unique names
    # TODO: ensure all subnets have unique names
    # TODO: ensure CIDR ranges don't conflict between subnets (and are valid within the VPC)
    all_vpcs: dict[str, CentralNetworkingVpc] = {}
    generic_vpc = CentralNetworkingVpc(name="generic-central", all_providers=all_providers, all_vpcs=all_vpcs)
    generic_public = SharedSubnet(
        config=SharedSubnetConfig(
            name="generic-central-public",
            vpc=generic_vpc,
            map_public_ip_on_launch=True,
            cidr_block="10.0.1.0/28",
            create_nat=CREATE_PRIVATE_SUBNET,
            route_to_internet_gateway=True,
            accounts_to_share_to=["all"],
        ),
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
    )
    if CREATE_PRIVATE_SUBNET:
        _ = SharedSubnet(  # this should only be used for quick proof of concepts, dedicated subnets should be made for long term use
            config=SharedSubnetConfig(
                name="generic-central-private",
                vpc=generic_vpc,
                cidr_block="10.0.1.16/28",
                route_to_nat_gateway=generic_public.nat_gateway,
                accounts_to_share_to=["all"],
            ),
            org_arn=org_info.arn,
            all_providers=all_providers,
        )
    subnet_configs: list[SharedSubnetConfig] = []
    define_subnets(vpcs=all_vpcs, subnet_configs=subnet_configs)
    for subnet_config in subnet_configs:
        _ = SharedSubnet(
            config=subnet_config,
            org_arn=org_info.arn,
            all_providers=all_providers,
        )
