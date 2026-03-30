"""Tests for engine.py — core experiment loop."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoresearch.engine import (
    AgentResult,
    AgentRunner,
    ClaudeCodeRunner,
    EngineError,
    EscalationState,
    RunResult,
    _parse_budget,
    _target_reached,
    run_marker,
)
from autoresearch.marker import (
    Escalation,
    Guard,
    LoopConfig,
    Marker,
    MarkerStatus,
    Metric,
    MetricDirection,
    ResultsConfig,
    Schedule,
    Target,
)
from autoresearch.metrics import HarnessResult, GuardResult
from autoresearch.state import AppState, DaemonState, TrackedMarker


# --- Fixtures and helpers ---


class FakeAgentRunner(AgentRunner):
    """Test double that returns predefined results in sequence."""

    def __init__(self, results: list[AgentResult]):
        self._results = list(results)
        self.call_count = 0
        self.calls: list[tuple[Path, str, str]] = []

    def invoke(self, worktree_path: Path, program: str, budget: str) -> AgentResult:
        self.calls.append((worktree_path, program, budget))
        result = self._results[min(self.call_count, len(self._results) - 1)]
        self.call_count += 1
        return result


def _make_marker(**overrides) -> Marker:
    defaults = {
        "name": "test-marker",
        "description": "Test",
        "status": MarkerStatus.ACTIVE,
        "target": Target(
            mutable=["src/main.py"],
            immutable=["tests/test_main.py"],
        ),
        "metric": Metric(
            command="echo '5 passed'",
            extract=r"grep -oP '\d+(?= passed)'",
            direction=MetricDirection.HIGHER,
            baseline=3,
        ),
        "loop": LoopConfig(max_experiments=5, budget_per_experiment="1m"),
        "escalation": Escalation(),
        "schedule": Schedule(),
        "results": ResultsConfig(),
    }
    defaults.update(overrides)
    return Marker(**defaults)


def _make_state() -> AppState:
    return AppState(markers=[], daemon=DaemonState())


def _make_tracked(marker_name: str = "test-marker") -> TrackedMarker:
    return TrackedMarker(
        id=f"test-repo:{marker_name}",
        repo_path="/tmp/test-repo",
        repo_name="test-repo",
        marker_name=marker_name,
    )


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("x = 1\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("pass\n")
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True, env=env,
    )
    return repo


# --- EscalationState tests ---


class TestEscalationState:
    def test_initial_state(self):
        esc = EscalationState()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 0
        assert esc.total_pivots == 0

    def test_on_keep_resets(self):
        esc = EscalationState()
        esc.consecutive_failures = 4
        esc.escalation_level = "refine"
        esc.on_keep()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 0

    def test_refine_at_3_failures(self):
        esc = EscalationState()
        for _ in range(3):
            esc.on_discard()
        assert esc.escalation_level == "refine"

    def test_pivot_at_5_failures(self):
        esc = EscalationState()
        for _ in range(5):
            esc.on_discard()
        assert esc.escalation_level == "pivot"
        assert esc.total_pivots == 1
        assert esc.consecutive_failures == 0  # reset after pivot

    def test_search_after_2_pivots_without_progress(self):
        esc = EscalationState()
        # First pivot
        for _ in range(5):
            esc.on_discard()
        assert esc.total_pivots == 1
        # Second pivot
        for _ in range(5):
            esc.on_discard()
        assert esc.total_pivots == 2
        assert esc.escalation_level == "search"

    def test_halt_after_3_pivots(self):
        esc = EscalationState()
        # 3 pivots
        for _ in range(5):
            esc.on_discard()  # pivot 1
        for _ in range(5):
            esc.on_discard()  # pivot 2 + search
        for _ in range(5):
            esc.on_discard()  # pivot 3
        assert esc.total_pivots == 3
        assert esc.escalation_level == "halt"

    def test_keep_resets_pivots_without_progress(self):
        esc = EscalationState()
        for _ in range(5):
            esc.on_discard()  # pivot 1
        assert esc.pivots_without_progress == 1
        esc.on_keep()
        assert esc.pivots_without_progress == 0

    def test_crash_counts_as_failure(self):
        esc = EscalationState()
        for _ in range(3):
            esc.on_crash()
        assert esc.escalation_level == "refine"

    def test_custom_thresholds(self):
        esc = EscalationState(refine_after=2, pivot_after=3)
        for _ in range(2):
            esc.on_discard()
        assert esc.escalation_level == "refine"
        esc.on_discard()
        assert esc.escalation_level == "pivot"


# --- ParseBudget tests ---


class TestParseBudget:
    def test_minutes(self):
        assert _parse_budget("10m") == 600

    def test_hours(self):
        assert _parse_budget("1h") == 3600

    def test_seconds(self):
        assert _parse_budget("30s") == 30

    def test_default_minutes(self):
        assert _parse_budget("5") == 300

    def test_invalid_returns_default(self):
        assert _parse_budget("abc") == 600


# --- TargetReached tests ---


class TestTargetReached:
    def test_higher_reached(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.HIGHER, baseline=3, target=10,
        ))
        assert _target_reached(marker, 10) is True
        assert _target_reached(marker, 11) is True

    def test_higher_not_reached(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.HIGHER, baseline=3, target=10,
        ))
        assert _target_reached(marker, 9) is False

    def test_lower_reached(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.LOWER, baseline=100, target=50,
        ))
        assert _target_reached(marker, 50) is True
        assert _target_reached(marker, 40) is True

    def test_no_target(self):
        marker = _make_marker()
        assert _target_reached(marker, 999) is False


# --- run_marker integration tests ---


class TestRunMarker:
    def test_not_active_raises(self, git_repo, tmp_path):
        marker = _make_marker(status=MarkerStatus.SKIP)
        runner = FakeAgentRunner([AgentResult(True, "test", 0, "")])
        with pytest.raises(EngineError, match="not active"):
            run_marker(
                git_repo, marker, _make_state(), _make_tracked(),
                runner, worktree_base=tmp_path / "wt",
            )

    def test_bad_repo_raises(self, tmp_path):
        marker = _make_marker()
        runner = FakeAgentRunner([AgentResult(True, "test", 0, "")])
        with pytest.raises(EngineError, match="does not exist"):
            run_marker(
                tmp_path / "nonexistent", marker, _make_state(), _make_tracked(),
                runner, worktree_base=tmp_path / "wt",
            )

    @patch("autoresearch.engine.run_harness")
    def test_happy_path_keeps_improved(self, mock_harness, git_repo, tmp_path):
        """Agent makes change, metric improves -> keep."""
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        # Agent that makes a real file change
        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count + 1}\n")
                return AgentResult(True, f"change x to {self.call_count + 1}", 0, "")

        marker = _make_marker(loop=LoopConfig(max_experiments=2, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.kept >= 1
        assert result.final_metric == 5.0
        assert result.final_status == "budget_exhausted"

    @patch("autoresearch.engine.run_harness")
    def test_discard_when_not_improved(self, mock_harness, git_repo, tmp_path):
        """Metric doesn't improve -> discard."""
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="2 passed", stderr="",
            metric=2.0, log_path=tmp_path / "run.log",
        )

        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count}\n")
                return AgentResult(True, "regressed", 0, "")

        marker = _make_marker(loop=LoopConfig(max_experiments=2, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.discarded == 2
        assert result.kept == 0

    @patch("autoresearch.engine.run_harness")
    def test_crash_handling(self, mock_harness, git_repo, tmp_path):
        """Harness returns None metric -> crash."""
        mock_harness.return_value = HarnessResult(
            exit_code=1, stdout="error", stderr="",
            metric=None, log_path=tmp_path / "run.log",
        )

        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                # Start from 10 to avoid collision with initial content (x = 1)
                (wt / "src" / "main.py").write_text(f"x = {self.call_count + 10}\n")
                return AgentResult(True, "crashed change", 0, "")

        marker = _make_marker(loop=LoopConfig(max_experiments=2, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.crashed == 2

    def test_no_changes_is_discard(self, git_repo, tmp_path):
        """Agent succeeds but makes no file changes -> discard."""
        runner = FakeAgentRunner([
            AgentResult(True, "no-op", 0, ""),
        ])
        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            runner, worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.discarded == 1
        assert result.kept == 0

    @patch("autoresearch.engine.run_harness")
    def test_escalation_to_halt(self, mock_harness, git_repo, tmp_path):
        """Enough failures trigger halt."""
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="2", stderr="",
            metric=2.0, log_path=tmp_path / "run.log",
        )

        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count}\n")
                return AgentResult(True, "attempt", 0, "")

        # 3 pivots at 5 failures each = 15 failures to halt
        marker = _make_marker(loop=LoopConfig(max_experiments=20, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.final_status == "halted"

    @patch("autoresearch.engine.run_harness")
    def test_target_reached_completes(self, mock_harness, git_repo, tmp_path):
        """Reaching target metric completes the run."""
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="10 passed", stderr="",
            metric=10.0, log_path=tmp_path / "run.log",
        )

        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count}\n")
                return AgentResult(True, "big improvement", 0, "")

        marker = _make_marker(
            metric=Metric(
                command="echo '10 passed'",
                extract=r"grep -oP '\d+(?= passed)'",
                direction=MetricDirection.HIGHER,
                baseline=3,
                target=10,
            ),
            loop=LoopConfig(max_experiments=5, budget_per_experiment="1m"),
        )
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.final_status == "completed"
        assert result.kept >= 1

    @patch("autoresearch.engine.run_harness")
    @patch("autoresearch.engine.run_guard")
    def test_guard_failure_discards(self, mock_guard, mock_harness, git_repo, tmp_path):
        """Guard failure after rework exhaustion -> discard."""
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        mock_guard.return_value = GuardResult(passed=False, value=10.0, output="failed")

        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count}\n")
                return AgentResult(True, "guard test", 0, "")

        marker = _make_marker(
            guard=Guard(command="pytest -q", extract=None, threshold=None, rework_attempts=1),
            loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"),
        )
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.discarded == 1


    @patch("autoresearch.engine.remove_worktree")
    @patch("autoresearch.engine.create_worktree")
    @patch("autoresearch.engine.git_head_short", return_value="abc1234")
    @patch("autoresearch.engine.git_reset_hard")
    @patch("autoresearch.engine.git_commit", return_value="abc1234")
    @patch("autoresearch.engine.run_harness")
    @patch("autoresearch.engine.run_guard")
    def test_guard_failure_rework_succeeds(self, mock_guard, mock_harness, mock_commit, mock_reset, mock_head, mock_create_wt, mock_rm_wt, git_repo, tmp_path):
        """Guard failure -> rework fixes it -> keep."""
        wt_path = tmp_path / "wt" / "test-marker"
        wt_path.mkdir(parents=True, exist_ok=True)
        from autoresearch.worktree import WorktreeInfo
        mock_create_wt.return_value = WorktreeInfo(path=wt_path, branch="autoresearch/test", base_commit="abc1234")
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        # First guard fails, rework guard passes
        mock_guard.side_effect = [
            GuardResult(passed=False, value=10.0, output="failed"),
            GuardResult(passed=True, value=10.0, output="passed"),
        ]

        class CountingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                return AgentResult(True, "rework test", 0, "")

        marker = _make_marker(
            guard=Guard(command="pytest -q", extract=None, threshold=None, rework_attempts=2),
            loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"),
        )
        agent = CountingAgent()
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            agent, worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert mock_guard.call_count == 2  # Main guard + rework guard
        assert agent.call_count >= 2  # Initial + rework invoke

    @patch("autoresearch.engine.remove_worktree")
    @patch("autoresearch.engine.create_worktree")
    @patch("autoresearch.engine.git_head_short", return_value="abc1234")
    @patch("autoresearch.engine.git_reset_hard")
    @patch("autoresearch.engine.git_commit", return_value="abc1234")
    @patch("autoresearch.engine.run_harness")
    @patch("autoresearch.engine.run_guard")
    def test_guard_rework_all_attempts_fail(self, mock_guard, mock_harness, mock_commit, mock_reset, mock_head, mock_create_wt, mock_rm_wt, git_repo, tmp_path):
        """Guard failure -> all rework attempts fail -> discard."""
        wt_path = tmp_path / "wt" / "test-marker"
        wt_path.mkdir(parents=True, exist_ok=True)
        from autoresearch.worktree import WorktreeInfo
        mock_create_wt.return_value = WorktreeInfo(path=wt_path, branch="autoresearch/test", base_commit="abc1234")
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        mock_guard.return_value = GuardResult(passed=False, value=10.0, output="failed")

        class CountingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                return AgentResult(True, "rework test", 0, "")

        marker = _make_marker(
            guard=Guard(command="pytest -q", extract=None, threshold=None, rework_attempts=3),
            loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"),
        )
        agent = CountingAgent()
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            agent, worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.discarded >= 1

    def test_state_updated_after_run(self, git_repo, tmp_path):
        """Tracked marker state is updated after the run."""
        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count}\n")
                return AgentResult(True, "update", 0, "")

        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))
        tracked = _make_tracked()
        state = _make_state()

        with patch("autoresearch.engine.run_harness") as mock_h:
            mock_h.return_value = HarnessResult(
                exit_code=0, stdout="5 passed", stderr="",
                metric=5.0, log_path=tmp_path / "run.log",
            )
            run_marker(
                git_repo, marker, state, tracked,
                WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
            )

        assert tracked.last_run is not None
        assert tracked.last_run_experiments == 1
        assert tracked.branch is not None


# --- FakeAgentRunner self-test ---


class TestFakeAgentRunner:
    def test_returns_results_in_order(self):
        results = [
            AgentResult(True, "first", 0, ""),
            AgentResult(False, "second", 1, ""),
        ]
        runner = FakeAgentRunner(results)
        r1 = runner.invoke(Path("/tmp"), "prog", "5m")
        r2 = runner.invoke(Path("/tmp"), "prog", "5m")
        assert r1.description == "first"
        assert r2.description == "second"

    def test_repeats_last_result(self):
        runner = FakeAgentRunner([AgentResult(True, "only", 0, "")])
        runner.invoke(Path("/tmp"), "prog", "5m")
        r2 = runner.invoke(Path("/tmp"), "prog", "5m")
        assert r2.description == "only"

    def test_tracks_calls(self):
        runner = FakeAgentRunner([AgentResult(True, "t", 0, "")])
        runner.invoke(Path("/a"), "p1", "5m")
        runner.invoke(Path("/b"), "p2", "10m")
        assert runner.call_count == 2
        assert len(runner.calls) == 2
