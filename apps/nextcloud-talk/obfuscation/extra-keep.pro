# Optional runtime bindings/classes referenced by transitive dependencies but
# absent from the packaged app. The non-obfuscated release build already ships
# without them; R8 needs explicit warning suppression when obfuscation is forced
# by the benchmark init script.
-dontwarn com.google.common.base.Objects$ToStringHelper
-dontwarn org.slf4j.impl.StaticLoggerBinder
