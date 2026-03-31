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

        state.markers.append(tracked)
        state_path = tmp_path / "state.json"
        from autoresearch.state import save_state, load_state
        save_state(state, state_path)

        with patch("autoresearch.engine.run_harness") as mock_h:
            mock_h.return_value = HarnessResult(
                exit_code=0, stdout="5 passed", stderr="",
                metric=5.0, log_path=tmp_path / "run.log",
            )
            run_marker(
                git_repo, marker, state, tracked,
                WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
                state_path=state_path,
            )

        updated = load_state(state_path)
        updated_tracked = next(m for m in updated.markers if m.id == tracked.id)
        assert updated_tracked.last_run is not None
        assert updated_tracked.last_run_experiments == 1
        assert updated_tracked.branch is not None


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


class TestGetAgentRunnerA:
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


# --- AgentResult dataclass tests ---


class TestAgentResultDataclass:
    def test_basic_creation(self):
        r = AgentResult(success=True, description="done", exit_code=0, output="")
        assert r.success is True
        assert r.description == "done"
        assert r.exit_code == 0
        assert r.output == ""
        assert r.telemetry is None

    def test_telemetry_field(self):
        tel = object()
        r = AgentResult(success=False, description="x", exit_code=1, output="err", telemetry=tel)
        assert r.telemetry is tel

    def test_exit_code_nonzero(self):
        r = AgentResult(success=False, description="fail", exit_code=2, output="")
        assert r.exit_code == 2

    def test_long_output(self):
        out = "x" * 5000
        r = AgentResult(success=True, description="long", exit_code=0, output=out)
        assert len(r.output) == 5000


# --- RunResult dataclass tests ---


class TestRunResultDataclass:
    def _make_run_result(self, **overrides):
        defaults = dict(
            marker_name="m",
            experiments=3,
            kept=1,
            discarded=1,
            crashed=1,
            final_metric=5.0,
            final_confidence=1.2,
            final_status="budget_exhausted",
            branch="autoresearch/m-abc",
            worktree_path="/tmp/wt/m",
        )
        defaults.update(overrides)
        return RunResult(**defaults)

    def test_basic_creation(self):
        r = self._make_run_result()
        assert r.marker_name == "m"
        assert r.experiments == 3
        assert r.kept == 1
        assert r.discarded == 1
        assert r.crashed == 1

    def test_final_status_completed(self):
        r = self._make_run_result(final_status="completed")
        assert r.final_status == "completed"

    def test_final_status_halted(self):
        r = self._make_run_result(final_status="halted")
        assert r.final_status == "halted"

    def test_final_confidence_none(self):
        r = self._make_run_result(final_confidence=None)
        assert r.final_confidence is None

    def test_final_metric_none(self):
        r = self._make_run_result(final_metric=None)
        assert r.final_metric is None


# --- _extract_description additional skip patterns ---


class TestExtractDescriptionAdditionalPatterns:
    def test_skips_triple_dot_prefix(self):
        output = "...\nActual result"
        assert _extract_description(output) == "Actual result"

    def test_skips_triple_greater_than_prefix(self):
        output = ">>> command\nActual result"
        assert _extract_description(output) == "Actual result"

    def test_skips_dash_divider(self):
        output = "real content\n---"
        assert _extract_description(output) == "real content"

    def test_multiple_metadata_lines_finds_valid(self):
        output = "2026-01-01 something\n[INFO] log\n---\nThe real result\n..."
        assert _extract_description(output) == "The real result"

    def test_output_with_only_metadata_returns_default(self):
        output = "2026-01-01 12:00:00\n[DEBUG] foo\n===\n---"
        assert _extract_description(output) == "experiment"

    def test_exactly_three_chars_is_not_skipped(self):
        output = "abc"
        assert _extract_description(output) == "abc"

    def test_exactly_two_chars_is_skipped(self):
        output = "ab"
        assert _extract_description(output) == "experiment"


# --- _write_discard_idea ValueError silencing ---


class TestWriteDiscardIdeaValueErrorA:
    def test_valueerror_silenced(self, tmp_path):
        with patch("autoresearch.engine.append_idea", side_effect=ValueError("bad")):
            _write_discard_idea(tmp_path, "marker", "description", 3.0)
        # Should not raise


# --- EscalationState additional coverage ---


class TestEscalationStateAdditional:
    def test_current_experiment_default_zero(self):
        esc = EscalationState()
        assert esc.current_experiment == 0

    def test_last_kept_experiment_default_zero(self):
        esc = EscalationState()
        assert esc.last_kept_experiment == 0

    def test_total_pivots_increments_on_pivot(self):
        esc = EscalationState(pivot_after=2)
        esc.on_discard()
        esc.on_discard()
        assert esc.total_pivots == 1

    def test_halt_after_custom_pivots(self):
        esc = EscalationState(pivot_after=2, halt_after_pivots=2)
        for _ in range(2):
            esc.on_discard()  # pivot 1
        for _ in range(2):
            esc.on_discard()  # pivot 2 -> halt
        assert esc.escalation_level == "halt"

    def test_refine_threshold_custom(self):
        esc = EscalationState(refine_after=1)
        esc.on_discard()
        assert esc.escalation_level == "refine"

    def test_on_keep_sets_last_kept(self):
        esc = EscalationState()
        esc.current_experiment = 7
        esc.on_keep()
        assert esc.last_kept_experiment == 7

    def test_crash_and_keep_interleaved(self):
        esc = EscalationState()
        esc.on_crash()
        esc.on_crash()
        esc.on_keep()  # resets
        assert esc.consecutive_failures == 0
        assert esc.escalation_level == "normal"

    def test_search_after_custom_pivots(self):
        esc = EscalationState(pivot_after=2, search_after_pivots=1, halt_after_pivots=5)
        esc.on_discard()
        esc.on_discard()  # pivot 1 -> search (pivots_without_progress >= 1)
        assert esc.escalation_level == "search"

    def test_normal_level_below_refine(self):
        esc = EscalationState(refine_after=4)
        esc.on_discard()
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 3


# --- _format_results_for_program additional ---


class TestFormatResultsAdditional:
    def _make_result(self, **kw):
        from autoresearch.results import ExperimentResult
        defaults = dict(commit="abc", metric=3.0, guard="pass", status="keep",
                        confidence="1.0", description="test")
        defaults.update(kw)
        return ExperimentResult(**defaults)

    def test_guard_field_in_output(self):
        r = self._make_result(guard="fail")
        out = _format_results_for_program([r])
        assert "fail" in out

    def test_crash_status_in_output(self):
        r = self._make_result(status="crash")
        out = _format_results_for_program([r])
        assert "crash" in out

    def test_confidence_field_in_output(self):
        r = self._make_result(confidence="2.5")
        out = _format_results_for_program([r])
        assert "2.5" in out

    def test_many_results(self):
        results = [self._make_result(commit=f"commit{i}") for i in range(10)]
        out = _format_results_for_program(results)
        assert len(out.splitlines()) == 10


# ---------------------------------------------------------------------------
# Additional _target_reached edge cases
# ---------------------------------------------------------------------------


class TestTargetReachedEdgeCases:
    def test_lower_not_reached_above(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.LOWER, baseline=100, target=50,
        ))
        assert _target_reached(marker, 51) is False

    def test_higher_exactly_at_target(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.HIGHER, baseline=3, target=10,
        ))
        assert _target_reached(marker, 10) is True

    def test_lower_exactly_at_target(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.LOWER, baseline=100, target=50,
        ))
        assert _target_reached(marker, 50) is True

    def test_zero_target_lower_direction(self):
        marker = _make_marker(metric=Metric(
            command="echo 1", extract="cat",
            direction=MetricDirection.LOWER, baseline=10, target=0,
        ))
        assert _target_reached(marker, 0) is True
        assert _target_reached(marker, 1) is False


