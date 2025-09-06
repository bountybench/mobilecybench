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
reserve_mb="${BUILD_RESERVE_MB:-1024}"

if [ "$total_mb" -le 0 ]; then total_mb=2048; fi
avail_mb=$(( total_mb - reserve_mb ))
[ "$avail_mb" -lt 1024 ] && avail_mb=1024

daemon_heap_mb=$(( (avail_mb * 60) / 100 ))
if [ "$daemon_heap_mb" -gt $((avail_mb - 256)) ]; then
  daemon_heap_mb=$((avail_mb - 256))
fi
if [ "$daemon_heap_mb" -lt 1024 ]; then daemon_heap_mb=1024; fi
if [ "$daemon_heap_mb" -gt 6144 ]; then daemon_heap_mb=6144; fi

kotlin_heap_mb=$(( daemon_heap_mb ))
max_metaspace_mb=512
workers=1

mkdir -p /root/.gradle

cat > /root/.gradle/gradle.properties <<EOF
org.gradle.caching=true
org.gradle.daemon=true
org.gradle.parallel=false
org.gradle.configureondemand=true
android.aapt2FromMavenOverride=/usr/bin/aapt2

org.gradle.jvmargs=-Xms512m -Xmx${daemon_heap_mb}m -XX:MaxMetaspaceSize=${max_metaspace_mb}m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8
kotlin.compiler.execution.strategy=in-process
kotlin.daemon.jvmargs=-Xmx${kotlin_heap_mb}m -Dfile.encoding=UTF-8
org.gradle.workers.max=${workers}
EOF

mkdir -p /etc/profile.d
cat > /etc/profile.d/gradle_memory.sh <<EOENV
export JAVA_TOOL_OPTIONS="-Xmx${daemon_heap_mb}m -XX:MaxMetaspaceSize=${max_metaspace_mb}m -Dfile.encoding=UTF-8"
export GRADLE_OPTS="-Xmx${daemon_heap_mb}m -XX:MaxMetaspaceSize=${max_metaspace_mb}m -Dfile.encoding=UTF-8"
EOENV

echo "[INFO] total_mb=${total_mb} reserve_mb=${reserve_mb} avail_mb=${avail_mb} daemon_heap_mb=${daemon_heap_mb} kotlin_heap_mb=${kotlin_heap_mb} metaspace_mb=${max_metaspace_mb} workers=${workers}"