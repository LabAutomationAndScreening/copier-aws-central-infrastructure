from .lib import GLOBAL_AUTOLINKS
from .lib import GithubRepoConfig

GLOBAL_AUTOLINKS.update([])


def create_repo_configs(configs: list[GithubRepoConfig]):
    """Create the configurations for the repositories.

    example: `configs.append(GithubRepoConfig(name="test-pulumi-repo", description="blah"))`
    """
    # Append repos to the list here
    configs.append(
        GithubRepoConfig(
            name=".github",
            description="Public information about the Organization",
            visibility="public",
        )
    )
