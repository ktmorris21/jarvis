from body_services.picar.scene_monitor import SceneMonitor, SceneMonitorConfig


def test_identical_scene_scores_zero():
    monitor = SceneMonitor.__new__(SceneMonitor)
    monitor.config = SceneMonitorConfig(width=4, height=4, sample_stride=1)
    frame = bytes([100] * 16)
    assert monitor.difference_score(frame, frame) == 0.0


def test_global_brightness_shift_is_discounted():
    monitor = SceneMonitor.__new__(SceneMonitor)
    monitor.config = SceneMonitorConfig(width=4, height=4, sample_stride=1)
    baseline = bytes([80] * 16)
    brighter = bytes([110] * 16)
    assert monitor.difference_score(brighter, baseline) == 0.0


def test_local_scene_change_scores_high():
    monitor = SceneMonitor.__new__(SceneMonitor)
    monitor.config = SceneMonitorConfig(width=4, height=4, sample_stride=1)
    baseline = bytes([100] * 16)
    changed = bytes([30] * 8 + [170] * 8)
    assert monitor.difference_score(changed, baseline) > 60
