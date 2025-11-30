import os
import time

import granola_audio

print("Granola Audio Test")
print("==================")

# Test 1: List devices
print("\n1. Listing devices...")
try:
    devices = granola_audio.list_devices()
    print(f"Found {len(devices)} devices:")
    mic_device = None
    for device in devices:
        print(f"- {device.name} (ID: {device.id}, Type: {device.device_type})")
        print(
            f"  Bluetooth: {device.is_bluetooth}, Sample Rate: {device.sample_rate}, Channels: {device.channels}, Default: {device.is_default}"
        )
        # Pick first microphone for testing
        if (
            device.device_type == granola_audio.DeviceType.Microphone
            and mic_device is None
        ):
            mic_device = device
except Exception as e:
    print(f"Error listing devices: {e}")
    mic_device = None

# Test 2: Recording
print("\n2. Testing recording...")
if mic_device:
    print(f"Using microphone: {mic_device.name} (ID: {mic_device.id})")

    output_dir = "/tmp/granola_test"
    os.makedirs(output_dir, exist_ok=True)

    config = granola_audio.RecordingConfig(
        output_dir=output_dir,
        mic_device_id=mic_device.id,
        system_audio=True,
        sample_rate=48000,
    )

    print(f"Starting recording to {output_dir}...")
    try:
        session = granola_audio.start_recording(config)
        print("Recording started! Recording for 3 seconds...")
        print("Please play some audio on your system now!")
        time.sleep(3)
        print("Stopping recording...")
        session.stop()
        print("Recording stopped!")

        # Check if files were created
        mic_file = os.path.join(output_dir, "microphone.wav")
        sys_file = os.path.join(output_dir, "system.wav")

        if os.path.exists(mic_file):
            size = os.path.getsize(mic_file)
            print(f"SUCCESS: Created {mic_file} ({size} bytes)")
        else:
            print(f"WARNING: File not created at {mic_file}")

        if os.path.exists(sys_file):
            size = os.path.getsize(sys_file)
            print(f"SUCCESS: Created {sys_file} ({size} bytes)")
        else:
            print(f"WARNING: File not created at {sys_file}")

    except Exception as e:
        print(f"Error during recording: {e}")
else:
    print("No microphone found, skipping recording test")

print("\nTest complete!")
