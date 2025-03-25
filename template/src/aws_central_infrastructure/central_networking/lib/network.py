import pulumi_aws
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags
from ephemeral_pulumi_deploy import common_tags_native
from ephemeral_pulumi_deploy import get_aws_account_id
from pulumi import ComponentResource
from pulumi import Output
from pulumi import Resource
from pulumi import ResourceOptions
from pulumi_aws.ec2 import Tag
from pulumi_aws_native import Provider
from pulumi_aws_native import TagArgs
from pulumi_aws_native import ec2
from pulumi_aws_native import ram
from pulumi_aws_native import ssm
from pydantic import BaseModel
from pydantic import ConfigDict

from aws_central_infrastructure.iac_management.lib import ORG_MANAGED_SSM_PARAM_PREFIX
from aws_central_infrastructure.iac_management.lib import AwsAccountInfo
from aws_central_infrastructure.iac_management.lib import create_classic_providers
from aws_central_infrastructure.iac_management.lib import create_providers
from aws_central_infrastructure.iac_management.lib import load_workload_info

CENTRAL_NETWORKING_SSM_PREFIX = f"{ORG_MANAGED_SSM_PARAM_PREFIX}/central-networking"


class SharedSubnetConfig(BaseModel):
    name: str
    cidr_block: str
    map_public_ip_on_launch: bool = False
    route_to_internet_gateway: bool = False
    route_to_nat_gateway: ec2.NatGateway | None = None
    create_nat: bool = False  # Note! NATs must (should?) be in the same availability zone as the subnet they serve (i.e. the public subnet the NAT is in must be the same AZ as the private subnet routing to it)
    availability_zone_id: str = "use1-az1"  # must use ID, not name https://docs.aws.amazon.com/vpc/latest/userguide/vpc-sharing-share-subnet-working-with.html

    model_config = ConfigDict(arbitrary_types_allowed=True)


def tag_args_to_aws_cli_str(tag_args: list[TagArgs]) -> str:
    return " ".join([f"Key={tag.key},Value={tag.value}" for tag in tag_args])


def create_ssm_param_in_all_accounts(  # noqa: PLR0913 # this is a lot of arguments, but they're all kwargs
    *,
    providers: dict[str, Provider],
    parent: Resource,
    resource_name_prefix: str,
    param_name: str,
    param_value: str | Output[str],
    include_this_account: bool = False,
):
    all_providers: dict[str, Provider | None] = dict(providers.items())
    if include_this_account:
        all_providers[get_aws_account_id()] = None
    for account_id, provider in all_providers.items():
        _ = ssm.Parameter(
            append_resource_suffix(f"{resource_name_prefix}-{account_id}", max_length=150),
            type=ssm.ParameterType.STRING,
            name=param_name,
            value=param_value,
            opts=ResourceOptions(provider=provider, parent=parent, delete_before_replace=True),
            tags=common_tags(),
        )


def tag_shared_resource(  # noqa: PLR0913 # this is a lot of arguments, but they're all kwargs
    *,
    providers: dict[str, pulumi_aws.Provider],
    tags: list[TagArgs],
    resource_name: str,
    resource_id: Output[str],
    parent: Resource,
    depends_on: list[Resource] | None = None,
):
    if depends_on is None:
        depends_on = [parent]
    for account_id, provider in providers.items():
        for tag in tags:
            _ = Tag(
                append_resource_suffix(f"tag-{resource_name}-{account_id}-{tag.key}", max_length=150),
                key=tag.key,
                value=tag.value,
                resource_id=resource_id,
                opts=ResourceOptions(
                    provider=provider,
                    delete_before_replace=True,
                    parent=parent,
                    depends_on=depends_on,
                ),
            )


class AllAccountProviders(ComponentResource):
    def __init__(
        self,
    ):
        super().__init__(
            "labauto:AllOrganizationAwsAccountProviders",
            append_resource_suffix(),
            None,
        )
        workloads_dict, _ = load_workload_info()
        all_accounts: list[AwsAccountInfo] = []
        for workload_info in workloads_dict.values():
            all_accounts.extend(
                [*workload_info.prod_accounts, *workload_info.staging_accounts, *workload_info.dev_accounts]
            )
        self.all_native_providers = create_providers(aws_accounts=all_accounts, parent=self)
        self.all_classic_providers = create_classic_providers(aws_accounts=all_accounts, parent=self)


