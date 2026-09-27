import argparse
from pathlib import Path

from audio_processing import prepare_wav
from classifier import SoundClassifier
from uploads import MAX_FILE_BYTES


def main():
    parser = argparse.ArgumentParser(description="Classify a local WAV fixture.")
    parser.add_argument("file", nargs="?", type=Path, default=Path(__file__).parent / "crash.wav")
    args = parser.parse_args()
    with args.file.open("rb") as file:
        data = file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        parser.error("Maximum WAV size is 5 MB.")
    audio = prepare_wav(data)
    classifier = SoundClassifier()
    classifier.warm_up()
    result = classifier.classify(audio)
    if result is None:
        print("No supported sound met the detection threshold.")
    else:
        print("Detected sound:", result["label"])
        print("Model score:", round(result["score"], 3))


if __name__ == "__main__":
    main()
