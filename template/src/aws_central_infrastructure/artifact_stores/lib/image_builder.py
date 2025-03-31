import inspect
from typing import Any
from typing import override

import boto3
from ephemeral_pulumi_deploy import append_resource_suffix
from ephemeral_pulumi_deploy import common_tags
from ephemeral_pulumi_deploy import get_config_str
from lab_auto_pulumi import GENERIC_CENTRAL_PRIVATE_SUBNET_NAME
from lab_auto_pulumi import GENERIC_CENTRAL_PUBLIC_SUBNET_NAME
from lab_auto_pulumi import GENERIC_CENTRAL_VPC_NAME
from lab_auto_pulumi import Ec2WithRdp
from pulumi import ComponentResource
from pulumi import Output
from pulumi import ResourceOptions
from pulumi import export
from pulumi_aws.ec2 import AmiFromInstance
from pulumi_aws.ec2 import AmiLaunchPermission
from pulumi_aws.iam import GetPolicyDocumentStatementArgs
from pulumi_aws.iam import RolePolicy
from pulumi_aws.iam import get_policy_document
from pulumi_aws.organizations import get_organization
from pulumi_aws_native import TagArgs
from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.central_networking.lib import CENTRAL_NETWORKING_SSM_PREFIX
from aws_central_infrastructure.central_networking.lib import CREATE_PRIVATE_SUBNET

USER_ACCESS_TAG_DELIMITER = "--"


class NewImageConfig(BaseModel):
    name: str
    description: str
    description_of_how_image_was_built: str


class ImageBuilderConfig(BaseModel):
    central_networking_subnet_name: str = Field(
        default_factory=lambda: GENERIC_CENTRAL_PRIVATE_SUBNET_NAME
        if CREATE_PRIVATE_SUBNET
        else GENERIC_CENTRAL_PUBLIC_SUBNET_NAME
    )
    central_networking_vpc_name: str = GENERIC_CENTRAL_VPC_NAME
    builder_resource_name: str
    instance_type: str
    user_access_tags: list[str] = Field(default_factory=lambda: ["Everyone"])
    base_image_id: str
    new_image_config: NewImageConfig | None = None
    tear_down_builder: bool = False  # set this to true after the image is created to remove the EC2 instance but leave in place the information of how it was created

    @override
    def model_post_init(self, context: Any):
        if self.new_image_config is None and self.tear_down_builder:
            raise ValueError(  # noqa: TRY003 # Pydantic standard pattern utilizes ValueError for validation
                f"Error for builder {self.builder_resource_name}: If tear_down_builder is true, then new_image_config must be set."
            )


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
        user_data_plain = manual_artifacts_bucket_name.apply(
            lambda bucket_name: inspect.cleandoc(
                f"""<powershell>
                setx MANUAL_ARTIFACTS_BUCKET_NAME "{bucket_name}" /M
                </powershell>"""
            )
        )
        if not config.tear_down_builder:
            ec2_builder = Ec2WithRdp(
                name=resource_name,
                central_networking_subnet_name=config.central_networking_subnet_name,
                instance_type=config.instance_type,
                image_id=config.base_image_id,
                central_networking_vpc_name=config.central_networking_vpc_name,
                user_data=user_data_plain,
                additional_instance_tags=[
                    TagArgs(
                        key="UserAccess",
                        value=f"{USER_ACCESS_TAG_DELIMITER}{USER_ACCESS_TAG_DELIMITER.join(config.user_access_tags)}{USER_ACCESS_TAG_DELIMITER}",
                    )
                ],
            )
            _ = RolePolicy(
                append_resource_suffix(f"{resource_name}-s3-read"),
                role=ec2_builder.instance_role.role_name,  # type: ignore[reportArgumentType] # pyright somehow thinks that a role_name can be None...which cannot happen
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
                opts=ResourceOptions(parent=ec2_builder.instance_role),
            )
        if config.new_image_config is not None:
            # TODO: confirm the instance is stopped...because if it wasn't then probably sysprep wasn't run (probably via a pulumi Command)
            # TODO: automatically delete volume snapshots when AMI is registered https://chatgpt.com/c/67e560ba-6558-800f-a1b7-85d119e58191
            new_ami = AmiFromInstance(  # can take 12 minutes-ish for Windows Server
                append_resource_suffix(f"{config.builder_resource_name}-ami"),
                description=config.new_image_config.description,
                name=config.new_image_config.name,
                source_instance_id="fake-because-the-instance-is-actually-deleted-now"
                if config.tear_down_builder
                else ec2_builder.instance.id,  # type: ignore[reportPossiblyUnboundVariable] # this is false positive due to the matching of the conditionals here and above
                tags={"Name": config.new_image_config.name, **common_tags()},
                opts=ResourceOptions(parent=self, ignore_changes=["source_instance_id"]),
            )
            export(f"{config.new_image_config.name}-ami-id", new_ami.id)
            _ = AmiLaunchPermission(
                append_resource_suffix(f"{config.builder_resource_name}-ami-share"),
                image_id=new_ami.id,
                organization_arn=get_organization().arn,  # TODO: pass this in so the API isn't invoked repeatedly
                opts=ResourceOptions(parent=self),
            )


def create_image_builders(
    *, image_builder_configs: list[ImageBuilderConfig], manual_artifacts_bucket_name: Output[str | None]
) -> None:
    for image_builder_config in image_builder_configs:
        _ = Ec2ImageBuilder(config=image_builder_config, manual_artifacts_bucket_name=manual_artifacts_bucket_name)
