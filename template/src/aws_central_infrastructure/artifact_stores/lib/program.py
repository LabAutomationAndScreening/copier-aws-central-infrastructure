import logging

from pulumi import export

from ..ami_sharing import define_image_builders
from ..internal_packages import create_internal_packages_configs
from .code_artifact import CentralCodeArtifact
from .code_artifact import RepoPackageClaims
from .image_builder import ImageBuilderConfig
from .image_builder import create_image_builders
from .ssm_buckets import DistributorPackagesBucket
from .ssm_buckets import ManualArtifactsBucket
from .ssm_buckets import create_ssm_bucket_ssm_params

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    # Create Resources Here
    central_code_artifact = CentralCodeArtifact()
    manual_artifacts_bucket = ManualArtifactsBucket()
    distributor_packages_bucket = DistributorPackagesBucket()
    create_ssm_bucket_ssm_params(
        distributor_packages_bucket=distributor_packages_bucket, manual_artifacts_bucket=manual_artifacts_bucket
    )
    export(
        "manual-artifacts-bucket-name", manual_artifacts_bucket.bucket.bucket_name
    )  # TODO: reference this by the Identity Center stack
    package_claims: list[RepoPackageClaims] = []
    create_internal_packages_configs(package_claims)
    central_code_artifact.register_package_claims(package_claims)
    image_builders: list[ImageBuilderConfig] = []
    define_image_builders(image_builders)
    create_image_builders(
        image_builder_configs=image_builders,
        manual_artifacts_bucket_name=manual_artifacts_bucket.bucket.bucket_name,
    )
