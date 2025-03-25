from pydantic import BaseModel
from pydantic import Field

from aws_central_infrastructure.central_networking.lib import CREATE_PRIVATE_SUBNET


class ImageBuilderConfig(BaseModel):
    central_networking_subnet_name: str = Field(
        default_factory=lambda: "generic-central-private" if CREATE_PRIVATE_SUBNET else "generic-central-public"
    )
    builder_resource_name: str
    instance_type: str
    user_access_tags: str = "Everyone"
    base_image_id: str
    new_image_name: str | None = None


class ImageShareConfig(BaseModel):
    image_id: str
