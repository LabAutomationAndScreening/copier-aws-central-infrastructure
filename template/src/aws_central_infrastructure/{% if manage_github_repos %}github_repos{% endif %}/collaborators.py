from .lib import RepositoryCollaboratorConfig


def define_repository_collaborators(*, configs: list[RepositoryCollaboratorConfig]):
    """Create the configurations for any outside collaborators.

    example: ```
    configs.append(
        RepositoryCollaboratorConfig(
            username="great-coder",
            description="From Initech, consultant assisting with project MyApplication",
            repo_permissions={"my-application": "push"},
        )
    )
    ```
    """
    _ = configs  # this line can be removed once the first collaborator is appended on to configs, it just temporarily helps linting when the template is instantiated
