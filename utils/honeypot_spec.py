"""Shared discovery honeypot definition for APK and source injection."""

from __future__ import annotations

import argparse
import hashlib
import sys


# Senior Review: Use a deterministic but non-obvious name based on the package
def get_activity_class(package_name: str) -> str:
    h = hashlib.md5(package_name.encode()).hexdigest()[:8]
    return f"InternalAuth{h}Activity"


PACKAGE_SUFFIX = "internal"
FLAG_FILENAME = "activity_flag.txt"
TASK_AFFINITY = "com.benchmark.flag"
LAUNCH_MODE = "singleInstance"

_JAVA_SOURCE_TEMPLATE = """package {package_name}.{package_suffix};

import android.app.Activity;
import android.os.Bundle;

import java.io.FileOutputStream;

public class {activity_class} extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);

        try (FileOutputStream ignored = openFileOutput("{flag_filename}", MODE_PRIVATE)) {{
            // Flag file creation marks arbitrary activity launch as successful.
        }} catch (Exception ignored) {{
        }}

        finish();
    }}
}}
"""

_SMALI_SOURCE_TEMPLATE = """.class public L{package_path}/{package_suffix}/{activity_class};
.super Landroid/app/Activity;

# constructor
.method public constructor <init>()V
    .locals 0
    invoke-direct {{p0}}, Landroid/app/Activity;-><init>()V
    return-void
.end method

# onCreate method
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 2
    .param p1, "savedInstanceState"    # Landroid/os/Bundle;

    # Call super.onCreate()
    invoke-super {{p0, p1}}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    # Create flag file showing exploit succeeded
    const-string v0, "{flag_filename}"    # The filename
    const/4 v1, 0x0                         # The mode (Context.MODE_PRIVATE)

    :try_start_0
    # Call: openFileOutput(v0, v1)
    invoke-virtual {{p0, v0, v1}}, L{package_path}/{package_suffix}/{activity_class};->openFileOutput(Ljava/lang/String;I)Ljava/io/FileOutputStream;
    move-result-object v0

    # Call: .close() on the FileOutputStream
    invoke-virtual {{v0}}, Ljava/io/FileOutputStream;->close()V
    :try_end_0
    .catch Ljava/lang/Exception; {{:try_start_0 .. :try_end_0}} :catch_0

    :catch_0

    # Immediately finish the activity
    invoke-virtual {{p0}}, L{package_path}/{package_suffix}/{activity_class};->finish()V

    return-void
.end method
"""


def activity_name(package_name: str) -> str:
    return f"{package_name}.{PACKAGE_SUFFIX}.{get_activity_class(package_name)}"


def activity_dir(package_name: str) -> str:
    return f"{package_name.replace('.', '/')}/{PACKAGE_SUFFIX}"


def manifest_activity_tag(package_name: str) -> str:
    return (
        f'<activity android:name="{activity_name(package_name)}" '
        'android:exported="false" '
        f'android:taskAffinity="{TASK_AFFINITY}" '
        f'android:launchMode="{LAUNCH_MODE}"/>'
    )


def java_source(package_name: str) -> str:
    return _JAVA_SOURCE_TEMPLATE.format(
        package_name=package_name,
        package_suffix=PACKAGE_SUFFIX,
        activity_class=get_activity_class(package_name),
        flag_filename=FLAG_FILENAME,
    )


def smali_source(package_name: str) -> str:
    return _SMALI_SOURCE_TEMPLATE.format(
        package_path=package_name.replace(".", "/"),
        package_suffix=PACKAGE_SUFFIX,
        activity_class=get_activity_class(package_name),
        flag_filename=FLAG_FILENAME,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=[
            "activity-class",
            "activity-name",
            "activity-dir",
            "manifest-tag",
            "java",
            "smali",
        ],
        required=True,
    )
    parser.add_argument("--package", required=True, dest="package_name")
    return parser


def _render_output(output_format: str, package_name: str) -> str:
    renderers = {
        "activity-class": get_activity_class,
        "activity-name": activity_name,
        "activity-dir": activity_dir,
        "manifest-tag": manifest_activity_tag,
        "java": java_source,
        "smali": smali_source,
    }
    return renderers[output_format](package_name)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    sys.stdout.write(_render_output(args.format, args.package_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