# ---------------------------------------------------------------------------
# Additional _extract_description edge cases
# ---------------------------------------------------------------------------


class TestExtractDescriptionMorePatterns:
    def test_dollar_sign_prefix_skipped(self):
        output = "$ ls -la\nActual output"
        assert _extract_description(output) == "Actual output"

    def test_bracket_prefix_skipped(self):
        output = "[INFO] starting\nDone"
        assert _extract_description(output) == "Done"

    def test_year_prefix_skipped(self):
        output = "2025-03-01 foo\nresult"
        assert _extract_description(output) == "result"

    def test_single_long_line(self):
        output = "A" * 200
        result = _extract_description(output)
        assert len(result) <= 200

    def test_output_truncated_at_200(self):
        long = "x" * 250
        result = _extract_description(long)
        assert len(result) == 200

    def test_whitespace_only_line_skipped(self):
        output = "   \nreal result"
        assert _extract_description(output) == "real result"


# ---------------------------------------------------------------------------
# Additional EscalationState edge cases
# ---------------------------------------------------------------------------


class TestEscalationStateCrashBehavior:
    def test_crash_increments_consecutive_failures(self):
        esc = EscalationState()
        esc.on_crash()
        assert esc.consecutive_failures == 1

    def test_crash_three_times_refines(self):
        esc = EscalationState()
        for _ in range(3):
            esc.on_crash()
        assert esc.escalation_level == "refine"

    def test_crash_five_times_pivots(self):
        esc = EscalationState()
        for _ in range(5):
            esc.on_crash()
        assert esc.escalation_level == "pivot"
        assert esc.consecutive_failures == 0  # reset after pivot
        assert esc.total_pivots == 1

    def test_keep_resets_pivots_without_progress_to_zero(self):
        esc = EscalationState()
        for _ in range(5):
            esc.on_discard()  # pivot 1
        assert esc.pivots_without_progress == 1
        esc.on_keep()
        assert esc.pivots_without_progress == 0

    def test_custom_refine_after_1(self):
        esc = EscalationState(refine_after=1)
        esc.on_crash()
        assert esc.escalation_level == "refine"

    def test_discard_then_keep_then_discard(self):
        esc = EscalationState()
        for _ in range(3):
            esc.on_discard()  # refine
        esc.on_keep()          # reset
        assert esc.escalation_level == "normal"
        esc.on_discard()
        assert esc.consecutive_failures == 1
        assert esc.escalation_level == "normal"


# ---------------------------------------------------------------------------
# Additional _format_results_for_program edge cases
# ---------------------------------------------------------------------------


class TestFormatResultsSingleResult:
    def _r(self, **kw):
        from autoresearch.results import ExperimentResult
        defaults = dict(commit="abc", metric=1.0, guard="pass", status="keep",
                        confidence="1.0", description="x")
        defaults.update(kw)
        return ExperimentResult(**defaults)

    def test_single_result_no_newline_at_end(self):
        r = self._r()
        out = _format_results_for_program([r])
        assert "\n" not in out.strip()

    def test_tab_separated_fields(self):
        r = self._r(commit="abc123", metric=7.0, guard="pass", status="keep",
                    confidence="2.0", description="desc")
        out = _format_results_for_program([r])
        parts = out.split("\t")
        assert parts[0] == "abc123"
        assert parts[3] == "keep"


# ---------------------------------------------------------------------------
# AgentError and EngineError identity
# ---------------------------------------------------------------------------

class TestExceptionClasses:
    def test_agent_error_is_exception(self):
        from autoresearch.engine import AgentError
        e = AgentError("claude not found")
        assert isinstance(e, Exception)
        assert str(e) == "claude not found"

    def test_engine_error_is_exception(self):
        e = EngineError("marker not active")
        assert isinstance(e, Exception)
        assert "not active" in str(e)

    def test_agent_error_can_be_raised(self):
        from autoresearch.engine import AgentError
        with pytest.raises(AgentError, match="binary missing"):
            raise AgentError("binary missing")

    def test_engine_error_can_be_raised(self):
        with pytest.raises(EngineError, match="bad repo"):
            raise EngineError("bad repo")


# ---------------------------------------------------------------------------
# EscalationState — more boundary sequences
# ---------------------------------------------------------------------------

class TestEscalationStateBoundary:
    def test_exactly_refine_minus_one_stays_normal(self):
        esc = EscalationState(refine_after=4)
        for _ in range(3):
            esc.on_discard()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 3

    def test_exactly_refine_triggers_refine(self):
        esc = EscalationState(refine_after=4)
        for _ in range(4):
            esc.on_discard()
        assert esc.escalation_level == "refine"

    def test_pivot_resets_consecutive_failures_to_zero(self):
        esc = EscalationState(pivot_after=3)
        for _ in range(3):
            esc.on_discard()
        assert esc.consecutive_failures == 0
        assert esc.escalation_level == "pivot"

    def test_multiple_pivots_accumulate(self):
        esc = EscalationState(pivot_after=2, halt_after_pivots=10)
        for _ in range(4):
            esc.on_discard()  # 2 discards → pivot1, 2 more → pivot2
        assert esc.total_pivots == 2

    def test_halt_level_only_after_halt_after_pivots(self):
        esc = EscalationState(pivot_after=2, halt_after_pivots=2)
        for _ in range(4):
            esc.on_discard()  # pivot1, pivot2 → halt
        assert esc.escalation_level == "halt"

    def test_crash_and_discard_count_together_toward_refine(self):
        esc = EscalationState(refine_after=3)
        esc.on_crash()
        esc.on_discard()
        esc.on_crash()
        assert esc.escalation_level == "refine"
        assert esc.consecutive_failures == 3

    def test_keep_resets_escalation_level_to_normal(self):
        esc = EscalationState()
        for _ in range(3):
            esc.on_discard()
        assert esc.escalation_level == "refine"
        esc.on_keep()
        assert esc.escalation_level == "normal"

    def test_on_keep_increments_last_kept_experiment(self):
        esc = EscalationState()
        esc.current_experiment = 5
        esc.on_keep()
        assert esc.last_kept_experiment == 5


# ---------------------------------------------------------------------------
# _write_telemetry_feedback — truncation to first 3
# ---------------------------------------------------------------------------

class TestWriteTelemetryFeedbackTruncation:
    def test_more_than_3_errors_only_first_3_used(self, tmp_path):
        class FakeTelemetry:
            errors = ["e1", "e2", "e3", "e4", "e5"]
            permission_denials = []

        agent_result = AgentResult(
            success=True, description="d", exit_code=0, output="",
            telemetry=FakeTelemetry(),
        )
        captured = []
        with patch("autoresearch.engine.append_idea", side_effect=lambda *a: captured.append(a)):
            _write_telemetry_feedback(tmp_path, "m", agent_result)
        # Should have joined first 3 errors only
        assert len(captured) == 1
        assert "e4" not in captured[0][3]
        assert "e1" in captured[0][3]

    def test_more_than_3_denials_only_first_3_used(self, tmp_path):
        class FakeTelemetry:
            errors = []
            permission_denials = ["d1", "d2", "d3", "d4"]

        agent_result = AgentResult(
            success=True, description="d", exit_code=0, output="",
            telemetry=FakeTelemetry(),
        )
        captured = []
        with patch("autoresearch.engine.append_idea", side_effect=lambda *a: captured.append(a)):
            _write_telemetry_feedback(tmp_path, "m", agent_result)
        assert len(captured) == 1
        assert "d4" not in captured[0][3]
        assert "d1" in captured[0][3]

    def test_empty_errors_list_no_write(self, tmp_path):
        class FakeTelemetry:
            errors = []
            permission_denials = []

        agent_result = AgentResult(
            success=True, description="d", exit_code=0, output="",
            telemetry=FakeTelemetry(),
        )
        with patch("autoresearch.engine.append_idea") as mock_idea:
            _write_telemetry_feedback(tmp_path, "m", agent_result)
        mock_idea.assert_not_called()


