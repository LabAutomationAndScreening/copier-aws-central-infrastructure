from .lib import SamlAppConfig


def define_app_configs(configs: list[SamlAppConfig]) -> None:
    """Create the configurations for the Users.

    example: ```
        configs.append(
            AwsIdentityCenterAppConfig(
                name="AWS Identity Center",
                label="Our Company's AWS",
                assigned_groups=["All Employees"],
                acs_url="https://us-east-1.signin.aws.amazon.com/platform/saml/acs/cc4f222e-849d-48fa-853a-ede44a96201d",
                issuer_url="https://us-east-1.signin.aws.amazon.com/platform/saml/d-9222cbd398",
            )
        )
    ```
    """
