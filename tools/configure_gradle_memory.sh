#!/usr/bin/env bash
set -eu

get_cgroup_mem_mb() {
  if [ -r /sys/fs/cgroup/memory.max ]; then
    val=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo "")
    if [ -n "$val" ] && [ "$val" != "max" ]; then
      echo $(( val / 1024 / 1024 ))
      return
    fi
  fi
  if [ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
    val=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo "")
    if [ -n "$val" ] && [ "$val" -gt 0 ] 2>/dev/null; then
      if [ "$val" -lt $((1024**4)) ]; then
        echo $(( val / 1024 / 1024 ))
        return
      fi
    fi
  fi
  awk '/MemTotal/ {print int($2/1024); exit}' /proc/meminfo 2>/dev/null || echo 2048
}

total_mb=$(get_cgroup_mem_mb)
: "${BUILD_RESERVE_MB:=512}"
: "${BUILD_MAX_METASPACE_MB:=512}"
: "${BUILD_MAX_HEAP_MB:=2048}"
if [ "$total_mb" -le 0 ]; then total_mb=2048; fi

avail_mb=$(( total_mb - BUILD_RESERVE_MB ))
[ "$avail_mb" -lt 1024 ] && avail_mb=1024

if [ "${BUILD_MAX_HEAP_MB}" -gt 0 ] 2>/dev/null; then
  heap_mb=$(( BUILD_MAX_HEAP_MB ))
else
  heap_mb=$(( avail_mb - 256 ))
fi

[ "$heap_mb" -lt 512 ] && heap_mb=512
[ "$heap_mb" -gt $(( total_mb - 128 )) ] && heap_mb=$(( total_mb - 128 ))

max_metaspace_mb=$(( BUILD_MAX_METASPACE_MB ))
mkdir -p /root/.gradle

cat > /root/.gradle/gradle.properties <<EOF
org.gradle.daemon=false
org.gradle.parallel=false
org.gradle.configureondemand=false
android.aapt2FromMavenOverride=/usr/bin/aapt2

org.gradle.jvmargs=-Xms256m -Xmx${heap_mb}m -XX:MaxMetaspaceSize=${max_metaspace_mb}m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8
kotlin.compiler.execution.strategy=daemon
kotlin.daemon.jvm.options=-Xmx1536m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8
org.gradle.workers.max=1
EOF

mkdir -p /etc/profile.d
cat > /etc/profile.d/gradle_memory.sh <<EOENV
export JAVA_TOOL_OPTIONS="-Xmx${heap_mb}m -XX:MaxMetaspaceSize=${max_metaspace_mb}m -Dfile.encoding=UTF-8"
export GRADLE_OPTS="-Xmx${heap_mb}m -XX:MaxMetaspaceSize=${max_metaspace_mb}m -Dfile.encoding=UTF-8"
EOENV

if [ -d /root/.gradle/daemon ]; then
  find /root/.gradle/daemon -name '*.pid' -print0 2>/dev/null | xargs -0 -r sh -c 'for f; do kill -9 $(cat "$f") >/dev/null 2>&1 || true; done' _
  rm -rf /root/.gradle/daemon/*
fi

echo "[INFO] total_mb=${total_mb} reserve_mb=${BUILD_RESERVE_MB} avail_mb=${avail_mb} heap_mb=${heap_mb} metaspace_mb=${max_metaspace_mb}"