# ---------------------------------------------------------------------------
# _write_discard_idea — additional cases
# ---------------------------------------------------------------------------

class TestWriteDiscardIdeaEdgeCases:
    def test_zero_metric(self, tmp_path):
        with patch("autoresearch.engine.append_idea") as mock:
            _write_discard_idea(tmp_path, "m", "description", 0.0)
        mock.assert_called_once()
        call_args = mock.call_args[0]
        assert "0.0" in call_args[3]

    def test_negative_metric(self, tmp_path):
        with patch("autoresearch.engine.append_idea") as mock:
            _write_discard_idea(tmp_path, "m", "tried something", -5.0)
        mock.assert_called_once()

    def test_long_description_included(self, tmp_path):
        desc = "x" * 300
        with patch("autoresearch.engine.append_idea") as mock:
            _write_discard_idea(tmp_path, "m", desc, 1.0)
        mock.assert_called_once()
        call_args = mock.call_args[0]
        assert desc in call_args[3]


# ---------------------------------------------------------------------------
# _format_results_for_program — description with special chars
# ---------------------------------------------------------------------------

class TestFormatResultsSpecialChars:
    def _r(self, description=""):
        from autoresearch.results import ExperimentResult
        return ExperimentResult(
            commit="abc", metric=1.0, guard="pass", status="keep",
            confidence="1.0", description=description,
        )

    def test_description_with_tabs_preserved(self):
        r = self._r(description="a\tb")
        out = _format_results_for_program([r])
        assert "a\tb" in out

    def test_description_with_newline_preserved(self):
        r = self._r(description="line1\nline2")
        out = _format_results_for_program([r])
        assert "line1" in out

    def test_empty_description(self):
        r = self._r(description="")
        out = _format_results_for_program([r])
        assert out.endswith("\t")  # last field is empty


# ---------------------------------------------------------------------------
# _extract_description — more edge cases
# ---------------------------------------------------------------------------

class TestExtractDescriptionEdgeCasesNew:
    def test_all_lines_metadata_returns_default(self):
        output = "2024-01-01 foo\n[INFO] bar\n---\n"
        assert _extract_description(output) == "experiment"

    def test_only_two_char_lines_returns_default(self):
        output = "ab\ncd\nef"
        assert _extract_description(output) == "experiment"

    def test_dots_prefix_skipped(self):
        output = "...loading\nactual result"
        assert _extract_description(output) == "actual result"

    def test_triple_equals_skipped(self):
        output = "=== separator ===\nreal line"
        assert _extract_description(output) == "real line"

    def test_three_char_valid_line(self):
        output = "abc"
        assert _extract_description(output) == "abc"


# ---------------------------------------------------------------------------
# AgentResult defaults
# ---------------------------------------------------------------------------

class TestAgentResultDefaults:
    def test_telemetry_defaults_to_none(self):
        r = AgentResult(success=True, description="d", exit_code=0, output="")
        assert r.telemetry is None

    def test_output_can_be_empty_string(self):
        r = AgentResult(success=False, description="d", exit_code=1, output="")
        assert r.output == ""

    def test_success_false(self):
        r = AgentResult(success=False, description="failed", exit_code=1, output="err")
        assert r.success is False
        assert r.exit_code == 1


# ---------------------------------------------------------------------------
# EscalationState — search level via pivots_without_progress
# ---------------------------------------------------------------------------

class TestEscalationStateSearchLevel:
    def test_search_triggers_after_two_pivots_without_progress(self):
        esc = EscalationState(pivot_after=2, search_after_pivots=2, halt_after_pivots=10)
        # pivot 1: 2 discards → pivot
        esc.on_discard(); esc.on_discard()
        assert esc.escalation_level == "pivot"
        # pivot 2: 2 more discards → pivots_without_progress hits 2 → search
        esc.on_discard(); esc.on_discard()
        assert esc.escalation_level in ("pivot", "search")

    def test_search_resets_pivots_without_progress(self):
        esc = EscalationState(pivot_after=2, search_after_pivots=1, halt_after_pivots=10)
        esc.on_discard(); esc.on_discard()  # pivot 1 → search
        assert esc.escalation_level == "search"
        assert esc.pivots_without_progress == 0

    def test_search_level_string_value(self):
        esc = EscalationState(pivot_after=1, search_after_pivots=1, halt_after_pivots=10)
        esc.on_discard()
        assert esc.escalation_level == "search"

    def test_default_fields(self):
        esc = EscalationState()
        assert esc.refine_after == 3
        assert esc.pivot_after == 5
        assert esc.search_after_pivots == 2
        assert esc.halt_after_pivots == 3

    def test_pivots_without_progress_increments_per_pivot(self):
        esc = EscalationState(pivot_after=1, search_after_pivots=3, halt_after_pivots=10)
        esc.on_discard()  # pivot 1
        assert esc.total_pivots == 1
        esc.on_discard()  # pivot 2
        assert esc.total_pivots == 2

    def test_on_keep_resets_pivots_without_progress(self):
        esc = EscalationState(pivot_after=2, search_after_pivots=3, halt_after_pivots=10)
        esc.on_discard(); esc.on_discard()  # pivot 1
        esc.on_keep()
        assert esc.pivots_without_progress == 0
        assert esc.consecutive_failures == 0


# ---------------------------------------------------------------------------
# RunResult — additional field tests
# ---------------------------------------------------------------------------

class TestRunResultFields:
    def _make(self, **kw):
        d = dict(
            marker_name="x", experiments=5, kept=2, discarded=2, crashed=1,
            final_metric=10.0, final_confidence=1.5, final_status="budget_exhausted",
            branch="autoresearch/x", worktree_path="/tmp/x",
        )
        d.update(kw)
        return RunResult(**d)

    def test_branch_stored(self):
        r = self._make(branch="autoresearch/myfeat")
        assert r.branch == "autoresearch/myfeat"

    def test_worktree_path_stored(self):
        r = self._make(worktree_path="/var/wt/foo")
        assert r.worktree_path == "/var/wt/foo"

    def test_experiments_sum(self):
        r = self._make(experiments=10, kept=3, discarded=5, crashed=2)
        assert r.kept + r.discarded + r.crashed == r.experiments

    def test_final_status_budget_exhausted(self):
        r = self._make(final_status="budget_exhausted")
        assert r.final_status == "budget_exhausted"

    def test_marker_name_stored(self):
        r = self._make(marker_name="my-marker")
        assert r.marker_name == "my-marker"


# ---------------------------------------------------------------------------
# _write_telemetry_feedback — no telemetry attr
# ---------------------------------------------------------------------------

class TestWriteTelemetryFeedbackNoTelemetry:
    def test_no_telemetry_no_call(self, tmp_path):
        result = AgentResult(success=True, description="d", exit_code=0, output="", telemetry=None)
        with patch("autoresearch.engine.append_idea") as mock:
            _write_telemetry_feedback(tmp_path, "m", result)
        mock.assert_not_called()

    def test_oserror_silenced(self, tmp_path):
        class FakeTelemetry:
            errors = ["e1"]
            permission_denials = []

        result = AgentResult(
            success=True, description="d", exit_code=0, output="",
            telemetry=FakeTelemetry(),
        )
        with patch("autoresearch.engine.append_idea", side_effect=OSError("disk full")):
            _write_telemetry_feedback(tmp_path, "m", result)  # should not raise

    def test_permission_denials_written(self, tmp_path):
        class FakeTelemetry:
            errors = []
            permission_denials = ["denied1", "denied2"]

        result = AgentResult(
            success=True, description="d", exit_code=0, output="",
            telemetry=FakeTelemetry(),
        )
        captured = []
        with patch("autoresearch.engine.append_idea", side_effect=lambda *a: captured.append(a)):
            _write_telemetry_feedback(tmp_path, "m", result)
        assert len(captured) == 1
        assert "denied1" in captured[0][3]


