"""Explicit, online setup step. The API itself never downloads a model."""
import argparse
import os
from pathlib import Path
import shutil


MODEL_URL = "https://tfhub.dev/google/yamnet/1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "models" / "yamnet")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Output already exists. Choose a new directory to avoid overwriting a model.")
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["TFHUB_CACHE_DIR"] = str(output.parent / ".tfhub-cache")
    import tensorflow_hub as hub

    cached = Path(hub.resolve(MODEL_URL))
    if not (cached / "saved_model.pb").is_file():
        raise RuntimeError("The download did not contain a SavedModel.")
    shutil.copytree(cached, output)
    print(f"Downloaded {MODEL_URL} to {output}")
    print("Set MODEL_DIR to this directory before starting the API.")


if __name__ == "__main__":
    main()
