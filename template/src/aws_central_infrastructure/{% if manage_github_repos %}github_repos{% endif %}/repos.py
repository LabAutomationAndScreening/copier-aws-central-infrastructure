from .lib import GithubRepoConfig


def create_repo_configs(configs: list[GithubRepoConfig]):
    """Create the configurations for the repositories.

    example: `configs.append(GithubRepoConfig(name="test-pulumi-repo", description="blah"))`
    """
    # Append repos to the list here
