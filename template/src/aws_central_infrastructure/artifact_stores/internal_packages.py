from .lib import RepoPackageClaims


def create_internal_packages_configs(repo_package_claims: list[RepoPackageClaims]) -> None:
    """Create the internal packages configurations.

    Example: repo_package_claims.append(RepoPackageClaims(repo_name="cloud-courier", pypi_package_names={"cloud-courier"}))
    """
