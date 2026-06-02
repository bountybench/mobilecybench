# Optional runtime bindings/classes referenced by transitive dependencies but
# absent from the packaged app. The non-obfuscated release build already ships
# without them; R8 needs explicit warning suppression when obfuscation is forced
# by the benchmark init script.
-dontwarn com.google.common.base.Objects$ToStringHelper
-dontwarn org.slf4j.impl.StaticLoggerBinder

# WebRTC's native library reflects into org.webrtc.WebRtcClassLoader during
# PeerConnectionFactory initialization. R8-renaming org.webrtc classes causes
# the obfuscated APK to SIGTRAP on app startup before Talk reaches foreground.
-keep class org.webrtc.** { *; }
