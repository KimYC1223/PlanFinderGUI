"""Tests for the committer module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from plan_finder_gui.engine.committer import _unstage_changes, git_commit


class TestUnstageChanges:
    """Tests for _unstage_changes helper function."""

    def test_unstage_success(self):
        """Should return True when git reset HEAD succeeds."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _unstage_changes("/fake/path")
            assert result is True
            mock_run.assert_called_once_with(
                ["git", "reset", "HEAD"],
                cwd="/fake/path",
                capture_output=True,
                text=True,
                timeout=10.0,
            )

    def test_unstage_failure(self):
        """Should return False when git reset HEAD fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = _unstage_changes("/fake/path")
            assert result is False

    def test_unstage_timeout(self):
        """Should return False when git reset times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10.0)
            result = _unstage_changes("/fake/path")
            assert result is False

    def test_unstage_file_not_found(self):
        """Should return False when git is not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            result = _unstage_changes("/fake/path")
            assert result is False


class TestGitCommit:
    """Tests for git_commit function."""

    def test_commit_success(self):
        """Should return (True, output) when commit succeeds."""
        with patch("subprocess.run") as mock_run:
            # Mock git add -A (success)
            # Mock git diff --cached --quiet (changes exist, returncode=1)
            # Mock git commit (success)
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=""),
                MagicMock(returncode=1),  # Changes exist
                MagicMock(returncode=0, stdout="[main abc123] Test commit", stderr=""),
            ]
            success, output = git_commit("/fake/path", "Test commit")
            assert success is True
            assert "Test commit" in output

    def test_commit_failure_unstage_succeeds(self):
        """Should unstage changes and indicate success in error message."""
        with patch("subprocess.run") as mock_run:
            # Mock git add -A (success)
            # Mock git diff --cached --quiet (changes exist, returncode=1)
            # Mock git commit (failure - e.g., pre-commit hook)
            # Mock git reset HEAD (success)
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=""),
                MagicMock(returncode=1),  # Changes exist
                MagicMock(returncode=1, stderr="pre-commit hook failed"),
                MagicMock(returncode=0),  # git reset HEAD succeeds
            ]
            success, output = git_commit("/fake/path", "Test commit")
            assert success is False
            assert "git commit 실패 (변경사항 unstage됨)" in output
            assert "pre-commit hook failed" in output

            # Verify git reset HEAD was called
            calls = mock_run.call_args_list
            assert len(calls) == 4
            reset_call = calls[3]
            assert reset_call[0][0] == ["git", "reset", "HEAD"]

    def test_commit_failure_unstage_also_fails(self):
        """Should indicate unstage failure in error message."""
        with patch("subprocess.run") as mock_run:
            # Mock git add -A (success)
            # Mock git diff --cached --quiet (changes exist, returncode=1)
            # Mock git commit (failure)
            # Mock git reset HEAD (also failure)
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=""),
                MagicMock(returncode=1),  # Changes exist
                MagicMock(returncode=1, stderr="GPG signing failed"),
                MagicMock(returncode=1),  # git reset HEAD fails
            ]
            success, output = git_commit("/fake/path", "Test commit")
            assert success is False
            assert "git commit 실패 (unstage도 실패)" in output
            assert "GPG signing failed" in output

    def test_add_failure_does_not_unstage(self):
        """Should not try to unstage if git add fails (nothing was staged)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")
            success, output = git_commit("/fake/path", "Test commit")
            assert success is False
            assert "git add 실패" in output
            # Only one call should be made (git add)
            assert mock_run.call_count == 1

    def test_no_changes_does_not_unstage(self):
        """Should not try to unstage if there are no changes to commit."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=""),  # git add -A
                MagicMock(returncode=0),  # git diff --cached --quiet (no changes)
            ]
            success, output = git_commit("/fake/path", "Test commit")
            assert success is False
            assert "커밋할 변경사항 없음" in output
            # Only two calls should be made (git add, git diff)
            assert mock_run.call_count == 2

    def test_exception_after_staging_unstages(self):
        """Should try to unstage if an exception occurs after staging."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=""),  # git add -A succeeds
                MagicMock(returncode=1),  # git diff --cached --quiet (changes exist)
                RuntimeError("unexpected error"),  # git commit throws
            ]
            # Need to also handle the reset call
            def side_effect_fn(*args, **kwargs):
                cmd = args[0]
                if cmd == ["git", "add", "-A"]:
                    return MagicMock(returncode=0, stderr="")
                elif cmd == ["git", "diff", "--cached", "--quiet"]:
                    return MagicMock(returncode=1)
                elif cmd == ["git", "commit", "-m", "Test commit"]:
                    raise RuntimeError("unexpected error")
                elif cmd == ["git", "reset", "HEAD"]:
                    return MagicMock(returncode=0)
                return MagicMock(returncode=0)

            mock_run.side_effect = side_effect_fn
            success, output = git_commit("/fake/path", "Test commit")
            assert success is False
            assert "unexpected error" in output

            # Verify git reset HEAD was attempted
            calls = mock_run.call_args_list
            reset_calls = [c for c in calls if c[0][0] == ["git", "reset", "HEAD"]]
            assert len(reset_calls) == 1

    def test_file_not_found_after_staging_unstages(self):
        """Should try to unstage if FileNotFoundError occurs after staging."""
        call_count = [0]

        def side_effect_fn(*args, **kwargs):
            call_count[0] += 1
            cmd = args[0]
            if cmd == ["git", "add", "-A"]:
                return MagicMock(returncode=0, stderr="")
            elif cmd == ["git", "diff", "--cached", "--quiet"]:
                return MagicMock(returncode=1)  # Changes exist
            elif cmd[0] == "git" and cmd[1] == "commit":
                raise FileNotFoundError("git not found")
            elif cmd == ["git", "reset", "HEAD"]:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=side_effect_fn) as mock_run:
            success, output = git_commit("/fake/path", "Test commit")
            assert success is False
            assert "git을 찾을 수 없음" in output

            # Verify git reset HEAD was attempted
            calls = mock_run.call_args_list
            reset_calls = [c for c in calls if c[0][0] == ["git", "reset", "HEAD"]]
            assert len(reset_calls) == 1
