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
    _extract_description,
    _format_results_for_program,
    _parse_budget,
    _reset_to_before_commit,
    _target_reached,
    _write_discard_idea,
    _write_telemetry_feedback,
    get_agent_runner,
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


# --- _format_results_for_program tests ---


class TestFormatResultsForProgram:
    def _make_result(self, commit="abc1234", metric=5.0, guard="pass", status="keep",
                     confidence="1.5x", description="test"):
        from autoresearch.results import ExperimentResult
        return ExperimentResult(
            commit=commit, metric=metric, guard=guard,
            status=status, confidence=confidence, description=description,
        )

    def test_empty_returns_empty_string(self):
        assert _format_results_for_program([]) == ""

    def test_single_result_tab_separated(self):
        r = self._make_result()
        out = _format_results_for_program([r])
        assert "abc1234" in out
        assert "5.0" in out
        assert "keep" in out
        parts = out.split("\t")
        assert len(parts) == 6

    def test_multiple_results_one_line_each(self):
        results = [
            self._make_result(commit="aaa", metric=3.0, status="discard"),
            self._make_result(commit="bbb", metric=7.0, status="keep"),
        ]
        out = _format_results_for_program(results)
        lines = out.strip().splitlines()
        assert len(lines) == 2
        assert "aaa" in lines[0]
        assert "bbb" in lines[1]

    def test_description_included(self):
        r = self._make_result(description="my experiment description")
        out = _format_results_for_program([r])
        assert "my experiment description" in out


# --- _extract_description tests ---


class TestExtractDescription:
    def test_returns_last_meaningful_line(self):
        output = "some output\nThis is the result\n"
        assert _extract_description(output) == "This is the result"

    def test_skips_timestamp_lines(self):
        output = "2026-03-30 12:00:00 INFO something\nActual description"
        assert _extract_description(output) == "Actual description"

    def test_skips_empty_lines(self):
        output = "Real content\n\n   \n"
        assert _extract_description(output) == "Real content"

    def test_empty_string_returns_default(self):
        assert _extract_description("") == "experiment"

    def test_none_like_empty_returns_default(self):
        assert _extract_description(None) == "experiment"

    def test_skips_short_lines(self):
        output = "ok\nA meaningful longer description here"
        assert _extract_description(output) == "A meaningful longer description here"

    def test_truncates_long_description(self):
        long_line = "x" * 300
        output = f"preamble\n{long_line}"
        result = _extract_description(output)
        assert len(result) <= 200

    def test_skips_divider_lines(self):
        output = "real result\n===========================\n"
        assert _extract_description(output) == "real result"

    def test_skips_log_bracket_prefix(self):
        output = "[INFO] something happened\nActual result"
        assert _extract_description(output) == "Actual result"

    def test_skips_shell_prompt(self):
        output = "$ echo done\nDone"
        assert _extract_description(output) == "Done"

    def test_returns_only_valid_line_when_all_else_metadata(self):
        output = "2026-01-01 00:00:00 start\nReal description line\n==="
        assert _extract_description(output) == "Real description line"

    def test_only_short_lines_returns_default(self):
        # All lines are 2 chars or less
        output = "ab\nxy\nz"
        assert _extract_description(output) == "experiment"


# --- _write_discard_idea tests ---


class TestWriteDiscardIdea:
    def test_writes_idea_to_backlog(self, tmp_path):
        _write_discard_idea(tmp_path, "my-marker", "tried adding caching", 4.5)
        ideas_path = tmp_path / ".autoresearch" / "my-marker" / "ideas.md"
        assert ideas_path.exists()
        content = ideas_path.read_text()
        assert "tried adding caching" in content
        assert "4.5" in content

    def test_oserror_silenced(self, tmp_path):
        # Write to a path that can't be created — should not raise
        _write_discard_idea(Path("/nonexistent/path"), "marker", "desc", 1.0)

    def test_empty_description(self, tmp_path):
        _write_discard_idea(tmp_path, "my-marker", "", 2.0)
        ideas_path = tmp_path / ".autoresearch" / "my-marker" / "ideas.md"
        assert ideas_path.exists()


# --- _write_telemetry_feedback tests ---


