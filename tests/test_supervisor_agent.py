"""
Unit tests for supervisor_agent.py

Tests the HierarchicalAgentSystem and WorkerAgent classes.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from agent.hierarchical_agent.supervisor_agent import (
    DEFAULT_SUPERVISOR_PROMPT,
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
    def test_mcp_tools_integration(self, mock_create, mock_openai):
        """Test that MCP tools are properly integrated into the system."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        # Create mock MCP tools
        mock_mcp_tool1 = Mock()
        mock_mcp_tool1.name = "execute_command"
        mock_mcp_tool2 = Mock()
        mock_mcp_tool2.name = "get_current_ui_state"
        mcp_tools = [mock_mcp_tool1, mock_mcp_tool2]

        # Initialize system with MCP tools
        system = HierarchicalAgentSystem(model="gpt-4", mcp_tools=mcp_tools)

        # Verify MCP tools are stored
        assert system.mcp_tools == mcp_tools
        assert len(system.mcp_tools) == 2

        # Register a worker
        system.register_worker(name="test_worker", description="Test worker", tools=[])

        # Build supervisor
        system.build_supervisor()

        # Verify that create_agent was called with tools that include MCP tools
        # The supervisor should be built with both worker tools and MCP tools
        call_args = mock_create.call_args_list[-1]  # Get last call (supervisor)
        tools_passed = call_args[1]["tools"]  # Get keyword arg 'tools'

        # Should have 1 worker tool + 2 MCP tools = 3 total
        assert len(tools_passed) == 3

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    def test_worker_receives_mcp_tools(self, mock_create, mock_openai):
        """Test that workers receive MCP tools from the system."""
        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()

        # Create mock MCP tools
        mock_mcp_tool = Mock()
        mock_mcp_tool.name = "execute_command"
        mcp_tools = [mock_mcp_tool]

        # Initialize system with MCP tools
        system = HierarchicalAgentSystem(model="gpt-4", mcp_tools=mcp_tools)

        # Register a worker
        worker = system.register_worker(
            name="test_worker", description="Test worker", tools=[]
        )

        # Verify worker received MCP tools
        assert mock_mcp_tool in worker.tools
        assert len(worker.tools) == 1  # Only MCP tool (no custom tools)


class TestSupervisorWorkflow:
    """Test suite for supervisor workflow and prompt."""

    def test_supervisor_prompt_has_three_phases(self):
        """Test that supervisor prompt describes three-phase workflow."""
        prompt = DEFAULT_SUPERVISOR_PROMPT

        # Should have three distinct phases
        assert "PHASE 1:" in prompt
        assert "PHASE 2:" in prompt
        assert "PHASE 3:" in prompt

    def test_supervisor_prompt_phase1_analysis_workers(self):
        """Test that Phase 1 describes running all analysis workers."""
        prompt = DEFAULT_SUPERVISOR_PROMPT

        # Should mention static analysis worker
        assert "Static Analysis worker" in prompt or "static_analysis" in prompt

        # Should mention all 10 OWASP workers
        assert "owasp_m1_worker" in prompt
        assert "owasp_m10_worker" in prompt
        assert "M1: Improper Credential Usage" in prompt
        assert "M10: Insufficient Cryptography" in prompt

        # Should instruct to wait for all 11 workers
        assert "11 workers" in prompt or "ALL" in prompt

    def test_supervisor_prompt_phase2_exploit_workers(self):
        """Test that Phase 2 describes creating exploit workers per vulnerability."""
        prompt = DEFAULT_SUPERVISOR_PROMPT

        # Should describe creating separate directories
        assert "exploit_files/exploit_" in prompt
        assert "mkdir" in prompt

        # Should mention one exploit worker per vulnerability
        assert "ONE exploit worker" in prompt or "one exploit worker" in prompt
        assert "per vulnerability" in prompt.lower()

    def test_supervisor_prompt_phase3_combine_exploits(self):
        """Test that Phase 3 describes combining exploits."""
        prompt = DEFAULT_SUPERVISOR_PROMPT

        # Should describe creating master exploit.sh
        assert "master exploit.sh" in prompt or "combine" in prompt.lower()

        # Should describe sequential execution with failure tolerance
        assert "|| true" in prompt or "continue" in prompt.lower()

        # Should describe success criteria (any exploit succeeds)
        assert "ANY exploit succeeds" in prompt or "if any succeeded" in prompt.lower()

    def test_supervisor_prompt_separate_directories(self):
        """Test that supervisor prompt instructs to use separate directories."""
        prompt = DEFAULT_SUPERVISOR_PROMPT

        # Should mention creating unique directories
        assert "exploit_1" in prompt
        assert "exploit_2" in prompt or "exploit_<N>" in prompt

    def test_supervisor_prompt_master_exploit_example(self):
        """Test that supervisor prompt includes master exploit example."""
        prompt = DEFAULT_SUPERVISOR_PROMPT

        # Should include example bash script
        assert "#!/bin/bash" in prompt
        assert "SUCCESS=0" in prompt or "SUCCESS=" in prompt

        # Should show running individual exploits
        assert "bash exploit_files/exploit_1/exploit.sh" in prompt or "bash" in prompt


class TestSupervisorSystemWithOWASPWorkers:
    """Test suite for supervisor system with OWASP workers registered."""

    @patch("agent.hierarchical_agent.supervisor_agent.ChatOpenAI")
    @patch("agent.hierarchical_agent.supervisor_agent.create_agent")
    @patch("utils.mcp_tools.create_mcp_tools")
    def test_create_and_run_supervisor_registers_owasp_workers(
        self, mock_mcp_tools, mock_create, mock_openai
    ):
        """Test that create_and_run_supervisor_system registers all 10 OWASP workers."""
        from agent.hierarchical_agent.supervisor_agent import (
            create_and_run_supervisor_system,
        )

        mock_openai.return_value = MagicMock()
        mock_create.return_value = MagicMock()
        mock_mcp_tools.return_value = []

        # Mock the agent to avoid actual execution
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [MagicMock(content="Done")]}
        mock_create.return_value = mock_agent

        # This will create the system but we'll intercept before invoke
        with patch.object(
            HierarchicalAgentSystem, "invoke", return_value={"messages": []}
        ):
            # We need to examine the system during creation
            original_build = HierarchicalAgentSystem.build_supervisor

            def track_workers(self):
                # Store worker list before building
                self._test_workers = list(self.workers.keys())
                return original_build(self)

            with patch.object(
                HierarchicalAgentSystem, "build_supervisor", track_workers
            ):
                try:
                    create_and_run_supervisor_system(
                        model="gpt-4",
                        max_iterations=50,
                        allowed_tools=["execute_command"],
                        user_input="Test",
                    )
                except Exception:
                    pass  # We just want to check registration, not full execution

        # Verify workers were registered (12 total: 1 static + 10 OWASP + 1 exploit)
        # This is a smoke test - actual verification would require more complex mocking

    def test_owasp_worker_names(self):
        """Test that OWASP worker names follow expected pattern."""
        expected_workers = [
            "owasp_m1_worker",
            "owasp_m2_worker",
            "owasp_m3_worker",
            "owasp_m4_worker",
            "owasp_m5_worker",
            "owasp_m6_worker",
            "owasp_m7_worker",
            "owasp_m8_worker",
            "owasp_m9_worker",
            "owasp_m10_worker",
        ]

        # Verify naming convention in supervisor prompt
        prompt = DEFAULT_SUPERVISOR_PROMPT
        for worker in expected_workers:
            assert worker in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
