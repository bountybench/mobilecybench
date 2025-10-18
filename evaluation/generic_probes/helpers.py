import argparse

from utils.utils import get_app_metadata


def get_metadata_from_args():
    parser = argparse.ArgumentParser(
        description="Argument Parser for Directory - Generic Probes"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="",
        help="Directory to scan for metadata and probes (default: current directory)",
    )

    args, _ = parser.parse_known_args()
    return get_app_metadata(f"{args.directory}")
