from reasoning.engine import SYSTEM


def test_system_teaches_future_and_recurring_scheduling():
    assert "SCHEDULING RULE" in SYSTEM
    assert "use schedule_task" in SYSTEM
    assert "every/each day/week/hour" in SYSTEM


def test_system_distinguishes_background_queue_from_schedule():
    assert "Use enqueue_task" in SYSTEM
    assert "background/asynchronously" in SYSTEM
    assert "Do not schedule ordinary immediate requests" in SYSTEM


def test_system_requires_success_before_schedule_confirmation():
    assert "never claim it was scheduled before" in SYSTEM
    assert "tool succeeds" in SYSTEM
