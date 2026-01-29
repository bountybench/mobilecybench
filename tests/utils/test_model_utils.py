"""Unit tests for utils/model_utils.py"""

from utils.model_utils import FORMAT_REINFORCEMENT_MESSAGE


class TestFormatReinforcementMessage:
    """Tests for the FORMAT_REINFORCEMENT_MESSAGE constant."""

    def test_message_contains_required_sections(self):
        assert "Reflection:" in FORMAT_REINFORCEMENT_MESSAGE
        assert "Plan and Status:" in FORMAT_REINFORCEMENT_MESSAGE
        assert "Thought:" in FORMAT_REINFORCEMENT_MESSAGE
        assert "Log:" in FORMAT_REINFORCEMENT_MESSAGE
        assert "Command:" in FORMAT_REINFORCEMENT_MESSAGE

    def test_message_is_not_empty(self):
        assert len(FORMAT_REINFORCEMENT_MESSAGE) > 100  # Reasonable length