class TestWriteTelemetryFeedback:
    def _make_agent_result(self, telemetry=None):
        return AgentResult(True, "test", 0, "", telemetry=telemetry)

    def test_no_telemetry_does_nothing(self, tmp_path):
        result = self._make_agent_result(telemetry=None)
        _write_telemetry_feedback(tmp_path, "marker", result)
        # No ideas file created
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        assert not ideas_path.exists()

    def test_telemetry_with_errors_writes_idea(self, tmp_path):
        tel = MagicMock()
        tel.errors = ["error A", "error B"]
        tel.permission_denials = []
        result = self._make_agent_result(telemetry=tel)
        _write_telemetry_feedback(tmp_path, "marker", result)
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        assert ideas_path.exists()
        content = ideas_path.read_text()
        assert "error A" in content

    def test_telemetry_with_permission_denials_writes_idea(self, tmp_path):
        tel = MagicMock()
        tel.errors = []
        tel.permission_denials = ["Edit /src/foo.py denied"]
        result = self._make_agent_result(telemetry=tel)
        _write_telemetry_feedback(tmp_path, "marker", result)
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        assert ideas_path.exists()
        content = ideas_path.read_text()
        assert "Permission denied" in content

    def test_telemetry_without_attrs_does_nothing(self, tmp_path):
        # Plain object with no errors/permission_denials attributes
        tel = object()
        result = self._make_agent_result(telemetry=tel)
        _write_telemetry_feedback(tmp_path, "marker", result)


# --- _reset_to_before_commit tests ---


class TestResetToBeforeCommit:
    @patch("autoresearch.engine.git_reset_hard")
    def test_calls_reset_with_parent(self, mock_reset):
        _reset_to_before_commit(Path("/tmp/wt"), "abc1234")
        mock_reset.assert_called_once_with(Path("/tmp/wt"), "abc1234~1")

    @patch("autoresearch.engine.git_reset_hard")
    def test_swallows_git_error(self, mock_reset):
        from autoresearch.worktree import GitError
        mock_reset.side_effect = GitError("git error")
        # Should not raise
        _reset_to_before_commit(Path("/tmp/wt"), "abc1234")


# --- get_agent_runner tests ---


class TestGetAgentRunner:
    def test_returns_claude_code_runner(self):
        marker = _make_marker()
        runner = get_agent_runner(marker)
        assert isinstance(runner, ClaudeCodeRunner)

    def test_runner_holds_marker(self):
        marker = _make_marker()
        runner = get_agent_runner(marker)
        assert runner.marker is marker


# --- EscalationState additional edge cases ---


class TestEscalationStateEdgeCases:
    def test_on_keep_updates_last_kept_experiment(self):
        esc = EscalationState()
        esc.current_experiment = 5
        esc.on_keep()
        assert esc.last_kept_experiment == 5

    def test_mixed_crash_and_discard_counts_together(self):
        esc = EscalationState()
        esc.on_crash()
        esc.on_crash()
        esc.on_discard()
        assert esc.escalation_level == "refine"
        assert esc.consecutive_failures == 3

    def test_keep_after_refine_resets_to_normal(self):
        esc = EscalationState()
        for _ in range(3):
            esc.on_discard()
        assert esc.escalation_level == "refine"
        esc.on_keep()
        assert esc.escalation_level == "normal"

    def test_evaluate_below_refine_threshold_stays_normal(self):
        esc = EscalationState()
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 2

    def test_search_resets_pivots_without_progress(self):
        esc = EscalationState()
        # Two pivots trigger "search" and reset pivots_without_progress to 0
        for _ in range(5):
            esc.on_discard()  # pivot 1
        for _ in range(5):
            esc.on_discard()  # pivot 2 + search
        assert esc.escalation_level == "search"


# --- ClaudeCodeRunner.invoke tests ---


