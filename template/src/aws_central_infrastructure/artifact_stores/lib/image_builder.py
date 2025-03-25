import base64
import inspect

import boto3
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags_native
from ephemeral_pulumi_deploy import get_config_str
from pulumi import ComponentResource
from pulumi import Output
from pulumi import ResourceOptions
from pulumi import export
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import GetPolicyDocumentStatementPrincipalArgs
from pulumi_aws.iam import RolePolicy
from pulumi_aws.iam import get_policy_document
from pulumi_aws_native import TagArgs
from pulumi_aws_native import ec2
from pulumi_aws_native import iam
from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.central_networking.lib import CENTRAL_NETWORKING_SSM_PREFIX
from aws_central_infrastructure.central_networking.lib import CREATE_PRIVATE_SUBNET

USER_ACCESS_TAG_DELIMITER = "--"


class ImageBuilderConfig(BaseModel):
    central_networking_subnet_name: str = Field(
        default_factory=lambda: "generic-central-private" if CREATE_PRIVATE_SUBNET else "generic-central-public"
    )
    central_networking_vpc_name: str = "generic"
    builder_resource_name: str
    instance_type: str
    user_access_tags: list[str] = Field(default_factory=lambda: ["Everyone"])
    base_image_id: str
    new_image_name: str | None = None


class ImageShareConfig(BaseModel):
    image_id: str


def get_central_networking_subnet_id(subnet_name: str) -> str:
    org_home_region = get_config_str("proj:aws_org_home_region")
    ssm_client = boto3.client("ssm", region_name=org_home_region)
    param = ssm_client.get_parameter(Name=f"{CENTRAL_NETWORKING_SSM_PREFIX}/subnets/{subnet_name}/id")["Parameter"]
    assert "Value" in param, f"Expected 'Value' in {param}"
    return param["Value"]


def get_central_networking_vpc_id(vpc_name: str) -> str:
    org_home_region = get_config_str("proj:aws_org_home_region")
    ssm_client = boto3.client("ssm", region_name=org_home_region)
    param = ssm_client.get_parameter(Name=f"{CENTRAL_NETWORKING_SSM_PREFIX}/vpcs/{vpc_name}/id")["Parameter"]
    assert "Value" in param, f"Expected 'Value' in {param}"
    return param["Value"]


class Ec2ImageBuilder(ComponentResource):
    def __init__(self, *, config: ImageBuilderConfig, manual_artifacts_bucket_name: Output[str | None]):
        resource_name = f"{config.builder_resource_name}-builder"
        super().__init__(
            "labauto:Ec2ImageBuilder",
            append_resource_suffix(config.builder_resource_name),
            None,
        )
        instance_role = iam.Role(
            append_resource_suffix(f"{resource_name}"),
            assume_role_policy_document=get_policy_document(
                statements=[
                    GetPolicyDocumentStatementArgs(
                        sid="AllowSsmAgentToAssumeRole",
                        effect="Allow",
                        actions=["sts:AssumeRole"],
                        principals=[
                            GetPolicyDocumentStatementPrincipalArgs(type="Service", identifiers=["ec2.amazonaws.com"])
                        ],
                    )
                ]
            ).json,
            managed_policy_arns=["arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"],
            tags=common_tags_native(),
            opts=ResourceOptions(parent=self),
        )
        _ = RolePolicy(
            append_resource_suffix(f"{resource_name}-s3-read"),
            role=instance_role.role_name,  # type: ignore[reportArgumentType] # pyright somehow thinks that a role_name can be None...which cannot happen
            policy=manual_artifacts_bucket_name.apply(
                lambda bucket_name: get_policy_document(
                    statements=[
                        GetPolicyDocumentStatementArgs(
                            sid="ReadManualArtifacts",
                            effect="Allow",
                            actions=["s3:GetObject"],
                            resources=[f"arn:aws:s3:::{bucket_name}/*"],
                        )
                    ]
                ).json
            ),
            opts=ResourceOptions(parent=instance_role),
        )
        instance_profile = iam.InstanceProfile(
            append_resource_suffix(resource_name),
            roles=[instance_role.role_name],  # type: ignore[reportArgumentType] # pyright thinks only inputs can be set as role names, but Outputs seem to work fine
            opts=ResourceOptions(parent=instance_role),
        )
        sg = ec2.SecurityGroup(
            append_resource_suffix(resource_name),
            vpc_id=get_central_networking_vpc_id(config.central_networking_vpc_name),
            group_description="Allow all outbound traffic for SSM access",
            security_group_egress=[
                ec2.SecurityGroupEgressArgs(ip_protocol="-1", from_port=0, to_port=0, cidr_ip="0.0.0.0/0")
            ],
            tags=common_tags_native(),
            opts=ResourceOptions(parent=self),
        )
        user_data_plain = manual_artifacts_bucket_name.apply(
            lambda bucket_name: inspect.cleandoc(
                f"""<powershell>
                setx MANUAL_ARTIFACTS_BUCKET_NAME "{bucket_name}" /M
                </powershell>"""
            )
        )
        _ = ec2.Instance(
            append_resource_suffix(resource_name),
            instance_type=config.instance_type,
            image_id=config.base_image_id,
            subnet_id=get_central_networking_subnet_id(config.central_networking_subnet_name),
            security_group_ids=[sg.id],
            iam_instance_profile=instance_profile.instance_profile_name,  # type: ignore[reportArgumentType] # pyright thinks only inputs can be set as instance profile names, but Outputs seem to work fine
            tags=[
                TagArgs(key="Name", value=resource_name),
                TagArgs(
                    key="UserAccess",
                    value=f"{USER_ACCESS_TAG_DELIMITER}{USER_ACCESS_TAG_DELIMITER.join(config.user_access_tags)}{USER_ACCESS_TAG_DELIMITER}",
                ),
                *common_tags_native(),
            ],
            user_data=user_data_plain.apply(
                lambda user_data: base64.b64encode(user_data.encode("utf-8")).decode("utf-8")
            ),
            opts=ResourceOptions(parent=self),
        )
        export(f"-user-data-for-{append_resource_suffix(config.builder_resource_name)}", user_data_plain)


def create_image_builders(
    *, image_builder_configs: list[ImageBuilderConfig], manual_artifacts_bucket_name: Output[str | None]
) -> None:
    for image_builder_config in image_builder_configs:
        _ = Ec2ImageBuilder(config=image_builder_config, manual_artifacts_bucket_name=manual_artifacts_bucket_name)
