import argparse
import json
import os
import sys


def get_directory_from_args():
    parser = argparse.ArgumentParser(
        description="Argument Parser for Directory - Generic Probes"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="",
        help="Directory to scan for probes (default: current directory)",
    )

    args, _ = parser.parse_known_args()
    return f"{os.getcwd()}/{args.directory}"


def get_metadata():
    with open(f"{get_directory_from_args()}/metadata.json", "r") as f:
        metadata = json.load(f)

    if not metadata:
        print("Metadata not found. Exiting with error code 2.")
        sys.exit(2)

    return metadata
