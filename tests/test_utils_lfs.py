"""Unit tests for migrator/utils/lfs.py"""
import subprocess
from unittest.mock import patch, MagicMock
import migrator.utils.lfs as lfs_module
from migrator.utils.lfs import _check_lfs_installed, _lfs_available


class TestCheckLfsInstalled:
    def test_returns_true_when_git_lfs_found(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "git-lfs/3.4.0 (GitHub; linux amd64; go 1.21.1)"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            assert _check_lfs_installed() is True
            mock_run.assert_called_once_with(
                ["git", "lfs", "version"],
                capture_output=True,
                text=True,
            )

    def test_returns_false_when_git_lfs_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _check_lfs_installed() is False

    def test_returns_false_when_nonzero_returncode(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            assert _check_lfs_installed() is False


class TestLfsAvailable:
    def test_caches_result_after_first_call(self):
        lfs_module._LFS_AVAILABLE = None
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "git-lfs/3.4.0"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result1 = _lfs_available()
            result2 = _lfs_available()
            assert result1 is True
            assert result2 is True
            # subprocess.run called only once thanks to the cache
            assert mock_run.call_count == 1

    def test_returns_cached_false(self):
        lfs_module._LFS_AVAILABLE = False
        with patch("subprocess.run") as mock_run:
            result = _lfs_available()
            assert result is False
            mock_run.assert_not_called()
