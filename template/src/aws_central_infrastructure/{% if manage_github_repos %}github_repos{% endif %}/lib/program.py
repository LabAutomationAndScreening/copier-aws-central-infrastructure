import logging

from ..repos import create_repo_configs
from .repo import create_github_provider
from .repo import create_repos

logger = logging.getLogger(__name__)


def pulumi_program() -> None:
    """Execute creating the stack."""
    configs = create_repo_configs()
    provider = create_github_provider()
    create_repos(configs=configs, provider=provider)
