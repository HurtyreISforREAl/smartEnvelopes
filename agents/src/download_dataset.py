from pathlib import Path
import subprocess
import zipfile
import shutil
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--file", default="")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    zip_path = out_dir / "dataset.zip"

    cmd = [
        "kaggle", "datasets", "download",
        "-d", args.dataset,
        "-p", str(out_dir),
        "-o"
    ]

    if args.file:
        cmd.extend(["-f", args.file])

    subprocess.run(cmd, check=True)

    if not zip_path.exists():
        zips = list(out_dir.glob("*.zip"))
        if not zips:
            raise FileNotFoundError("Kaggle archive not found in output directory")
        zip_path = zips[0]

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(raw_dir)

    print(f"Downloaded and extracted to: {raw_dir}")


if __name__ == "__main__":
    main()