class CentralNetworkingVpc(ComponentResource):
    def __init__(self, *, name: str, all_providers: AllAccountProviders):
        super().__init__(
            "labauto:CentralNetworkingVpc",
            append_resource_suffix(name),
            None,
        )
        self.tag_name = f"{name}-central-vpc"
        self.vpc_tags = [TagArgs(key="Name", value=self.tag_name), *common_tags_native()]
        self.vpc = ec2.Vpc(
            append_resource_suffix(name),
            cidr_block="10.0.0.0/16",
            enable_dns_hostnames=True,
            tags=self.vpc_tags,
            opts=ResourceOptions(parent=self),
        )
        create_ssm_param_in_all_accounts(
            providers=all_providers.all_native_providers,
            parent=self,
            resource_name_prefix=f"central-networking-vpc-id-{name}",
            param_value=self.vpc.vpc_id,
            param_name=f"{CENTRAL_NETWORKING_SSM_PREFIX}/vpcs/{name}/id",
            include_this_account=True,
        )
        self.igw = ec2.InternetGateway(append_resource_suffix(name), tags=common_tags_native())
        # AWS Native provider doesn't yet support InternetGatewayAttachment, so using classic provider https://github.com/pulumi/pulumi-aws-native/issues/782
        _ = pulumi_aws.ec2.InternetGatewayAttachment(
            append_resource_suffix(name), vpc_id=self.vpc.id, internet_gateway_id=self.igw.id
        )


class SharedSubnet(ComponentResource):
    def __init__(
        self,
        *,
        vpc: CentralNetworkingVpc,
        config: SharedSubnetConfig,
        org_arn: str,
        all_providers: AllAccountProviders,
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
            vpc_id=vpc.vpc.id,
            availability_zone_id=config.availability_zone_id,
            cidr_block=config.cidr_block,
            map_public_ip_on_launch=config.map_public_ip_on_launch,
            tags=subnet_tags,
            opts=ResourceOptions(parent=self),
        )
        self.subnet_share = ram.ResourceShare(
            append_resource_suffix(config.name),
            resource_arns=[
                subnet.subnet_id.apply(
                    lambda subnet_id: f"arn:aws:ec2:{pulumi_aws.config.region}:{get_aws_account_id()}:subnet/{subnet_id}"
                )
            ],
            principals=[org_arn],
            opts=ResourceOptions(parent=self),
            allow_external_principals=False,
            tags=common_tags_native(),
        )
        tag_shared_resource(
            providers=all_providers.all_classic_providers,
            tags=subnet_tags,
            resource_name=f"{config.name}-subnet",
            resource_id=subnet.subnet_id,
            parent=self.subnet_share,
        )
        route_table_tags = [TagArgs(key="Name", value=config.name), *common_tags_native()]
        route_table = ec2.RouteTable(
            append_resource_suffix(config.name),
            vpc_id=vpc.vpc.id,
            tags=route_table_tags,
            opts=ResourceOptions(parent=self),
        )
        tag_shared_resource(
            providers=all_providers.all_classic_providers,
            tags=route_table_tags,
            resource_name=f"{config.name}-route-table",
            resource_id=route_table.id,
            parent=self.subnet_share,
        )

        _ = ec2.SubnetRouteTableAssociation(
            append_resource_suffix(config.name),
            subnet_id=subnet.id,
            route_table_id=route_table.id,
            opts=ResourceOptions(parent=route_table),
        )
        if config.route_to_internet_gateway:
            _ = ec2.Route(
                append_resource_suffix(f"{config.name}-to-igw"),
                route_table_id=route_table.id,
                destination_cidr_block="0.0.0.0/0",
                gateway_id=vpc.igw.id,
                opts=ResourceOptions(parent=route_table),
            )
        if config.route_to_nat_gateway is not None:
            _ = ec2.Route(
                append_resource_suffix(f"{config.name}-to-nat"),
                route_table_id=route_table.id,
                destination_cidr_block="0.0.0.0/0",
                gateway_id=config.route_to_nat_gateway.id,
                opts=ResourceOptions(parent=route_table),
            )
        if config.create_nat:
            nat_eip = ec2.Eip(
                append_resource_suffix(f"{config.name}-nat"),
                domain="vpc",
                tags=common_tags_native(),
                opts=ResourceOptions(parent=self, depends_on=[vpc.igw]),
            )
            self.nat_gateway = ec2.NatGateway(
                append_resource_suffix(config.name),
                allocation_id=nat_eip.allocation_id,
                subnet_id=subnet.id,
                tags=common_tags_native(),
                opts=ResourceOptions(parent=self),
            )
        create_ssm_param_in_all_accounts(
            providers=all_providers.all_native_providers,
            parent=self.subnet_share,
            resource_name_prefix=f"central-networking-subnet-id-{config.name}",
            param_value=subnet.subnet_id,
            param_name=f"{CENTRAL_NETWORKING_SSM_PREFIX}/subnets/{config.name}/id",
            include_this_account=True,
        )
