from __future__ import annotations

from pathlib import Path

import pytest

import pre_commit.constants as C
from pre_commit.commands.install_uninstall import install
from pre_commit.util import cmd_output
from testing.fixtures import make_consuming_repo
from testing.util import cwd
from testing.util import git_commit


def commit(filename: str) -> None:
    Path(filename).touch()
    cmd_output('git', 'add', filename)
    git_commit('-n', msg=filename)


def hooked_files(stdout: str) -> set[str]:
    lines = stdout.splitlines()
    hooked = [x for x in lines if x.startswith('hooked: ')]
    return {x[8:] for x in hooked}


@pytest.fixture
def prepush_upstream(tempdir_factory):
    upstream = make_consuming_repo(tempdir_factory, 'prepush_scripts_repo')
    with cwd(upstream):
        commit('master_first')
        commit('master_second')
        cmd_output('git', 'branch', 'feature')
        commit('master_third')
        commit('master_fourth')
    return upstream


@pytest.fixture
def prepush_clone(prepush_upstream, tempdir_factory, store):
    path = tempdir_factory.get()
    cmd_output('git', 'clone', prepush_upstream, path)
    with cwd(path):
        assert install(C.CONFIG_FILE, store, hook_types=['pre-push']) == 0
    return path


class TestPushingNewBranch:
    def test_pushing_new_branch_without_commits_should_pass(
            self, prepush_clone,
    ):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', '-b', 'feature2', 'origin/feature')

            _, out, _ = cmd_output('git', 'push', '-u', 'origin', 'feature2')

            assert hooked_files(out) == set()

    def test_pushing_new_branch_with_1_commit_should_give_1_file(
            self, prepush_clone,
    ):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', '-b', 'feature2', 'origin/feature')
            commit('feature_first')

            rc, out, _ = cmd_output(
                'git', 'push', '-u', 'origin', 'feature2',
                check=False,
            )

            assert rc != 0
            assert hooked_files(out) == {'feature_first'}


class TestPushingAfterMerge:
    def test_pushing_mergecommit_over_pushed_commit_gives_merged_files(
        self,
        prepush_clone,
    ):
        '''It probably should pass instead - but it does not with current
        implementation'''
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            cmd_output('git', 'push', '--no-verify')
            cmd_output('git', 'merge', 'master')

            rc, out, _ = cmd_output('git', 'push', check=False)
            assert rc != 0
            assert hooked_files(out) == {'master_fourth', 'master_third'}

    def test_pushing_mergecommit_and_commit_gives_both_files(
        self,
        prepush_clone,
    ):
        '''It probably should pass instead - but it does with current
        implementation'''
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            cmd_output('git', 'push', '--no-verify')
            cmd_output('git', 'merge', 'master')
            commit('feature_second')

            rc, out, _ = cmd_output('git', 'push', check=False)
            assert rc != 0
            assert hooked_files(out) == {
                'feature_second', 'master_fourth',
                'master_third',
            }

    def test_pushing_commit_and_mergecommit_gives_both_files(
        self,
        prepush_clone,
    ):
        '''It probably should pass instead - but it does with current
        implementation'''
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            cmd_output('git', 'push', '--no-verify')
            commit('feature_second')
            cmd_output('git', 'merge', 'master')

            rc, out, _ = cmd_output('git', 'push', check=False)
            assert rc != 0
            assert hooked_files(out) == {
                'feature_second', 'master_fourth',
                'master_third',
            }


class TestMovingBranch:
    rebase_to = 'origin/master~1'

    def test_rebasing_1_commit_should_give_1_file(self, prepush_clone):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            cmd_output('git', 'push', '--no-verify')
            cmd_output('git', 'rebase', self.rebase_to)

            rc, out, _ = cmd_output('git', 'push', '--force', check=False)

            assert rc != 0
            assert hooked_files(out) == {'feature_first'}

    def test_rebasing_1_commit_and_commiting_1_more_should_give_2_files(
            self, prepush_clone,
    ):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            cmd_output('git', 'push', '--no-verify')
            cmd_output('git', 'rebase', self.rebase_to)
            commit('feature_second')

            rc, out, _ = cmd_output('git', 'push', '--force', check=False)

            assert rc != 0
            assert hooked_files(out) == {'feature_first', 'feature_second'}

    def test_rebasing_without_commits_should_pass(self, prepush_clone):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')

            cmd_output('git', 'rebase', self.rebase_to)
            _, out, _ = cmd_output('git', 'push', '--force')

            assert hooked_files(out) == set()


class TestEditingBranch:
    def test_dropping_middle_commit_should_give_last_file(self, prepush_clone):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            commit('feature_second')
            commit('feature_third')
            cmd_output('git', 'push', '--no-verify')

            cmd_output('git', 'reset', '--hard', 'HEAD~2')
            cmd_output('git', 'cherry-pick', 'origin/feature')
            rc, out, _ = cmd_output('git', 'push', '--force', check=False)

            assert rc != 0
            assert hooked_files(out) == {'feature_third'}

    def test_dropping_last_commit_should_pass(self, prepush_clone):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            commit('feature_second')
            commit('feature_third')
            cmd_output('git', 'push', '--no-verify')

            cmd_output('git', 'reset', '--hard', 'HEAD~1')
            _, out, _ = cmd_output('git', 'push', '--force')

            assert hooked_files(out) == set()

    def test_amending_last_commit_should_give_last_file(self, prepush_clone):
        with cwd(prepush_clone):
            cmd_output('git', 'checkout', 'feature')
            commit('feature_first')
            commit('feature_second')
            commit('feature_third')
            cmd_output('git', 'push', '--no-verify')

            git_commit('--amend', '--no-edit')
            rc, out, _ = cmd_output('git', 'push', '--force', check=False)

            assert rc != 0
            assert hooked_files(out) == {'feature_third'}
