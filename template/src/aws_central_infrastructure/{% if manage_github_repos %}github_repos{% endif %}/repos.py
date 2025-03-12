from collections.abc import Iterable

from .lib import GithubRepoConfig


def create_repo_configs() -> Iterable[GithubRepoConfig]:
    """Create the configurations for the repositories.

    example: `configs.append(GithubRepoConfig(name="test-pulumi-repo", description="blah"))`
    """
    configs: list[GithubRepoConfig] = []
    # Append repos to the list here

    return configs