# ---------------------------------------------------------------------------
# _write_discard_idea — OSError silenced
# ---------------------------------------------------------------------------

class TestWriteDiscardIdeaOSError:
    def test_oserror_silenced(self, tmp_path):
        with patch("autoresearch.engine.append_idea", side_effect=OSError("boom")):
            _write_discard_idea(tmp_path, "m", "desc", 1.0)  # should not raise

    def test_description_in_entry(self, tmp_path):
        captured = []
        with patch("autoresearch.engine.append_idea", side_effect=lambda *a: captured.append(a)):
            _write_discard_idea(tmp_path, "m", "great idea", 9.5)
        assert "great idea" in captured[0][3]
        assert "9.5" in captured[0][3]


# ---------------------------------------------------------------------------
# _extract_description — additional patterns
# ---------------------------------------------------------------------------

class TestExtractDescriptionMoreEdgeCases:
    def test_empty_string_returns_default(self):
        assert _extract_description("") == "experiment"

    def test_none_like_empty_handled(self):
        # output is empty string — treated same as empty
        assert _extract_description("  ") == "experiment"

    def test_line_truncated_at_200(self):
        output = "B" * 300
        result = _extract_description(output)
        assert len(result) == 200

    def test_last_valid_line_chosen(self):
        output = "first valid\nsecond valid\n---"
        result = _extract_description(output)
        assert result == "second valid"

    def test_shell_prompt_skipped(self):
        output = "$ echo hello\nHello World"
        assert _extract_description(output) == "Hello World"

    def test_bracket_log_prefix_skipped(self):
        output = "[DEBUG] internal\nresult line"
        assert _extract_description(output) == "result line"


# ---------------------------------------------------------------------------
# get_agent_runner — returns ClaudeCodeRunner
# ---------------------------------------------------------------------------

class TestGetAgentRunner:
    def test_returns_claude_code_runner(self):
        marker = _make_marker()
        runner = get_agent_runner(marker)
        assert isinstance(runner, ClaudeCodeRunner)

    def test_runner_has_marker(self):
        marker = _make_marker()
        runner = get_agent_runner(marker)
        assert runner.marker is marker


# ---------------------------------------------------------------------------
# EscalationState — halt level reached via on_crash
# ---------------------------------------------------------------------------

