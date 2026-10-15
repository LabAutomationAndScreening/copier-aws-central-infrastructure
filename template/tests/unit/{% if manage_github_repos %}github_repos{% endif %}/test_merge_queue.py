from random import choice
from uuid import uuid4

import pytest

# separate internal imports from external imports with this comment, because otherwise ruff in the copier template doesn't recognize them as internal and reformats them
from aws_central_infrastructure.github_repos.lib import GithubRepoConfig
from aws_central_infrastructure.github_repos.lib import MergeQueueMergeMethodError
from aws_central_infrastructure.github_repos.lib.repo import MergeMethod
from aws_central_infrastructure.github_repos.lib.repo import _merge_queue_merge_method

ALL_MERGE_METHODS: list[MergeMethod] = ["merge", "squash", "rebase"]


class TestMergeQueueMergeMethod:
    def test_Given_all_methods_enabled_and_allowed_merge_methods_lists_one__When_derived__Then_that_method_in_github_queue_casing(
        self,
    ):
        method = choice(ALL_MERGE_METHODS)
        config = GithubRepoConfig(
            name=str(uuid4()),
            description=str(uuid4()),
            allow_merge_commit=True,
            allow_rebase_merge=True,
            allowed_merge_methods=[method],
        )

        merge_method = _merge_queue_merge_method(config)

        assert merge_method == method.upper()

    def test_Given_default_repo_merge_flags__When_derived__Then_squash(self):
        config = GithubRepoConfig(name=str(uuid4()), description=str(uuid4()))

        merge_method = _merge_queue_merge_method(config)

        assert merge_method == "SQUASH"

    def test_Given_merge_commits_also_enabled__When_derived__Then_error_names_repo_and_both_methods(self):
        repo_name = str(uuid4())
        config = GithubRepoConfig(name=repo_name, description=str(uuid4()), allow_merge_commit=True)

        with pytest.raises(MergeQueueMergeMethodError, match=rf"{repo_name}.*squash.*merge"):
            _ = _merge_queue_merge_method(config)

    def test_Given_import_config_enables_rebase__When_derived__Then_import_flags_decide_and_error_lists_both(self):
        repo_name = str(uuid4())
        imported_settings = GithubRepoConfig(name=str(uuid4()), description=str(uuid4()), allow_rebase_merge=True)
        config = GithubRepoConfig(
            name=repo_name,
            description=str(uuid4()),
            import_existing_repo_using_config=imported_settings,
        )

        with pytest.raises(MergeQueueMergeMethodError, match=rf"{repo_name}.*squash.*rebase"):
            _ = _merge_queue_merge_method(config)

    def test_Given_allowed_merge_methods_names_a_method_disabled_on_the_repo__When_derived__Then_error_lists_none(
        self,
    ):
        repo_name = str(uuid4())
        config = GithubRepoConfig(name=repo_name, description=str(uuid4()), allowed_merge_methods=["rebase"])

        with pytest.raises(MergeQueueMergeMethodError, match=rf"{repo_name}.*\[\]"):
            _ = _merge_queue_merge_method(config)
