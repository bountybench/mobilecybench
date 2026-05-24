# Optional tinylog runtime integrations reference JVM/server APIs that are not
# present on Android. The app does not use those paths; suppress R8 missing-class
# errors when the repo obfuscation init script enables release minification.
-dontwarn dalvik.system.VMStack
-dontwarn java.lang.ProcessHandle
-dontwarn java.lang.management.ManagementFactory
-dontwarn java.lang.management.RuntimeMXBean
-dontwarn javax.naming.InitialContext
-dontwarn javax.naming.NameNotFoundException
-dontwarn javax.naming.NamingException
-dontwarn sun.reflect.Reflection
