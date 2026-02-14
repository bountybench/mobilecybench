"""
Unit tests for supervisor_agent.py

Tests the HierarchicalAgentSystem and WorkerAgent classes.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from agent.hierarchical_agent.supervisor_agent import (
    HierarchicalAgentSystem,
    WorkerAgent,
)


class TestWorkerAgent:
    """Test suite for WorkerAgent class."""

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    def test_worker_agent_initialization(self, mock_openai):
        """Test that WorkerAgent initializes correctly."""
        mock_openai.return_value = MagicMock()

        with patch(
            "agent.hierarchical_agent.supervisor_agent.create_agent"
        ) as mock_create:
            mock_create.return_value = MagicMock()

            worker = WorkerAgent(
                name="test_worker",
                description="Test worker description",
                system_prompt="Test prompt",
                tools=[],
                model="gpt-4",
            )

            assert worker.name == "test_worker"
            assert worker.description == "Test worker description"
            assert worker.system_prompt == "Test prompt"
            assert worker.tools == []
            assert worker.model == "gpt-4"
            assert worker.agent is not None

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    def test_worker_agent_default_system_prompt(self, mock_openai):
        """Test that default system prompt is generated when none provided."""
        mock_openai.return_value = MagicMock()

        with patch(
            "agent.hierarchical_agent.supervisor_agent.create_agent"
        ) as mock_create:
            mock_create.return_value = MagicMock()

            worker = WorkerAgent(
                name="test_worker",
                description="Test description",
                tools=[],
                model="gpt-4",
            )

            assert "test_worker specialist" in worker.system_prompt

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    def test_worker_agent_invoke(self, mock_openai):
        """Test that worker can invoke tasks."""
        mock_openai.return_value = MagicMock()

        with patch(
            "agent.hierarchical_agent.supervisor_agent.create_agent"
        ) as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {
                "messages": [MagicMock(content="Test response")]
            }
            mock_create.return_value = mock_agent

            worker = WorkerAgent(
                name="test_worker",
                description="Test description",
                tools=[],
                model="gpt-4",
            )

            result = worker.invoke("Test task")

            assert result == "Test response"
            mock_agent.invoke.assert_called_once()


class TestHierarchicalAgentSystem:
    """Test suite for HierarchicalAgentSystem class."""

    def test_system_initialization(self):
        """Test that HierarchicalAgentSystem initializes correctly."""
        system = HierarchicalAgentSystem(
            supervisor_prompt="Test supervisor prompt",
            model="gpt-4",
            global_tool_limit=50,
        )

        assert system.model == "gpt-4"
        assert system.global_tool_limit == 50
        assert system.supervisor_prompt == "Test supervisor prompt"
        assert len(system.workers) == 0
        assert len(system.supervisor_tools) == 0
        assert system.supervisor is None

    def test_system_default_prompt(self):
        """Test default supervisor prompt generation."""
        system = HierarchicalAgentSystem(model="gpt-4")

        assert "supervisor agent" in system.supervisor_prompt.lower()

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_register_worker(self, mock_create, mock_openai):
        """Test worker registration."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        system = HierarchicalAgentSystem(model="gpt-4")

        worker = system.register_worker(
            name="test_worker",
            description="Test description",
            system_prompt="Test prompt",
            tools=[],
        )

        assert worker.name == "test_worker"
        assert "test_worker" in system.workers
        assert len(system.supervisor_tools) == 1

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_build_supervisor(self, mock_create, mock_openai):
        """Test supervisor building."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        system = HierarchicalAgentSystem(model="gpt-4")

        # Register a worker first
        system.register_worker(
            name="test_worker", description="Test description", tools=[]
        )

        supervisor = system.build_supervisor()

        assert supervisor is not None
        assert system.supervisor is not None
        # Supervisor should be created with workers as tools
        assert mock_create.call_count == 2  # 1 for worker, 1 for supervisor

    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_invoke_without_supervisor(self, mock_create):
        """Test that invoke raises error if supervisor not built."""
        mock_create.return_value = MagicMock()

        system = HierarchicalAgentSystem(model="gpt-4")

        with pytest.raises(RuntimeError, match="Supervisor not built"):
            system.invoke("Test input")

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_invoke_with_supervisor(self, mock_create, mock_openai):
        """Test successful invocation with supervisor."""
        mock_openai.return_value = MagicMock()
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Supervisor response")]
        }
        mock_create.return_value = mock_agent

        system = HierarchicalAgentSystem(model="gpt-4")
        system.register_worker(
            name="test_worker", description="Test description", tools=[]
        )
        system.build_supervisor()

        result = system.invoke("Test input")

        assert "messages" in result
        mock_agent.invoke.assert_called()

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_list_workers(self, mock_create, mock_openai):
        """Test listing registered workers."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        system = HierarchicalAgentSystem(model="gpt-4")

        system.register_worker(name="worker1", description="Worker 1", tools=[])
        system.register_worker(name="worker2", description="Worker 2", tools=[])

        workers = system.list_workers()

        assert len(workers) == 2
        assert "worker1" in workers
        assert "worker2" in workers

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_worker_tool_wrapping(self, mock_create, mock_openai):
        """Test that workers are properly wrapped as tools."""
        mock_openai.return_value = MagicMock()
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Worker response")]
        }
        mock_create.return_value = mock_agent

        system = HierarchicalAgentSystem(model="gpt-4")

        system.register_worker(name="test_worker", description="Test worker", tools=[])

        # The worker should be wrapped as a tool
        assert len(system.supervisor_tools) == 1
        tool = system.supervisor_tools[0]

        # Test that the tool has the expected interface (invoke/run methods)
        assert hasattr(tool, "invoke") or hasattr(tool, "run")

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_runtime_tools_integration(self, mock_create, mock_openai):
        """Test that Runtime tools are properly integrated into the system."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        # Create mock Runtime tools
        mock_runtime_tool1 = Mock()
        mock_runtime_tool1.name = "execute_command"
        mock_runtime_tool2 = Mock()
        mock_runtime_tool2.name = "get_current_ui_state"
        runtime_tools = [mock_runtime_tool1, mock_runtime_tool2]

        # Initialize system with Runtime tools
        system = HierarchicalAgentSystem(model="gpt-4", runtime_tools=runtime_tools)

        # Verify Runtime tools are stored
        assert system.runtime_tools == runtime_tools
        assert len(system.runtime_tools) == 2

        # Register a worker
        system.register_worker(name="test_worker", description="Test worker", tools=[])

        # Build supervisor
        system.build_supervisor()

        # Verify that create_agent was called with tools that include Runtime tools
        # The supervisor should be built with both worker tools and Runtime tools
        call_args = mock_create.call_args_list[-1]  # Get last call (supervisor)
        tools_passed = call_args[1]["tools"]  # Get keyword arg 'tools'

        # Should have 1 worker tool + 2 Runtime tools = 3 total
        assert len(tools_passed) == 3

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_worker_receives_runtime_tools(self, mock_create, mock_openai):
        """Test that workers receive Runtime tools from the system."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        # Create mock Runtime tools
        mock_runtime_tool = Mock()
        mock_runtime_tool.name = "execute_command"
        runtime_tools = [mock_runtime_tool]

        # Initialize system with Runtime tools
        system = HierarchicalAgentSystem(model="gpt-4", runtime_tools=runtime_tools)

        # Register a worker
        worker = system.register_worker(
            name="test_worker", description="Test worker", tools=[]
        )

        # Verify worker received Runtime tools
        assert mock_runtime_tool in worker.tools
        assert len(worker.tools) == 1  # Only Runtime tool (no custom tools)


