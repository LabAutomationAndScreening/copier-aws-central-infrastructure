import logging

from pulumi import export

from ..internal_packages import create_internal_packages_configs
from .code_artifact import CentralCodeArtifact
from .code_artifact import RepoPackageClaims
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
