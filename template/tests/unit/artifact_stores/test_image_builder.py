from uuid import uuid4

import pydantic
import pytest

# separate internal imports from external imports with this comment, because otherwise ruff in the copier template doesn't recognize them as internal and reformats them
from aws_central_infrastructure.artifact_stores.lib import ImageBuilderConfig


def test_Given_no_new_image_config__When_tear_down_builder_true__Then_error():
    builder_resource_name = str(uuid4())
    with pytest.raises(pydantic.ValidationError, match=f"(.|\n)*{builder_resource_name}(.|\n)*tear_down_builder"):
        _ = ImageBuilderConfig(
            builder_resource_name=builder_resource_name,
            instance_type=str(uuid4()),
            base_image_id=str(uuid4()),
            tear_down_builder=True,
        )
