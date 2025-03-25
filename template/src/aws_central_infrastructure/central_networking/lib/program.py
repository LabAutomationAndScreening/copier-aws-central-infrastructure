import logging

import pulumi_aws
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags
from ephemeral_pulumi_deploy import common_tags_native
from ephemeral_pulumi_deploy import get_aws_account_id
from pulumi import ComponentResource
from pulumi import ResourceOptions
from pulumi_aws.ec2 import Tag
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import Provider
from pulumi_aws_native import TagArgs
from pulumi_aws_native import ec2
from pulumi_aws_native import ram
from pulumi_aws_native import ssm
from pydantic import BaseModel

from aws_central_infrastructure.iac_management.lib import ORG_MANAGED_SSM_PARAM_PREFIX
from aws_central_infrastructure.iac_management.lib import AwsAccountInfo
from aws_central_infrastructure.iac_management.lib import create_classic_providers
from aws_central_infrastructure.iac_management.lib import create_providers
from aws_central_infrastructure.iac_management.lib import load_workload_info

logger = logging.getLogger(__name__)


class SharedSubnetConfig(BaseModel):
    name: str
    cidr_block: str
    map_public_ip_on_launch: bool = False
    availability_zone_id: str = "use1-az1"  # must use ID, not name https://docs.aws.amazon.com/vpc/latest/userguide/vpc-sharing-share-subnet-working-with.html


def tag_args_to_aws_cli_str(tag_args: list[TagArgs]) -> str:
    return " ".join([f"Key={tag.key},Value={tag.value}" for tag in tag_args])


class SharedSubnet(ComponentResource):
    def __init__(  # noqa: PLR0913 # these are all kwargs
        self,
        *,
        vpc: ec2.Vpc,
        config: SharedSubnetConfig,
        org_id: str,
        org_management_account_id: str,
        all_providers: dict[str, Provider],
        all_classic_providers: dict[str, pulumi_aws.Provider],
    ):
        super().__init__(
            "labauto:CentralNetworkingSharedSubnet",
            append_resource_suffix(config.name),
            None,
            opts=ResourceOptions(parent=vpc),
        )
        subnet_tags = [TagArgs(key="Name", value=config.name), *common_tags_native()]
        subnet = ec2.Subnet(
            append_resource_suffix(config.name),
            vpc_id=vpc.id,
            availability_zone_id=config.availability_zone_id,
            cidr_block=config.cidr_block,
            map_public_ip_on_launch=config.map_public_ip_on_launch,
            tags=subnet_tags,
            opts=ResourceOptions(parent=self),
        )
        subnet_share = ram.ResourceShare(
            append_resource_suffix(config.name),
            resource_arns=[
                subnet.subnet_id.apply(
                    lambda subnet_id: f"arn:aws:ec2:{pulumi_aws.config.region}:{get_aws_account_id()}:subnet/{subnet_id}"
                )
            ],
            principals=[f"arn:aws:organizations::{org_management_account_id}:organization/{org_id}"],
            opts=ResourceOptions(parent=self),
            allow_external_principals=False,  # restrict sharing to your AWS Organization
        )

        for account_id, provider in all_classic_providers.items():
            for tag in subnet_tags:
                _ = Tag(  # tagging via a Pulumi Command using provider didn't work, and pulumi_aws_native doesn't have the Tag resource, so using pulumi AWS classic for now
                    append_resource_suffix(f"tag-{config.name}-{account_id}-{tag.key}", max_length=150),
                    key=tag.key,
                    value=tag.value,
                    resource_id=subnet.id,
                    opts=ResourceOptions(
                        provider=provider, parent=subnet_share, depends_on=[subnet_share], delete_before_replace=True
                    ),
                )
        for account_id, provider in all_providers.items():
            _ = ssm.Parameter(
                append_resource_suffix(f"central-networking-subnet-id-{config.name}-{account_id}", max_length=150),
                type=ssm.ParameterType.STRING,
                name=f"{ORG_MANAGED_SSM_PARAM_PREFIX}/central-networking/subnets/{config.name}-id",
                value=subnet.subnet_id,
                opts=ResourceOptions(provider=provider, parent=subnet_share, delete_before_replace=True),
                tags=common_tags(),
            )


def pulumi_program() -> None:
    """Execute creating the stack."""
    # Create Resources Here
    workloads_dict, _ = load_workload_info()
    org_id = get_organization().id
    vpc = ec2.Vpc(
        append_resource_suffix("generic"),
        cidr_block="10.0.0.0/16",
        enable_dns_hostnames=True,
        tags=[TagArgs(key="Name", value="Generic-Central-VPC"), *common_tags_native()],
    )
    all_accounts: list[AwsAccountInfo] = []
    for workload_info in workloads_dict.values():
        all_accounts.extend(
            [*workload_info.prod_accounts, *workload_info.staging_accounts, *workload_info.dev_accounts]
        )

    all_providers = create_providers(aws_accounts=all_accounts, parent=vpc)
    all_classic_providers = create_classic_providers(aws_accounts=all_accounts, parent=vpc)

    _ = SharedSubnet(
        vpc=vpc,
        config=SharedSubnetConfig(
            name="generic-central-private",
            cidr_block="10.0.1.0/24",
        ),
        org_id=org_id,
        org_management_account_id=get_organization().master_account_id,
        all_providers=all_providers,
        all_classic_providers=all_classic_providers,
    )
