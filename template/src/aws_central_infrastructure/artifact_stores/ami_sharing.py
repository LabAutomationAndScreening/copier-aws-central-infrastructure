from .lib import ImageBuilderConfig
from .lib import ImageShareConfig


def define_image_builders(image_builders: list[ImageBuilderConfig]) -> None:
    """Create image builders used to build AMIs to share across the organization.

    Example:
    image_builders.append(
        ImageBuilderConfig(
            builder_resource_name="my-app-image", instance_type="t3.micro", base_image_id="ami-02e3d076cbd5c28fa"
        )
    )
    """


def define_image_shares(image_shares: list[ImageShareConfig]) -> None:
    """Define the sharing of AMIs across the organization.

    Example:
    image_shares.append(
        ImageShareConfig(
            image_id="ami-02e3d076cbd5c28f2"
        )
    )
    """
