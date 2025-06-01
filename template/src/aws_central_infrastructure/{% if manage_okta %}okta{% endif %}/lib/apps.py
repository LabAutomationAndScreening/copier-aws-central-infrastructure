import pulumi
from ephemeral_pulumi_deploy import append_resource_suffix
from pulumi import ResourceOptions
from pulumi_okta import Provider
from pulumi_okta.app import Saml


def create_apps(*, provider: Provider):
    aws_ic_app = Saml(
        append_resource_suffix("aws-identity-center"),
        label="AWS IAM Identity Center",
        preconfigured_app="amazon_aws",
        opts=ResourceOptions(provider=provider),
    )
    pulumi.export("AWS-IDENTITY-CENTER-METADATA", aws_ic_app.metadata)
