from uuid import uuid4

import pytest

# separate internal imports from external imports with this comment, because otherwise ruff in the copier template doesn't recognize them as internal and reformats them
from aws_central_infrastructure.github_repos.lib import GithubRepoConfig
from aws_central_infrastructure.github_repos.lib import GithubTeamConfig
from aws_central_infrastructure.github_repos.lib import ReviewExemptTeamNotFoundError
from aws_central_infrastructure.github_repos.lib.repo import _validate_review_exempt_teams
from aws_central_infrastructure.github_repos.repos import create_repo_configs
from aws_central_infrastructure.github_repos.teams import define_team_configs


class TestValidateReviewExemptTeams:
    def test_Given_repo_names_a_slug_no_team_produces__When_validated__Then_error_names_repo_slug_and_available_slugs(
        self,
    ):
        repo_name = str(uuid4())
        missing_slug = str(uuid4())
        known_slug = str(uuid4())
        config = GithubRepoConfig(name=repo_name, description=str(uuid4()), review_exempt_teams=[missing_slug])

        with pytest.raises(ReviewExemptTeamNotFoundError, match=rf"{repo_name}.*{missing_slug}.*{known_slug}"):
            _validate_review_exempt_teams(configs=[config], team_slugs=[known_slug])


class TestRealConfigs:
    def test_Given_repo_and_team_configs__When_exempt_slugs_collected__Then_each_matches_a_team_slug(self):
        repo_configs: list[GithubRepoConfig] = []
        create_repo_configs(repo_configs)
        root_team = GithubTeamConfig(name="Everyone", description="Everyone in the organization.")
        dev_sec_ops_team_config = GithubTeamConfig(
            name="DevSecOps", description="DevSecOps Team", parent_team=root_team
        )
        team_configs: list[GithubTeamConfig] = [dev_sec_ops_team_config]
        _ = define_team_configs(configs=team_configs, dev_sec_ops_team_config=dev_sec_ops_team_config)
        team_slugs = {root_team.slug, *(team.slug for team in team_configs)}

        referenced_slugs = {slug for config in repo_configs for slug in config.review_exempt_teams}

        assert referenced_slugs - team_slugs == set()
