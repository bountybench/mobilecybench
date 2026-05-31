# Per-app R8 keep rules for owncloud-android. Picked up by
# gradle/obfuscate.init.gradle when MCB_OBFUSCATE=1.
#
# OkHttp ships compile-time references to three optional TLS providers
# (BouncyCastle JSSE, Conscrypt, OpenJSSE) via its Platform subclasses.
# Those classes are only present at runtime when the consumer adds the
# corresponding dependency; owncloud-android does not. Android's class
# loader resolves these lazily at runtime, so default (non-R8) builds are
# fine. R8 in release mode resolves references at build time and fails
# with "Missing classes detected" unless we tell it these absences are
# expected.
#
# -dontwarn is the standard suppression for "class genuinely not on the
# classpath; do not error on unresolved references to it." It does NOT
# affect the produced bytecode — OkHttp's Platform code path that
# references these classes is unreachable at runtime when the deps are
# absent.
-dontwarn org.bouncycastle.jsse.**
-dontwarn org.conscrypt.**
-dontwarn org.openjsse.**
