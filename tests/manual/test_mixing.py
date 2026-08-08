import os
import wave

from quinoa.audio.converter import mix_recording_audio


def test_mixing():
    output_dir = "/tmp/quinoa_test"

    print(f"Mixing audio in {output_dir}...")

    if not os.path.isdir(output_dir):
        print("Output directory missing. Run test_audio.py first.")
        return

    try:
        stereo_path = mix_recording_audio(output_dir)

        if stereo_path is None:
            print("Could not mix audio. Ensure microphone.wav exists.")
            return

        print(f"Created {stereo_path}")

        size = os.path.getsize(stereo_path)
        print(f"Size: {size} bytes")

        with wave.open(str(stereo_path), "rb") as wav:
            print(f"Channels: {wav.getnchannels()}")
            print(f"Rate: {wav.getframerate()}")
            print(f"Width: {wav.getsampwidth()}")
            print(f"Frames: {wav.getnframes()}")

            if wav.getnchannels() == 2:
                print("SUCCESS: Output is stereo")
            else:
                print("FAILURE: Output is not stereo")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_mixing()
