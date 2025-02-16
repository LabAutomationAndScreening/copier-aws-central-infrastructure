import logging

from pulumi import export

from .ssm_buckets import DistributorPackagesBucket
from .ssm_buckets import ManualArtifactsBucket

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    # Create Resources Here
    manual_artifacts_bucket = ManualArtifactsBucket()
    _ = DistributorPackagesBucket()

    export(
        "manual-artifacts-bucket-name", manual_artifacts_bucket.bucket.bucket_name
    )  # referenced by the Identity Center stack
