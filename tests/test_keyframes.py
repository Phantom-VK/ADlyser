import pytest

from adlyser.config import BoundaryConfig, ReviewerConfig, StretchConfig
from adlyser.perception.keyframes import boundary_times, stretch_times, sweep_covers_scene, sweep_times

CFG = StretchConfig(frame_interval_s=30, min_frames=3, max_frames=8, tool_rounds=2)


def test_frames_are_spread_evenly_inside_the_stretch():
    assert stretch_times(0, 120, CFG) == pytest.approx([15, 45, 75, 105])


def test_short_stretches_get_the_minimum_number_of_frames():
    assert len(stretch_times(100, 110, CFG)) == 3


def test_long_stretches_are_capped():
    assert len(stretch_times(0, 3000, CFG)) == 8


def test_frames_stay_inside_the_stretch():
    times = stretch_times(200, 500, CFG)
    assert all(200 < t < 500 for t in times)
    assert times == sorted(times)


def test_boundary_frames_are_two_before_then_two_after():
    cfg = BoundaryConfig(frame_offsets_s=[2.0, 0.5])
    assert boundary_times(100.0, cfg, 1000.0) == pytest.approx([98.0, 99.5, 100.5, 102.0])


def test_boundary_frames_are_clamped_to_the_video():
    cfg = BoundaryConfig(frame_offsets_s=[2.0, 0.5])
    times = boundary_times(1.0, cfg, 1000.0)
    assert min(times) >= 0
    times = boundary_times(999.8, cfg, 1000.0)
    assert max(times) < 1000.0


def test_sweep_frames_cover_a_whole_scene_at_about_one_per_interval():
    cfg = ReviewerConfig(
        sweep_interval_s=10, sweep_max_frames=24, tool_rounds=3, speech_window_s=15, max_loops=2
    )
    times = sweep_times(0, 100, cfg)
    assert len(times) == 10 and times[0] < 10 and times[-1] > 90


def test_sweep_frames_are_capped_and_never_empty():
    cfg = ReviewerConfig(
        sweep_interval_s=10, sweep_max_frames=24, tool_rounds=3, speech_window_s=15, max_loops=2
    )
    assert len(sweep_times(0, 3000, cfg)) == 24
    assert len(sweep_times(50, 50.5, cfg)) == 1


def test_sweep_coverage_is_full_only_when_the_cap_does_not_thin_the_frames():
    cfg = ReviewerConfig(
        sweep_interval_s=10, sweep_max_frames=40, tool_rounds=3, speech_window_s=15, max_loops=2
    )
    assert sweep_covers_scene(0, 400, cfg)
    assert not sweep_covers_scene(0, 401, cfg)
    assert sweep_covers_scene(0, 5, cfg)