class TestCreateAndRunSupervisorSystem:
    """Test suite for create_and_run_supervisor_system function."""

    def test_create_and_run_supervisor_system_with_metadata(self):
        """Test create_and_run_supervisor_system handles metadata correctly."""
        from agent.hierarchical_agent.supervisor_agent import (
            create_and_run_supervisor_system,
        )

        # Mock dependencies
        with patch(
            "agent.hierarchical_agent.supervisor_agent.WorkerAgent"
        ) as MockWorker, patch(
            "agent.hierarchical_agent.supervisor_agent.HierarchicalAgentSystem"
        ) as MockSystem, patch(
            "builtins.open", create=True
        ), patch(
            "utils.runtime_tools.create_runtime_tools"
        ):

            mock_worker_instance = MagicMock()
            mock_worker_instance.invoke.return_value = "Report content"
            MockWorker.return_value = mock_worker_instance

            mock_system_instance = MagicMock()
            mock_system_instance.invoke.return_value = {
                "iteration": 5,
                "messages": ["Final message"],
            }
            MockSystem.return_value = mock_system_instance

            metadata = {
                "package_name": "com.example.app",
                "container_names": ["container1"],
                "app_server": "http://app-server:8080",
            }

            create_and_run_supervisor_system(
                worker_model="gpt-4",
                hierarchy_model="gpt-4",
                max_iterations=10,
                allowed_tools=[],
                metadata=metadata,
            )

            # Verify targeted workers were created
            # We expect calls for: static_analysis, git_history, targeted_flag_txt, targeted_pwned_file, targeted_vuln_activity, targeted_container_flag_0
            # Total 6 workers
            assert MockWorker.call_count == 6

            # Check for specific targeted worker names in calls
            call_args_list = MockWorker.call_args_list
            worker_names = [call.kwargs.get("name") for call in call_args_list]

            assert "targeted_flag_txt" in worker_names
            assert "targeted_pwned_file" in worker_names
            assert "targeted_vuln_activity" in worker_names
            assert "targeted_container_flag_0" in worker_names

            # Verify APP_SERVER_ACCESS in supervisor input
            # The system.invoke is called with user_input
            invoke_call = mock_system_instance.invoke.call_args
            user_input = invoke_call.kwargs.get("user_input")
            assert "APP_SERVER_ACCESS" in user_input
            assert "http://app-server:8080" in user_input


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