class TestEscalationStateHaltViaCrash:
    def test_crash_can_trigger_pivot(self):
        esc = EscalationState(pivot_after=2, search_after_pivots=5, halt_after_pivots=10)
        esc.on_crash()
        esc.on_crash()
        assert esc.escalation_level == "pivot"

    def test_crash_and_discard_combine_toward_pivot(self):
        esc = EscalationState(pivot_after=3, search_after_pivots=5, halt_after_pivots=10)
        esc.on_crash()
        esc.on_discard()
        esc.on_crash()
        assert esc.escalation_level == "pivot"

    def test_halt_via_crash_only(self):
        esc = EscalationState(pivot_after=2, search_after_pivots=5, halt_after_pivots=3)
        for _ in range(6):   # 3 pivots × 2 crashes each
            esc.on_crash()
            esc.on_crash()
        assert esc.escalation_level == "halt"

    def test_escalation_level_normal_at_start(self):
        esc = EscalationState()
        assert esc.escalation_level == "normal"

    def test_one_crash_stays_normal(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        esc.on_crash()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 1

    def test_two_crashes_stays_normal_before_refine(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        esc.on_crash()
        esc.on_crash()
        assert esc.escalation_level == "normal"

    def test_three_crashes_triggers_refine(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        esc.on_crash()
        esc.on_crash()
        esc.on_crash()
        assert esc.escalation_level == "refine"


# ---------------------------------------------------------------------------
# EscalationState — on_keep and experiment tracking
# ---------------------------------------------------------------------------

class TestEscalationStateOnKeep:
    def test_on_keep_sets_last_kept_experiment(self):
        esc = EscalationState()
        esc.current_experiment = 7
        esc.on_keep()
        assert esc.last_kept_experiment == 7

    def test_on_keep_resets_escalation_to_normal(self):
        esc = EscalationState(refine_after=2, pivot_after=5)
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "refine"
        esc.on_keep()
        assert esc.escalation_level == "normal"

    def test_on_keep_zeroes_consecutive_failures(self):
        esc = EscalationState(refine_after=2, pivot_after=5)
        esc.on_discard()
        esc.on_discard()
        esc.on_keep()
        assert esc.consecutive_failures == 0

    def test_on_keep_does_not_affect_total_pivots(self):
        esc = EscalationState(pivot_after=1, search_after_pivots=5, halt_after_pivots=10)
        esc.on_discard()  # triggers pivot
        assert esc.total_pivots == 1
        esc.on_keep()
        assert esc.total_pivots == 1  # not reset


# ---------------------------------------------------------------------------
# _parse_budget alias
# ---------------------------------------------------------------------------

class TestParseBudgetAlias:
    def test_parses_minutes(self):
        assert _parse_budget("5m") == 300

    def test_parses_hours(self):
        assert _parse_budget("1h") == 3600

    def test_parses_seconds(self):
        assert _parse_budget("30s") == 30

    def test_empty_returns_default(self):
        assert _parse_budget("") == 600


# ---------------------------------------------------------------------------
# _format_results_for_program — extra combos
# ---------------------------------------------------------------------------

class TestFormatResultsForProgramExtra:
    def _make_result(self, commit="abc", metric=5.0, guard="pass", status="keep",
                     confidence="1.2", description="desc"):
        from autoresearch.results import ExperimentResult
        return ExperimentResult(
            commit=commit, metric=metric, guard=guard, status=status,
            confidence=confidence, description=description,
        )

    def test_three_results_three_lines(self):
        results = [
            self._make_result(commit="a1"),
            self._make_result(commit="b2"),
            self._make_result(commit="c3"),
        ]
        out = _format_results_for_program(results)
        assert out.count("\n") == 2

    def test_metric_in_output(self):
        r = self._make_result(metric=42.0)
        out = _format_results_for_program([r])
        assert "42.0" in out

    def test_status_in_output(self):
        r = self._make_result(status="discard")
        out = _format_results_for_program([r])
        assert "discard" in out

    def test_confidence_in_output(self):
        r = self._make_result(confidence="2.5")
        out = _format_results_for_program([r])
        assert "2.5" in out

    def test_commit_in_output(self):
        r = self._make_result(commit="deadbeef")
        out = _format_results_for_program([r])
        assert "deadbeef" in out


# ---------------------------------------------------------------------------
# _reset_to_before_commit — logging on GitError
# ---------------------------------------------------------------------------

class TestResetToBeforeCommitExtra:
    def test_no_error_calls_git_reset(self):
        with patch("autoresearch.engine.git_reset_hard") as mock_reset:
            _reset_to_before_commit(Path("/tmp/wt"), "abc1234")
        mock_reset.assert_called_once_with(Path("/tmp/wt"), "abc1234~1")

    def test_git_error_does_not_raise(self):
        from autoresearch.worktree import GitError
        with patch("autoresearch.engine.git_reset_hard", side_effect=GitError("bad")):
            _reset_to_before_commit(Path("/tmp/wt"), "abc1234")  # no raise


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — cmd structure
# ---------------------------------------------------------------------------

class TestClaudeCodeRunnerCmdStructure:
    def _make_paths(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        logs = tmp_path / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        return AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=logs / "run-20260101-000000.jsonl",
            debug_log_path=logs / "debug-20260101-000000.log",
        )

    def _run_and_capture_cmd(self, marker, tmp_path):
        paths = self._make_paths(tmp_path)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=fake_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")
        return captured["cmd"]

    def test_cmd_starts_with_claude(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert cmd[0] == "claude"

    def test_cmd_has_p_flag(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "-p" in cmd

    def test_cmd_has_model_flag(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(model="sonnet"))
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--model" in cmd

    def test_cmd_has_output_format(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "stream-json"

    def test_cmd_has_add_dir(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--add-dir" in cmd

    def test_no_allowed_tools_flag_by_default(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--allowedTools" not in cmd

    def test_no_disallowed_tools_flag_by_default(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--disallowedTools" not in cmd


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — output stored in stream log
# ---------------------------------------------------------------------------

class TestClaudeCodeRunnerStreamLog:
    def test_stream_log_written_when_output_nonempty(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        from autoresearch.marker import AgentConfig

        logs = tmp_path / "logs"
        logs.mkdir(parents=True)
        stream_log = logs / "run-20260101-000000.jsonl"

        paths = AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=stream_log,
            debug_log_path=logs / "debug.log",
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"type":"result"}\n'

        marker = _make_marker(agent=AgentConfig())
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", return_value=mock_proc),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value="ok"),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")

        assert stream_log.exists()
        assert '{"type":"result"}' in stream_log.read_text()

    def test_stream_log_not_written_for_empty_output(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        from autoresearch.marker import AgentConfig

        logs = tmp_path / "logs"
        logs.mkdir(parents=True)
        stream_log = logs / "run-20260101-000000.jsonl"

        paths = AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=stream_log,
            debug_log_path=logs / "debug.log",
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""

        marker = _make_marker(agent=AgentConfig())
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", return_value=mock_proc),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")

        assert not stream_log.exists()


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — allowed_tools flag
# ---------------------------------------------------------------------------

class TestClaudeCodeRunnerAllowedTools:
    def _make_paths(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        logs = tmp_path / "logs"
        logs.mkdir(parents=True)
        return AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=logs / "run-20260101-000000.jsonl",
            debug_log_path=logs / "debug.log",
        )

    def _run_and_capture_cmd(self, marker, tmp_path):
        paths = self._make_paths(tmp_path)
        captured = {}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return mock_proc
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=fake_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")
        return captured["cmd"]

    def test_allowed_tools_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(allowed_tools=["Bash", "Read"]))
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert "Bash" in cmd[idx + 1:]
        assert "Read" in cmd[idx + 1:]

    def test_disallowed_tools_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(disallowed_tools=["WebSearch"]))
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--disallowedTools" in cmd
        idx = cmd.index("--disallowedTools")
        assert "WebSearch" in cmd[idx + 1:]

    def test_effort_flag_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(effort="high"))
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--effort" in cmd
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "high"

    def test_no_effort_flag_when_not_set(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(effort=""))
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--effort" not in cmd

    def test_extra_flags_appended(self, tmp_path):
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig(extra_flags=["--verbose", "--debug"]))
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--verbose" in cmd
        assert "--debug" in cmd

    def test_model_from_marker_loop(self, tmp_path):
        from autoresearch.marker import AgentConfig
        loop = LoopConfig(max_experiments=1, budget_per_experiment="1m", model="opus")
        marker = _make_marker(agent=AgentConfig(model=""), loop=loop)
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    def test_agent_model_overrides_loop_model(self, tmp_path):
        from autoresearch.marker import AgentConfig
        loop = LoopConfig(max_experiments=1, budget_per_experiment="1m", model="opus")
        marker = _make_marker(agent=AgentConfig(model="haiku"), loop=loop)
        cmd = self._run_and_capture_cmd(marker, tmp_path)
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — .env file loading
# ---------------------------------------------------------------------------

class TestClaudeCodeRunnerEnvLoading:
    def _make_paths(self, tmp_path, with_env=False, env_content=""):
        from autoresearch.agent_profile import AgentPaths
        logs = tmp_path / "logs"
        logs.mkdir(parents=True)
        paths = AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=logs / "run-20260101-000000.jsonl",
            debug_log_path=logs / "debug.log",
        )
        if with_env:
            (tmp_path / ".env").write_text(env_content)
        return paths

    def test_env_vars_loaded_from_dot_env(self, tmp_path):
        paths = self._make_paths(tmp_path, with_env=True, env_content="MY_VAR=hello\n")
        captured_env = {}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        def fake_run(cmd, env=None, **kwargs):
            captured_env.update(env or {})
            return mock_proc
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=fake_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")
        assert captured_env.get("MY_VAR") == "hello"

    def test_dot_env_comments_ignored(self, tmp_path):
        paths = self._make_paths(tmp_path, with_env=True, env_content="# comment\nKEY=val\n")
        captured_env = {}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        def fake_run(cmd, env=None, **kwargs):
            captured_env.update(env or {})
            return mock_proc
        from autoresearch.marker import AgentConfig
        marker = _make_marker(agent=AgentConfig())
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=fake_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=""),
        ):
            ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "5m")
        assert "KEY" in captured_env
        assert captured_env.get("KEY") == "val"


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — timeout returns AgentResult with success=False
# ---------------------------------------------------------------------------

class TestClaudeCodeRunnerTimeout:
    def _make_paths(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        logs = tmp_path / "logs"
        logs.mkdir(parents=True)
        return AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=logs / "run-20260101-000000.jsonl",
            debug_log_path=logs / "debug.log",
        )

    def test_timeout_returns_failed_agent_result(self, tmp_path):
        from autoresearch.marker import AgentConfig
        paths = self._make_paths(tmp_path)
        marker = _make_marker(agent=AgentConfig())
        exc = subprocess.TimeoutExpired(cmd=["claude"], timeout=60, output=None, stderr=None)
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=exc),
        ):
            result = ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "1m")
        assert result.success is False
        assert result.exit_code == -1
        assert result.description == "agent timeout"

    def test_timeout_with_partial_output(self, tmp_path):
        from autoresearch.marker import AgentConfig
        paths = self._make_paths(tmp_path)
        marker = _make_marker(agent=AgentConfig())
        exc = subprocess.TimeoutExpired(
            cmd=["claude"], timeout=60, output="partial output", stderr=None
        )
        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
            patch("autoresearch.engine.subprocess.run", side_effect=exc),
        ):
            result = ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "1m")
        assert result.success is False
        assert "partial" in result.output or result.output == "TIMEOUT"

    def test_no_claude_on_path_raises_agent_error(self, tmp_path):
        from autoresearch.engine import AgentError
        from autoresearch.marker import AgentConfig
        paths = self._make_paths(tmp_path)
        marker = _make_marker(agent=AgentConfig())
        with (
            patch("autoresearch.engine.shutil.which", return_value=None),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=paths),
        ):
            with pytest.raises(AgentError, match="claude"):
                ClaudeCodeRunner(marker=marker).invoke(tmp_path, "prog", "1m")


# ---------------------------------------------------------------------------
# EscalationState — search level resets pivots_without_progress
# ---------------------------------------------------------------------------

