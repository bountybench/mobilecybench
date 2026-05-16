#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR/repo"
PACKAGE_NAME="mobilecybench-termux-online"
PACKAGE_VERSION="1.0.0"
PACKAGE_ARCH="all"
SUITE="mobilecybench"
COMPONENT="main"
DESCRIPTION_SHORT="Deterministic local-repo validation tool for the MobileCyBench Termux benchmark"
DESCRIPTION_LONG=" This package installs mcb-online-check so the benchmark can require a real"
DESCRIPTION_LONG_2=" package-manager flow against a controlled local mirror."
POOL_DIR="$REPO_DIR/pool/$COMPONENT/m/$PACKAGE_NAME"
PACKAGE_FILE="$POOL_DIR/${PACKAGE_NAME}_${PACKAGE_VERSION}_${PACKAGE_ARCH}.deb"

hash_file() {
    local algo="$1"
    local path="$2"
    python3 - "$algo" "$path" <<'PY'
import hashlib
import pathlib
import sys

algo = sys.argv[1]
path = pathlib.Path(sys.argv[2])
h = hashlib.new(algo)
with path.open("rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
}

build_package() {
    local staging
    staging="$(mktemp -d)"
    trap 'rm -rf "$staging"' RETURN

    local pkg_root="$staging/${PACKAGE_NAME}_${PACKAGE_VERSION}_${PACKAGE_ARCH}"
    local debian_dir="$pkg_root/DEBIAN"
    local bin_dir="$pkg_root/data/data/data/com.termux/files/usr/bin"

    mkdir -p "$debian_dir" "$bin_dir" "$POOL_DIR"

    cat > "$debian_dir/control" <<EOF
Package: ${PACKAGE_NAME}
Version: ${PACKAGE_VERSION}
Architecture: ${PACKAGE_ARCH}
Maintainer: MobileCyBench <noreply@example.invalid>
Installed-Size: 1
Section: utils
Priority: optional
Description: ${DESCRIPTION_SHORT}
${DESCRIPTION_LONG}
${DESCRIPTION_LONG_2}
EOF

    cat > "$bin_dir/mcb-online-check" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
set -eu
printf 'mcb-online-check: local repo package is installed\n'
EOF
    chmod 0755 "$bin_dir/mcb-online-check"

    python3 - "$pkg_root" "$PACKAGE_FILE" <<'PY'
import gzip
import io
import pathlib
import stat
import tarfile
import sys

pkg_root = pathlib.Path(sys.argv[1])
package_file = pathlib.Path(sys.argv[2])


def add_tree(tar: tarfile.TarFile, root: pathlib.Path, prefix: pathlib.Path) -> None:
    for path in sorted(root.rglob("*")):
        arcname = prefix / path.relative_to(root)
        info = tar.gettarinfo(str(path), arcname=str(arcname))
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        info.mtime = 0
        if path.is_file():
            with path.open("rb") as fh:
                tar.addfile(info, fh)
        else:
            tar.addfile(info)


def gzipped_tar_from(root: pathlib.Path, prefix: pathlib.Path) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            add_tree(tar, root, prefix)
    return buffer.getvalue()


def ar_header(name: str, size: int) -> bytes:
    fields = [
        f"{name}/".ljust(16),
        str(0).rjust(12),
        str(0).rjust(6),
        str(0).rjust(6),
        oct(stat.S_IFREG | 0o644)[2:].rjust(8),
        str(size).rjust(10),
        "`\n",
    ]
    return "".join(fields).encode("ascii")


def write_ar_member(fh, name: str, payload: bytes) -> None:
    fh.write(ar_header(name, len(payload)))
    fh.write(payload)
    if len(payload) % 2 == 1:
        fh.write(b"\n")


control_payload = gzipped_tar_from(pkg_root / "DEBIAN", pathlib.Path("."))
data_payload = gzipped_tar_from(pkg_root / "data", pathlib.Path("."))

package_file.parent.mkdir(parents=True, exist_ok=True)
with package_file.open("wb") as fh:
    fh.write(b"!<arch>\n")
    write_ar_member(fh, "debian-binary", b"2.0\n")
    write_ar_member(fh, "control.tar.gz", control_payload)
    write_ar_member(fh, "data.tar.gz", data_payload)
PY
}

write_packages_index() {
    local arch="$1"
    local packages_dir="$REPO_DIR/dists/$SUITE/$COMPONENT/binary-$arch"
    local packages_file="$packages_dir/Packages"
    local packages_gz="$packages_dir/Packages.gz"
    local package_size
    local md5sum
    local sha1sum
    local sha256sum
    mkdir -p "$packages_dir"

    package_size="$(wc -c < "$PACKAGE_FILE" | tr -d '[:space:]')"
    md5sum="$(hash_file md5 "$PACKAGE_FILE")"
    sha1sum="$(hash_file sha1 "$PACKAGE_FILE")"
    sha256sum="$(hash_file sha256 "$PACKAGE_FILE")"

    cat > "$packages_file" <<EOF
Package: ${PACKAGE_NAME}
Version: ${PACKAGE_VERSION}
Architecture: ${PACKAGE_ARCH}
Maintainer: MobileCyBench <noreply@example.invalid>
Installed-Size: 1
Section: utils
Priority: optional
Filename: ${PACKAGE_FILE#"$REPO_DIR/"}
Size: ${package_size}
MD5sum: ${md5sum}
SHA1: ${sha1sum}
SHA256: ${sha256sum}
Description: ${DESCRIPTION_SHORT}
${DESCRIPTION_LONG}
${DESCRIPTION_LONG_2}

EOF

    gzip -n -c "$packages_file" > "$packages_gz"
}

write_release_file() {
    local release_dir="$REPO_DIR/dists/$SUITE"
    local release_file="$release_dir/Release"
    local files=(
        "main/binary-aarch64/Packages"
        "main/binary-aarch64/Packages.gz"
        "main/binary-arm/Packages"
        "main/binary-arm/Packages.gz"
        "main/binary-i686/Packages"
        "main/binary-i686/Packages.gz"
        "main/binary-x86_64/Packages"
        "main/binary-x86_64/Packages.gz"
        "main/binary-all/Packages"
        "main/binary-all/Packages.gz"
    )

    {
        printf 'Origin: MobileCyBench\n'
        printf 'Label: MobileCyBench Termux Local Repo\n'
        printf 'Suite: %s\n' "$SUITE"
        printf 'Codename: %s\n' "$SUITE"
        printf 'Version: 1.0\n'
        printf 'Architectures: all aarch64 arm i686 x86_64\n'
        printf 'Components: %s\n' "$COMPONENT"
        printf 'Description: Deterministic local package repo for the MobileCyBench Termux benchmark\n'
        printf 'Date: Mon, 01 Jan 2024 00:00:00 UTC\n'
        printf 'MD5Sum:\n'
        for rel in "${files[@]}"; do
            printf ' %s %s %s\n' \
                "$(hash_file md5 "$release_dir/$rel")" \
                "$(wc -c < "$release_dir/$rel" | tr -d '[:space:]')" \
                "$rel"
        done
        printf 'SHA1:\n'
        for rel in "${files[@]}"; do
            printf ' %s %s %s\n' \
                "$(hash_file sha1 "$release_dir/$rel")" \
                "$(wc -c < "$release_dir/$rel" | tr -d '[:space:]')" \
                "$rel"
        done
        printf 'SHA256:\n'
        for rel in "${files[@]}"; do
            printf ' %s %s %s\n' \
                "$(hash_file sha256 "$release_dir/$rel")" \
                "$(wc -c < "$release_dir/$rel" | tr -d '[:space:]')" \
                "$rel"
        done
    } > "$release_file"
}

rm -rf "$REPO_DIR"
mkdir -p "$POOL_DIR"

build_package
for arch in aarch64 arm i686 x86_64 all; do
    write_packages_index "$arch"
done
write_release_file

printf 'Built Termux local repo at %s\n' "$REPO_DIR"
