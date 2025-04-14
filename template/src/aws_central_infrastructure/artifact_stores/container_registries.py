from .lib import EcrConfig


def define_container_registries(container_registries: list[EcrConfig]) -> None:
    """Create container registries (e.g. ECRs) to share across the organization or within a workload.

    Example:
    container_registries.append(
        EcrConfig(
            git_repo_name="cool-repo",
            ecr_repo_name="backend",
            ecr_repo_namespace="my-project",
        )
    )
    """
