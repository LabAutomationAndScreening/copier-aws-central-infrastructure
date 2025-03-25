import logging

from pulumi_aws.organizations import get_organization

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

    generic_vpc = CentralNetworkingVpc(name="generic", all_providers=all_providers)

    generic_public = SharedSubnet(
        vpc=generic_vpc,
        config=SharedSubnetConfig(
            name="generic-central-public",
            map_public_ip_on_launch=True,
            cidr_block="10.0.1.0/24",
            create_nat=CREATE_PRIVATE_SUBNET,
            route_to_internet_gateway=True,
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
        _ = SharedSubnet(
            vpc=generic_vpc,
            config=SharedSubnetConfig(
                name="generic-central-private",
                cidr_block="10.0.2.0/24",
                route_to_nat_gateway=generic_public.nat_gateway,
            ),
            org_arn=org_info.arn,
            all_providers=all_providers,
        )
