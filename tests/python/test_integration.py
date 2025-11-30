import os
import shutil
import time

import pytest

import granola_audio


@pytest.fixture
def output_dir():
    path = "/tmp/granola_test_integration"
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    yield path
    if os.path.exists(path):
        shutil.rmtree(path)


def test_recording_lifecycle(output_dir):
    """
    Test the full lifecycle of a recording session using the mock backend.
    """
    # 1. Configure
    config = granola_audio.RecordingConfig(
        output_dir=output_dir,
        mic_device_id="mock_mic",
        system_audio=True,
        sample_rate=48000,
    )

    # 2. Start
    session = granola_audio.start_recording(config)
    assert session is not None

    # 3. Poll for events
    # We expect 'started' and then 'levels'
    started = False
    levels_received = False

    start_time = time.time()
    while time.time() - start_time < 2.0:
        events = session.poll_events()
        for event in events:
            if event.type_ == "started":
                started = True
            elif event.type_ == "levels":
                levels_received = True
                # Verify levels are valid floats
                if event.mic_level is not None:
                    assert 0.0 <= event.mic_level <= 1.0
                if event.system_level is not None:
                    assert 0.0 <= event.system_level <= 1.0

        if started and levels_received:
            break
        time.sleep(0.1)

    assert started, "Did not receive 'started' event"
    assert levels_received, "Did not receive 'levels' event"

    # 4. Stop
    session.stop()

    # 5. Verify stopped event
    stopped = False
    start_time = time.time()
    while time.time() - start_time < 1.0:
        events = session.poll_events()
        for event in events:
            if event.type_ == "stopped":
                stopped = True
        if stopped:
            break
        time.sleep(0.1)

    assert stopped, "Did not receive 'stopped' event"
