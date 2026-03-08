"""Shared pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def reset_lfs_cache():
    """Reset the cached _LFS_AVAILABLE value between tests."""
    import migrator.utils.lfs as lfs_module
    original = lfs_module._LFS_AVAILABLE
    yield
    lfs_module._LFS_AVAILABLE = original
