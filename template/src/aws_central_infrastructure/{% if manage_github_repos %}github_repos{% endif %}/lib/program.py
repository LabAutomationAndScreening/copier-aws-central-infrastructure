import logging

from ..repos import create_repo_configs
from .repo import create_repos

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    configs = create_repo_configs()
    create_repos(configs)
