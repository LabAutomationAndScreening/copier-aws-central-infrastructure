import logging

import pulumi_aws
from ephemeral_pulumi_deploy import append_resource_suffix
from lab_auto_pulumi import GENERIC_CENTRAL_PRIVATE_SUBNET_NAME
from lab_auto_pulumi import GENERIC_CENTRAL_PUBLIC_SUBNET_NAME
from lab_auto_pulumi import GENERIC_CENTRAL_VPC_NAME
from lab_auto_pulumi import AwsAccountInfo
from pulumi import ResourceOptions
from pulumi_aws.ec2 import InstanceMetadataDefaults
from pulumi_aws.organizations import get_organization

from aws_central_infrastructure.iac_management.lib import load_workload_info

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
        resource_name=f"{generic_vpc.resource_name_base}-vpc",
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

    # set EC2 instance metadata defaults
    region = pulumi_aws.config.region
    _ = InstanceMetadataDefaults(
        append_resource_suffix(f"central-infra-{region}"),
        http_tokens="required",  # enforce imdsv2
        http_put_response_hop_limit=1,
    )
    for workload_info in workloads_info.values():
        workload_name = workload_info.name
        all_accounts: list[AwsAccountInfo] = []

        all_accounts.extend(
            [*workload_info.prod_accounts, *workload_info.staging_accounts, *workload_info.dev_accounts]
        )
        for account in all_accounts:
            _ = InstanceMetadataDefaults(
                append_resource_suffix(f"{workload_name}-{account.name}-{region}", max_length=150),
                http_tokens="required",  # enforce imdsv2
                http_put_response_hop_limit=1,  # enforce imdsv2
                opts=ResourceOptions(
                    provider=all_providers.all_classic_providers[account.id], delete_before_replace=True
                ),
            )
