import os
import shutil
import time

import granola_audio

print("Granola Recording Test")
print("----------------------")

OUTPUT_DIR = "./test_recordings"

# Clean up previous test
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)

try:
    devices = granola_audio.list_devices()
    mic = next(
        (d for d in devices if d.device_type == granola_audio.DeviceType.Microphone),
        None,
    )

    if not mic:
        print("No microphone found!")
        exit(1)

    print(f"Using microphone: {mic.name} ({mic.id})")

    config = granola_audio.RecordingConfig(
        output_dir=OUTPUT_DIR,
        mic_device_id=mic.id,
        system_audio=False,
        sample_rate=48000,
    )

    print("Starting recording...")
    session = granola_audio.start_recording(config)

    print("Recording for 5 seconds...")
    time.sleep(5)

    print("Stopping recording...")
    session.stop()

    print("Recording stopped.")

    # Verify file
    mic_file = os.path.join(OUTPUT_DIR, "microphone.wav")
    if os.path.exists(mic_file):
        size = os.path.getsize(mic_file)
        print(f"Success! Created {mic_file} ({size} bytes)")
    else:
        print(f"Error: {mic_file} not found")

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
