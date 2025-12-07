import os
import wave

from quinoa.transcription.processor import create_stereo_mix


def test_mixing():
    output_dir = "/tmp/quinoa_test"
    mic_path = os.path.join(output_dir, "microphone.wav")
    sys_path = os.path.join(output_dir, "system.wav")
    stereo_path = os.path.join(output_dir, "mixed_stereo.wav")

    print(f"Mixing {mic_path} and {sys_path}...")

    if not os.path.exists(mic_path) or not os.path.exists(sys_path):
        print("Input files missing. Run test_audio.py first.")
        return

    try:
        create_stereo_mix(mic_path, sys_path, stereo_path)
        print(f"Created {stereo_path}")

        if os.path.exists(stereo_path):
            size = os.path.getsize(stereo_path)
            print(f"Size: {size} bytes")

            with wave.open(stereo_path, "rb") as wav:
                print(f"Channels: {wav.getnchannels()}")
                print(f"Rate: {wav.getframerate()}")
                print(f"Width: {wav.getsampwidth()}")
                print(f"Frames: {wav.getnframes()}")

                if wav.getnchannels() == 2:
                    print("SUCCESS: Output is stereo")
                else:
                    print("FAILURE: Output is not stereo")
        else:
            print("FAILURE: File not created")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_mixing()