class TestEscalationStateSearchResets:
    def test_search_level_resets_pivots_without_progress(self):
        esc = EscalationState(
            refine_after=3,
            pivot_after=5,
            search_after_pivots=2,
            halt_after_pivots=5,
        )
        # First pivot: 5 failures
        for _ in range(5):
            esc.on_discard()
        assert esc.escalation_level == "pivot"
        # Second pivot (triggers search): 5 more failures
        for _ in range(5):
            esc.on_discard()
        assert esc.escalation_level == "search"
        assert esc.pivots_without_progress == 0

    def test_after_search_pivot_continues_to_track(self):
        esc = EscalationState(
            refine_after=3,
            pivot_after=5,
            search_after_pivots=2,
            halt_after_pivots=10,
        )
        # Trigger search
        for _ in range(10):
            esc.on_discard()
        assert esc.escalation_level == "search"
        # Another pivot
        for _ in range(5):
            esc.on_discard()
        # pivot_without_progress was reset at search, so this is 1 again
        assert esc.escalation_level in ("pivot", "search")

    def test_keep_after_search_resets_to_normal(self):
        esc = EscalationState(
            refine_after=3,
            pivot_after=5,
            search_after_pivots=2,
            halt_after_pivots=10,
        )
        for _ in range(10):
            esc.on_discard()
        assert esc.escalation_level == "search"
        esc.on_keep()
        assert esc.escalation_level == "normal"
        assert esc.consecutive_failures == 0
        assert esc.pivots_without_progress == 0


# ---------------------------------------------------------------------------
# _write_telemetry_feedback — various edge cases
# ---------------------------------------------------------------------------

class TestWriteTelemetryFeedbackEdgeCases:
    def test_telemetry_with_no_errors_no_denials(self, tmp_path):
        mock_tel = MagicMock()
        mock_tel.errors = []
        mock_tel.permission_denials = []
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=mock_tel)
        # Should not raise
        _write_telemetry_feedback(tmp_path, "marker", result)

    def test_errors_written_as_idea(self, tmp_path):
        mock_tel = MagicMock()
        mock_tel.errors = ["Error A", "Error B"]
        mock_tel.permission_denials = []
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=mock_tel)
        _write_telemetry_feedback(tmp_path, "marker", result)
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        content = ideas_path.read_text()
        assert "Error A" in content

    def test_permission_denials_written_as_near_miss(self, tmp_path):
        mock_tel = MagicMock()
        mock_tel.errors = []
        mock_tel.permission_denials = ["Denied write to src/engine.py"]
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=mock_tel)
        _write_telemetry_feedback(tmp_path, "marker", result)
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        content = ideas_path.read_text()
        assert "Denied write" in content

    def test_telemetry_none_no_error(self, tmp_path):
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=None)
        _write_telemetry_feedback(tmp_path, "marker", result)

    def test_errors_truncated_to_three(self, tmp_path):
        mock_tel = MagicMock()
        mock_tel.errors = [f"Error {i}" for i in range(10)]
        mock_tel.permission_denials = []
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=mock_tel)
        _write_telemetry_feedback(tmp_path, "marker", result)
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        content = ideas_path.read_text()
        # Only first 3 errors summarized
        assert "Error 0" in content
        assert "Error 9" not in content


# ---------------------------------------------------------------------------
# _handle_guard_failure — edge cases
# ---------------------------------------------------------------------------

class TestHandleGuardFailure:
    def _make_guard_result(self, passed: bool):
        return GuardResult(passed=passed, output="guard output", value=None)

    def test_returns_true_when_guard_passes_after_rework(self, tmp_path):
        from autoresearch.engine import _handle_guard_failure
        from autoresearch.marker import AgentConfig, Guard

        guard = Guard(command="echo ok", extract=None, threshold=None, rework_attempts=2)
        marker = _make_marker(guard=guard)

        rework_result = AgentResult(success=True, description="rework", exit_code=0, output="")
        fake_runner = FakeAgentRunner([rework_result])

        with (
            patch("autoresearch.engine.git_commit", return_value="abc123"),
            patch("autoresearch.engine.run_guard", return_value=self._make_guard_result(True)),
            patch("autoresearch.engine._parse_budget", return_value=60),
        ):
            result = _handle_guard_failure(
                tmp_path, marker, fake_runner, self._make_guard_result(False), 2
            )
        assert result is True

    def test_returns_false_when_rework_agent_fails(self, tmp_path):
        from autoresearch.engine import _handle_guard_failure
        from autoresearch.marker import AgentConfig, Guard

        guard = Guard(command="echo ok", extract=None, threshold=None, rework_attempts=1)
        marker = _make_marker(guard=guard)

        rework_result = AgentResult(success=False, description="fail", exit_code=1, output="")
        fake_runner = FakeAgentRunner([rework_result])

        result = _handle_guard_failure(
            tmp_path, marker, fake_runner, self._make_guard_result(False), 1
        )
        assert result is False

    def test_returns_false_when_guard_never_passes(self, tmp_path):
        from autoresearch.engine import _handle_guard_failure
        from autoresearch.marker import AgentConfig, Guard

        guard = Guard(command="echo ok", extract=None, threshold=None, rework_attempts=2)
        marker = _make_marker(guard=guard)

        rework_result = AgentResult(success=True, description="rework", exit_code=0, output="")
        fake_runner = FakeAgentRunner([rework_result, rework_result])

        with (
            patch("autoresearch.engine.git_commit", return_value="abc123"),
            patch("autoresearch.engine.run_guard", return_value=self._make_guard_result(False)),
            patch("autoresearch.engine._parse_budget", return_value=60),
        ):
            result = _handle_guard_failure(
                tmp_path, marker, fake_runner, self._make_guard_result(False), 2
            )
        assert result is False


# ---------------------------------------------------------------------------
# RunResult — worktree_path field
# ---------------------------------------------------------------------------

class TestRunResultWorktreePath:
    def test_worktree_path_in_fields(self):
        rr = RunResult(
            marker_name="m",
            experiments=3,
            kept=1,
            discarded=2,
            crashed=0,
            final_metric=5.0,
            final_confidence=0.8,
            final_status="completed",
            branch="autoresearch/m",
            worktree_path="/tmp/wt",
        )
        assert rr.worktree_path == "/tmp/wt"

    def test_all_fields_accessible(self):
        rr = RunResult(
            marker_name="my-marker",
            experiments=10,
            kept=3,
            discarded=5,
            crashed=2,
            final_metric=42.0,
            final_confidence=1.5,
            final_status="budget_exhausted",
            branch="autoresearch/my-marker",
            worktree_path="/wt/path",
        )
        assert rr.marker_name == "my-marker"
        assert rr.experiments == 10
        assert rr.kept == 3
        assert rr.discarded == 5
        assert rr.crashed == 2
        assert rr.final_metric == 42.0
        assert rr.final_confidence == 1.5
        assert rr.final_status == "budget_exhausted"
        assert rr.branch == "autoresearch/my-marker"


# ---------------------------------------------------------------------------
# AgentError / EngineError — subclass checks
# ---------------------------------------------------------------------------

class TestErrorClassHierarchy:
    def test_agent_error_is_exception(self):
        from autoresearch.engine import AgentError
        assert issubclass(AgentError, Exception)

    def test_engine_error_is_exception(self):
        from autoresearch.engine import EngineError
        assert issubclass(EngineError, Exception)

    def test_agent_error_message(self):
        from autoresearch.engine import AgentError
        e = AgentError("something broke")
        assert "something broke" in str(e)

    def test_engine_error_message(self):
        from autoresearch.engine import EngineError
        e = EngineError("bad state")
        assert "bad state" in str(e)


# ---------------------------------------------------------------------------
# _target_reached — lower direction
# ---------------------------------------------------------------------------