class TestClaudeCodeRunnerInvoke:
    def _make_paths(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs_dir,
            stream_log_path=logs_dir / "run-20260101-000000.jsonl",
            debug_log_path=logs_dir / "debug-20260101-000000.log",
        )

    @patch("autoresearch.engine.shutil.which", return_value=None)
    def test_raises_if_claude_not_found(self, mock_which, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        from autoresearch.engine import AgentError
        with pytest.raises(AgentError, match="claude"):
            runner.invoke(tmp_path, "program", "5m")

    @patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude")
    def test_success_returns_agent_result(self, mock_which, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        paths = self._make_paths(tmp_path)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"type":"result","subtype":"success"}\n'

        with (
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", return_value=mock_proc),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value="done"),
        ):
            result = runner.invoke(tmp_path, "program", "5m")

        assert result.success is True
        assert result.exit_code == 0

    @patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude")
    def test_nonzero_exit_returns_failure(self, mock_which, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        paths = self._make_paths(tmp_path)

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with (
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", return_value=mock_proc),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            result = runner.invoke(tmp_path, "program", "5m")

        assert result.success is False
        assert result.exit_code == 1

    @patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude")
    def test_timeout_returns_failure(self, mock_which, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        paths = self._make_paths(tmp_path)

        timeout_exc = subprocess.TimeoutExpired(cmd=["claude"], timeout=300)
        timeout_exc.stdout = b"partial output"

        with (
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=timeout_exc),
        ):
            result = runner.invoke(tmp_path, "program", "5m")

        assert result.success is False
        assert result.exit_code == -1
        assert "partial output" in result.output

    @patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude")
    def test_timeout_no_stdout(self, mock_which, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        paths = self._make_paths(tmp_path)

        timeout_exc = subprocess.TimeoutExpired(cmd=["claude"], timeout=300)
        timeout_exc.stdout = None

        with (
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=timeout_exc),
        ):
            result = runner.invoke(tmp_path, "program", "5m")

        assert result.output == "TIMEOUT"

    @patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude")
    def test_dot_env_loaded(self, mock_which, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        paths = self._make_paths(tmp_path)

        # Write a .env file in the agent dir
        (tmp_path / ".env").write_text("MY_VAR=hello\n# comment\n\nBAD_LINE\n")

        captured_env = {}

        def capture_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        with (
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=capture_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            runner.invoke(tmp_path, "program", "5m")

        assert captured_env.get("MY_VAR") == "hello"


# --- _write_telemetry_feedback exception coverage ---


class TestWriteTelemetryFeedbackException:
    def test_swallows_oserror_from_append_idea(self, tmp_path):
        from autoresearch.engine import _write_telemetry_feedback

        telem = MagicMock()
        telem.errors = ["err1"]
        telem.permission_denials = []
        agent_result = AgentResult(True, "desc", 0, "", telemetry=telem)

        with patch("autoresearch.engine.append_idea", side_effect=OSError("disk full")):
            # Should not raise
            _write_telemetry_feedback(tmp_path, "test-marker", agent_result)

    def test_swallows_valueerror_from_append_idea(self, tmp_path):
        from autoresearch.engine import _write_telemetry_feedback

        telem = MagicMock()
        telem.errors = []
        telem.permission_denials = ["denied1"]
        agent_result = AgentResult(True, "desc", 0, "", telemetry=telem)

        with patch("autoresearch.engine.append_idea", side_effect=ValueError("bad path")):
            _write_telemetry_feedback(tmp_path, "test-marker", agent_result)


# --- run_marker cleanup_worktree with GitError ---


class TestRunMarkerCleanup:
    @patch("autoresearch.engine.run_harness")
    def test_cleanup_worktree_git_error_logged(self, mock_harness, git_repo, tmp_path):
        """remove_worktree raising GitError should be caught, not propagate."""
        from autoresearch.worktree import GitError as WtGitError

        mock_harness.return_value = MagicMock(
            exit_code=0, stdout="3 passed", stderr="", metric=3.0
        )

        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))
        runner = FakeAgentRunner([AgentResult(True, "done", 0, "")])

        with (
            patch("autoresearch.engine.remove_worktree", side_effect=WtGitError("rm fail")),
            patch("autoresearch.engine.git_commit", return_value="abc1234"),
            patch("autoresearch.engine.git_head_short", return_value="abc1234"),
        ):
            # Should not raise even if remove_worktree fails
            result = run_marker(
                git_repo, marker, _make_state(), _make_tracked(),
                runner, worktree_base=tmp_path / "wt",
                cleanup_worktree=True,
            )
        assert result is not None


# --- ClaudeCodeRunner cmd-building branches ---


class TestClaudeCodeRunnerCmdBranches:
    """Verify that optional agent config fields are reflected in the subprocess command."""

    def _make_paths(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs_dir,
            stream_log_path=logs_dir / "run-20260101-000000.jsonl",
            debug_log_path=logs_dir / "debug-20260101-000000.log",
        )

    def _invoke_capturing_cmd(self, marker, tmp_path):
        """Invoke the runner and return the command that was passed to subprocess.run."""
        paths = self._make_paths(tmp_path)
        captured = {}

        def capture_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=capture_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")
        return captured["cmd"]

    def test_effort_flag_added(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(effort="high"))
        cmd = self._invoke_capturing_cmd(marker, tmp_path)
        assert "--effort" in cmd
        assert "high" in cmd

    def test_no_effort_flag_when_empty(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(effort=""))
        cmd = self._invoke_capturing_cmd(marker, tmp_path)
        assert "--effort" not in cmd

    def test_allowed_tools_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(allowed_tools=["Bash(pytest:*)"]))
        cmd = self._invoke_capturing_cmd(marker, tmp_path)
        assert "--allowedTools" in cmd
        assert "Bash(pytest:*)" in cmd

    def test_disallowed_tools_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(disallowed_tools=["Bash(rm:*)"]))
        cmd = self._invoke_capturing_cmd(marker, tmp_path)
        assert "--disallowedTools" in cmd
        assert "Bash(rm:*)" in cmd

    def test_extra_flags_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(extra_flags=["--dangerously-skip-permissions"]))
        cmd = self._invoke_capturing_cmd(marker, tmp_path)
        assert "--dangerously-skip-permissions" in cmd

    def test_model_from_loop_when_agent_model_empty(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(
            agent=AgentConfig(model=""),
            loop=LoopConfig(model="opus", budget_per_experiment="5m"),
        )
        cmd = self._invoke_capturing_cmd(marker, tmp_path)
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"


# --- run_marker with state_path ---


class TestRunMarkerStatePath:
    @patch("autoresearch.engine.run_harness")
    def test_saves_state_when_state_path_provided(self, mock_harness, git_repo, tmp_path):
        """When state_path is provided, save_state is called."""
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        state_path = tmp_path / "state.json"
        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))

        class WriteAgent(AgentRunner):
            def invoke(self, wt, prog, budget):
                (wt / "src" / "main.py").write_text("x = 99\n")
                return AgentResult(True, "wrote", 0, "")

        run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WriteAgent(), worktree_base=tmp_path / "wt",
            cleanup_worktree=False, state_path=state_path,
        )
        assert state_path.is_file()


