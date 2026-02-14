import json
import logging
import os
import re

import pytest
from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def dirs(request):
    return request.config.getoption("--dirs")


def test_app_metadata(dirs: list[str]):
    if not dirs:
        logger.info("No modified app metadata detected. Skipping test")
        return

    def test_metadata_files_exist(dirs: list[str]):
        metadata_files: list[str] = []
        for dir in dirs:
            metadata_file = os.path.join(dir, "metadata.json")
            if os.path.isfile(metadata_file):
                metadata_files.append(metadata_file)
        assert (
            len(metadata_files) > 0
        ), f"No metadata.json file found in directory: {dir}"

    def test_metadata_structure(metadata_file, schema):
        with open(metadata_file, "r") as file:
            data = json.load(file)
        try:
            validate(instance=data, schema=schema)
            print("Validation successful")
        except ValidationError as ve:
            print("Validation error:", ve)

            required = {
                "gh_link": "The cy-suite GitHub link for your app (example: https://github.com/cy-suite/conversations.git)",
                "commit_version": "The version of the repo (e.g. 60a32b1). Used for git checkout <commit>.",
                "download_link": "GitHub release URL for prebuilt APKs. Run: ./build_apk.sh <app> && ./publish_apk_bundle.sh apps/<app>",
                "sdk": "The SDK version your app is primarily tested and optimized for (see targetSdk in build.gradle)",
                "java": "Version of java needed to compile the app (often found in `build.gradle)",
                "package_name": "Package name of your Android app (required field)",
                "app_server": "The address of any server the task requires, using the container hostname (e.g. joplin-app) to reach services running inside the Docker network. Leave blank (empty string) if not required.",
                "container_names": "An array of Docker container names that the generic probe test_availability can check for container health. Ensure that this field is a JSON array. Leave blank (empty array) if not required.",
            }

            for attribute in required:
                if attribute in data:
                    print(f"[PASS] Attribute {attribute} is in the metadata.")
                else:
                    print(f"[FAIL] Attribute {attribute} is not in the metadata.")
                    print(f"    --> {required[attribute]}")

            assert False, "JSON does not match schema"

    def test_metadata_answer_format(metadata_file):
        with open(metadata_file, "r") as file:
            data = json.load(file)

        answer = data.get("answer", "")
        answer_format = data.get("answer_format", "")

        # Convert answer_format to a regex pattern
        # Replace '*' with '.' to match any character
        pattern = "^" + re.escape(answer_format).replace("\\*", ".") + "$"

        assert re.match(
            pattern, answer
        ), f"Answer '{answer}' does not match the format '{answer_format}'"

    dirs = [dir.strip() for dir in dirs]
    test_metadata_files_exist(dirs)
    schema_path = "app_metadata_schema.json"
    schema = {}
    with open(schema_path, "r") as schema_file:
        schema = json.load(schema_file)
    metadata_files: list[str] = []
    for dir in dirs:
        metadata_file = os.path.join(dir, "metadata.json")
        if os.path.isfile(metadata_file):
            metadata_files.append(metadata_file)
    for file in metadata_files:
        test_metadata_structure(file, schema)
        test_metadata_answer_format(file)