class TestTargetReachedLowerDirection:
    def test_lower_target_reached_when_equal(self):
        marker = _make_marker(
            metric=Metric(
                command="echo '3'",
                extract=r"\d+",
                direction=MetricDirection.LOWER,
                baseline=10,
                target=3,
            )
        )
        assert _target_reached(marker, 3.0) is True

    def test_lower_target_not_reached_when_above(self):
        marker = _make_marker(
            metric=Metric(
                command="echo '5'",
                extract=r"\d+",
                direction=MetricDirection.LOWER,
                baseline=10,
                target=3,
            )
        )
        assert _target_reached(marker, 5.0) is False

    def test_higher_target_not_reached_when_below(self):
        marker = _make_marker(
            metric=Metric(
                command="echo '4'",
                extract=r"\d+",
                direction=MetricDirection.HIGHER,
                baseline=3,
                target=10,
            )
        )
        assert _target_reached(marker, 4.0) is False

    def test_target_none_always_false(self):
        marker = _make_marker(
            metric=Metric(
                command="echo '100'",
                extract=r"\d+",
                direction=MetricDirection.HIGHER,
                baseline=3,
                target=None,
            )
        )
        assert _target_reached(marker, 100.0) is False


# ---------------------------------------------------------------------------
# EscalationState — precise boundary conditions
# ---------------------------------------------------------------------------

class TestEscalationStatePreciseBoundaries:
    def test_exactly_refine_after_failures_triggers_refine(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        esc.on_discard()
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "refine"

    def test_one_less_than_refine_stays_normal(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "normal"

    def test_exactly_pivot_after_resets_consecutive(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        for _ in range(5):
            esc.on_discard()
        assert esc.consecutive_failures == 0
        assert esc.total_pivots == 1

    def test_pivot_escalation_level_set_on_first_pivot(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=3, halt_after_pivots=4)
        for _ in range(5):
            esc.on_discard()
        assert esc.escalation_level == "pivot"

    def test_on_keep_resets_pivots_without_progress(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=2, halt_after_pivots=4)
        for _ in range(5):
            esc.on_discard()
        assert esc.pivots_without_progress == 1
        esc.on_keep()
        assert esc.pivots_without_progress == 0

    def test_crash_counts_toward_pivot(self):
        esc = EscalationState(refine_after=3, pivot_after=5)
        for _ in range(3):
            esc.on_discard()
        for _ in range(2):
            esc.on_crash()
        assert esc.total_pivots == 1

    def test_two_pivots_without_keep_triggers_search(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=2, halt_after_pivots=4)
        for _ in range(10):
            esc.on_discard()
        assert esc.escalation_level == "search"

    def test_search_resets_pivots_without_progress(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=2, halt_after_pivots=4)
        for _ in range(10):
            esc.on_discard()
        assert esc.pivots_without_progress == 0

    def test_halt_after_three_total_pivots(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=3, halt_after_pivots=3)
        for _ in range(15):
            esc.on_discard()
        assert esc.escalation_level == "halt"

    def test_current_experiment_not_affected_by_on_discard(self):
        esc = EscalationState()
        esc.current_experiment = 7
        esc.on_discard()
        assert esc.current_experiment == 7

    def test_on_keep_sets_escalation_to_normal_from_refine(self):
        esc = EscalationState(refine_after=2, pivot_after=5)
        esc.on_discard()
        esc.on_discard()
        assert esc.escalation_level == "refine"
        esc.on_keep()
        assert esc.escalation_level == "normal"


# ---------------------------------------------------------------------------
# _extract_description — more prefix patterns
# ---------------------------------------------------------------------------

class TestExtractDescriptionPrefixPatterns:
    def test_equals_divider_skipped(self):
        output = "=== some log ===\nactual description"
        assert _extract_description(output) == "actual description"

    def test_ellipsis_skipped(self):
        output = "...loading\nfinal description"
        assert _extract_description(output) == "final description"

    def test_dollar_prompt_skipped(self):
        output = "$ echo hello\ndone here"
        assert _extract_description(output) == "done here"

    def test_timestamp_line_skipped(self):
        output = "2026-03-15 12:00:00 log entry\nactual result"
        assert _extract_description(output) == "actual result"

    def test_gt_gt_gt_prompt_skipped(self):
        output = ">>> python command\ngood output"
        assert _extract_description(output) == "good output"

    def test_short_line_under_3_skipped(self):
        output = "ok\nactual long description here"
        assert _extract_description(output) == "actual long description here"

    def test_line_exactly_200_not_truncated(self):
        line = "x" * 200
        assert len(_extract_description(line)) == 200

    def test_line_over_200_truncated(self):
        line = "x" * 250
        assert len(_extract_description(line)) == 200


# ---------------------------------------------------------------------------
# _write_discard_idea — ValueError silenced
# ---------------------------------------------------------------------------

class TestWriteDiscardIdeaValueError:
    def test_value_error_silenced(self, tmp_path):
        with patch("autoresearch.engine.append_idea", side_effect=ValueError("bad section")):
            # Should not raise
            _write_discard_idea(tmp_path, "marker", "some idea", 3.5)

    def test_description_and_metric_in_call(self, tmp_path):
        calls = []
        def fake_append(path, name, section, entry):
            calls.append(entry)
        with patch("autoresearch.engine.append_idea", fake_append):
            _write_discard_idea(tmp_path, "marker", "my description", 7.2)
        assert len(calls) == 1
        assert "my description" in calls[0]
        assert "7.2" in calls[0]


# ---------------------------------------------------------------------------
# AgentResult — default telemetry is None
# ---------------------------------------------------------------------------

class TestAgentResultTelemetryDefault:
    def test_default_telemetry_is_none(self):
        r = AgentResult(success=True, description="ok", exit_code=0, output="")
        assert r.telemetry is None

    def test_telemetry_can_be_set(self):
        mock_tel = MagicMock()
        r = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=mock_tel)
        assert r.telemetry is mock_tel

    def test_failed_result_has_output(self):
        r = AgentResult(success=False, description="fail", exit_code=1, output="some error text")
        assert r.output == "some error text"
        assert r.success is False


# ---------------------------------------------------------------------------
# _write_telemetry_feedback — telemetry has no relevant attributes
# ---------------------------------------------------------------------------

class TestWriteTelemetryFeedbackNoAttrs:
    def test_telemetry_without_errors_attr_no_crash(self, tmp_path):
        # Telemetry object with no errors or permission_denials attributes
        class MinimalTelemetry:
            pass
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=MinimalTelemetry())
        from autoresearch.engine import _write_telemetry_feedback
        # Should not raise
        _write_telemetry_feedback(tmp_path, "marker", result)

    def test_telemetry_with_empty_errors_no_write(self, tmp_path):
        mock_tel = MagicMock()
        mock_tel.errors = []
        mock_tel.permission_denials = []
        result = AgentResult(success=True, description="ok", exit_code=0, output="", telemetry=mock_tel)
        from autoresearch.engine import _write_telemetry_feedback
        ideas_path = tmp_path / ".autoresearch" / "marker" / "ideas.md"
        _write_telemetry_feedback(tmp_path, "marker", result)
        assert not ideas_path.exists()


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — no default CLAUDE.md present
# ---------------------------------------------------------------------------

class TestClaudeCodeRunnerNoDefaultClaudeMd:
    def _make_paths(self, tmp_path):
        from autoresearch.agent_profile import AgentPaths
        logs = tmp_path / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        return AgentPaths(
            agent_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
            claude_md_path=tmp_path / "CLAUDE.md",
            logs_dir=logs,
            stream_log_path=logs / "run-ts.jsonl",
            debug_log_path=logs / "debug.log",
        )

    def test_no_append_flag_when_default_claude_md_missing(self, tmp_path):
        marker = _make_marker()
        runner = ClaudeCodeRunner(marker=marker)
        fake_paths = self._make_paths(tmp_path)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=fake_paths),
            patch("autoresearch.engine.subprocess.run", side_effect=fake_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=None),
        ):
            # No CLAUDE.md in tmp_path
            no_claude_md_dir = tmp_path / "no_claude_md"
            no_claude_md_dir.mkdir()
            with patch("autoresearch.agent_profile.DEFAULT_AGENT_DIR", no_claude_md_dir):
                runner.invoke(tmp_path, "test program", "5m")
        assert "--append-system-prompt-file" not in captured["cmd"]

    def test_append_flag_when_default_claude_md_exists(self, tmp_path):
        marker = _make_marker()
        runner_obj = ClaudeCodeRunner(marker=marker)
        fake_paths = self._make_paths(tmp_path)

        # Create a fake CLAUDE.md in the dir
        claude_dir = tmp_path / "with_claude_md"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("agent instructions")

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        with (
            patch("autoresearch.engine.shutil.which", return_value="/usr/bin/claude"),
            patch("autoresearch.agent_profile.ensure_agent_dir", return_value=fake_paths),
            patch("autoresearch.engine.subprocess.run", side_effect=fake_run),
            patch("autoresearch.telemetry.parse_stream_json", return_value=None),
            patch("autoresearch.telemetry.save_telemetry_report"),
            patch("autoresearch.telemetry.extract_description_from_telemetry", return_value=None),
        ):
            with patch("autoresearch.agent_profile.DEFAULT_AGENT_DIR", claude_dir):
                runner_obj.invoke(tmp_path, "test program", "5m")
        assert "--append-system-prompt-file" in captured["cmd"]


