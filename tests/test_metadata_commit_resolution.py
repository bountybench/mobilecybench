"""Tests for metadata commit resolution helper."""

import pytest

from utils.metadata_utils import get_metadata_commit


class TestGetMetadataCommit:
    def test_commit_version_only(self):
        metadata = {"commit_version": "abc123"}
        assert get_metadata_commit(metadata) == "abc123"

    def test_commit_id_only(self):
        metadata = {"commit_id": "def456"}
        assert get_metadata_commit(metadata) == "def456"

    def test_both_present_commit_version_wins(self):
        metadata = {"commit_version": "abc123", "commit_id": "def456"}
        assert get_metadata_commit(metadata) == "abc123"

    def test_neither_present_raises(self):
        with pytest.raises(ValueError, match="commit_version"):
            get_metadata_commit({})

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="commit_version"):
            get_metadata_commit({"commit_version": ""})

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="commit_version"):
            get_metadata_commit({"commit_version": "   "})

    def test_strips_whitespace(self):
        metadata = {"commit_version": "  abc123  "}
        assert get_metadata_commit(metadata) == "abc123"

    def test_commit_version_empty_falls_back_to_commit_id(self):
        metadata = {"commit_version": "", "commit_id": "def456"}
        assert get_metadata_commit(metadata) == "def456"