# --- run_marker cleanup_worktree=False does not call remove_worktree ---


class TestRunMarkerNoCleanup:
    @patch("autoresearch.engine.run_harness")
    @patch("autoresearch.engine.remove_worktree")
    def test_no_cleanup_skips_remove_worktree(self, mock_remove, mock_harness, git_repo, tmp_path):
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))

        class WriteAgent(AgentRunner):
            def invoke(self, wt, prog, budget):
                (wt / "src" / "main.py").write_text("x = 7\n")
                return AgentResult(True, "wrote", 0, "")

        run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WriteAgent(), worktree_base=tmp_path / "wt",
            cleanup_worktree=False,
        )
        mock_remove.assert_not_called()


# --- _handle_guard_failure when agent returns success=False ---


class TestHandleGuardFailureAgentFails:
    @patch("autoresearch.engine.remove_worktree")
    @patch("autoresearch.engine.create_worktree")
    @patch("autoresearch.engine.git_head_short", return_value="abc1234")
    @patch("autoresearch.engine.git_reset_hard")
    @patch("autoresearch.engine.git_commit", return_value="abc1234")
    @patch("autoresearch.engine.run_harness")
    @patch("autoresearch.engine.run_guard")
    def test_agent_fail_during_rework_does_not_commit(
        self, mock_guard, mock_harness, mock_commit, mock_reset,
        mock_head, mock_create_wt, mock_rm_wt, git_repo, tmp_path
    ):
        """If the rework agent returns success=False, no extra commit is made."""
        wt_path = tmp_path / "wt" / "test-marker"
        wt_path.mkdir(parents=True, exist_ok=True)
        from autoresearch.worktree import WorktreeInfo
        mock_create_wt.return_value = WorktreeInfo(
            path=wt_path, branch="autoresearch/test", base_commit="abc1234"
        )
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="5 passed", stderr="",
            metric=5.0, log_path=tmp_path / "run.log",
        )
        # Guard always fails
        mock_guard.return_value = GuardResult(passed=False, value=0.0, output="failed")

        class FailingReworkAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                # First call (initial run) succeeds; rework call fails
                if self.call_count == 1:
                    return AgentResult(True, "initial", 0, "")
                return AgentResult(False, "failed rework", 1, "")

        marker = _make_marker(
            guard=Guard(command="pytest -q", extract=None, threshold=None, rework_attempts=1),
            loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"),
        )
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            FailingReworkAgent(), worktree_base=tmp_path / "wt",
            cleanup_worktree=False,
        )
        # Only 1 commit for initial change, no rework commit
        assert mock_commit.call_count == 1
        assert result.discarded >= 1


# --- EscalationState: pivot escalation resets consecutive_failures ---


class TestEscalationStatePivotReset:
    def test_consecutive_failures_reset_on_pivot(self):
        esc = EscalationState(pivot_after=3)
        esc.on_discard()
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "pivot"
        assert esc.consecutive_failures == 0

    def test_two_pivots_without_progress_triggers_search(self):
        esc = EscalationState(pivot_after=3, search_after_pivots=2, halt_after_pivots=5)
        for _ in range(3):
            esc.on_discard()
        assert esc.escalation_level == "pivot"
        for _ in range(3):
            esc.on_discard()
        assert esc.escalation_level == "search"
        assert esc.pivots_without_progress == 0  # reset after search

    def test_keep_resets_consecutive_failures_exactly(self):
        esc = EscalationState()
        esc.on_discard()
        esc.on_discard()
        esc.on_keep()
        assert esc.consecutive_failures == 0
        assert esc.escalation_level == "normal"