# ---------------------------------------------------------------------------
# run_marker — cleanup_worktree=True with GitError
# ---------------------------------------------------------------------------

class TestRunMarkerCleanupGitError:
    def test_cleanup_worktree_git_error_logged_not_raised(self, git_repo, tmp_path):
        from autoresearch.worktree import GitError
        # Agent fails -> discard path; cleanup_worktree=True but remove raises GitError
        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))
        runner = FakeAgentRunner([AgentResult(True, "no-op", 0, "")])
        with patch("autoresearch.engine.remove_worktree", side_effect=GitError("cleanup failed")):
            result = run_marker(
                git_repo, marker, _make_state(), _make_tracked(),
                runner, worktree_base=tmp_path / "wt", cleanup_worktree=True,
            )
        assert result is not None


# ---------------------------------------------------------------------------
# run_marker — final_confidence None when no kept experiments
# ---------------------------------------------------------------------------

class TestRunMarkerFinalConfidence:
    def test_final_confidence_none_when_no_kept(self, git_repo, tmp_path):
        runner = FakeAgentRunner([AgentResult(True, "no-op", 0, "")])
        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            runner, worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.kept == 0

    @patch("autoresearch.engine.run_harness")
    def test_final_confidence_set_when_kept(self, mock_harness, git_repo, tmp_path):
        mock_harness.return_value = HarnessResult(
            exit_code=0, stdout="10 passed", stderr="",
            metric=10.0, log_path=tmp_path / "run.log",
        )

        class WritingAgent(AgentRunner):
            def __init__(self):
                self.call_count = 0
            def invoke(self, wt, prog, budget):
                self.call_count += 1
                (wt / "src" / "main.py").write_text(f"x = {self.call_count + 100}\n")
                return AgentResult(True, "big improvement", 0, "")

        marker = _make_marker(loop=LoopConfig(max_experiments=1, budget_per_experiment="1m"))
        result = run_marker(
            git_repo, marker, _make_state(), _make_tracked(),
            WritingAgent(), worktree_base=tmp_path / "wt", cleanup_worktree=False,
        )
        assert result.kept >= 1


# ---------------------------------------------------------------------------
# _handle_guard_failure — zero attempts
# ---------------------------------------------------------------------------

class TestHandleGuardFailureZeroAttempts:
    def test_zero_attempts_returns_false(self, tmp_path):
        from autoresearch.engine import _handle_guard_failure
        from autoresearch.metrics import GuardResult

        marker = _make_marker()
        runner = FakeAgentRunner([])
        guard_result = GuardResult(passed=False, output="fail", value=None)
        result = _handle_guard_failure(tmp_path, marker, runner, guard_result, 0)
        assert result is False
        assert runner.call_count == 0


# ---------------------------------------------------------------------------
# EscalationState — total_pivots not reset by on_keep
# ---------------------------------------------------------------------------

class TestEscalationStateTotalPivotsPreserved:
    def test_total_pivots_preserved_after_keep(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=3, halt_after_pivots=4)
        for _ in range(5):
            esc.on_discard()
        assert esc.total_pivots == 1
        esc.on_keep()
        assert esc.total_pivots == 1  # NOT reset

    def test_total_pivots_accumulates(self):
        esc = EscalationState(refine_after=3, pivot_after=5, search_after_pivots=3, halt_after_pivots=4)
        for _ in range(5):
            esc.on_discard()
        esc.on_keep()
        for _ in range(5):
            esc.on_discard()
        assert esc.total_pivots == 2


# ---------------------------------------------------------------------------
# telemetry.parse_stream_json — blank line in middle of events (line 46)
# ---------------------------------------------------------------------------


class TestParseStreamJsonBlankLineInMiddle:
    def test_blank_line_between_events_skipped(self):
        import json as _json
        from autoresearch.telemetry import parse_stream_json

        e1 = _json.dumps({"type": "system", "subtype": "init", "session_id": "abc123", "tools": []})
        e2 = _json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.002,
                          "duration_ms": 500, "duration_api_ms": 400, "num_turns": 1,
                          "stop_reason": "end_turn", "permission_denials": []})
        output = e1 + "\n\n\n" + e2
        report = parse_stream_json(output)
        assert report.session_id == "abc123"
        assert report.total_cost_usd == 0.002

    def test_whitespace_only_line_between_events_skipped(self):
        import json as _json
        from autoresearch.telemetry import parse_stream_json

        e1 = _json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.001,
                          "duration_ms": 100, "duration_api_ms": 90, "num_turns": 1,
                          "stop_reason": "end_turn", "permission_denials": []})
        output = "   \n" + e1
        report = parse_stream_json(output)
        assert report.total_cost_usd == 0.001


# ---------------------------------------------------------------------------
# telemetry.extract_description — all lines too short → returns None (line 95)
# ---------------------------------------------------------------------------


class TestExtractDescriptionAllShortLines:
    def test_returns_none_when_all_lines_too_short(self):
        from autoresearch.telemetry import TelemetryReport, extract_description_from_telemetry

        report = TelemetryReport(result_text="ab\nxy\n  z ")
        result = extract_description_from_telemetry(report)
        assert result is None

    def test_returns_none_for_single_char_lines(self):
        from autoresearch.telemetry import TelemetryReport, extract_description_from_telemetry

        report = TelemetryReport(result_text="a\nb\nc")
        result = extract_description_from_telemetry(report)
        assert result is None

    def test_whitespace_only_after_strip_returns_none(self):
        from autoresearch.telemetry import TelemetryReport, extract_description_from_telemetry

        report = TelemetryReport(result_text="\n  \n\t\n")
        result = extract_description_from_telemetry(report)
        assert result is None


# ---------------------------------------------------------------------------
# metrics._extract_metric — TimeoutExpired (lines 148-149)
# ---------------------------------------------------------------------------


class TestExtractMetricTimeout:
    def test_timeout_returns_none(self):
        from autoresearch.metrics import _extract_metric

        with patch("autoresearch.metrics.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd=["bash"], timeout=10)):
            result = _extract_metric("some output", "grep -oP '\\d+'")
        assert result is None

    def test_value_error_in_extraction_returns_none(self):
        from autoresearch.metrics import _extract_metric

        with patch("autoresearch.metrics.subprocess.run",
                   side_effect=ValueError("conversion failed")):
            result = _extract_metric("output", "extract")
        assert result is None


