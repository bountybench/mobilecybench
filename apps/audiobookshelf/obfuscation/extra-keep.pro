# OkHttp probes optional TLS providers reflectively. Audiobookshelf does not
# package these provider jars, so suppress R8 missing-class errors for those
# dormant integration paths when obfuscation enables release minification.
-dontwarn org.bouncycastle.jsse.BCSSLParameters
-dontwarn org.bouncycastle.jsse.BCSSLSocket
-dontwarn org.bouncycastle.jsse.provider.BouncyCastleJsseProvider
-dontwarn org.conscrypt.Conscrypt
-dontwarn org.conscrypt.Conscrypt$Version
-dontwarn org.conscrypt.ConscryptHostnameVerifier
-dontwarn org.openjsse.javax.net.ssl.SSLParameters
-dontwarn org.openjsse.javax.net.ssl.SSLSocket
-dontwarn org.openjsse.net.ssl.OpenJSSE

# Capacitor dispatches native plugin methods from JavaScript by their source
# method names. Keep only that bridge surface stable so R8 can still obfuscate
# unrelated application code.
-keep @com.getcapacitor.annotation.CapacitorPlugin class com.audiobookshelf.app.plugins.** { *; }
-keepclassmembers class com.audiobookshelf.app.plugins.** {
    @com.getcapacitor.PluginMethod <methods>;
}

# Login and device-state setup bind Kotlin/Jackson payloads reflectively.
# Preserve model metadata and members used by that serializer boundary.
-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod,RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,RuntimeInvisibleAnnotations,RuntimeInvisibleParameterAnnotations
-keep class kotlin.Metadata { *; }
-keep class kotlin.reflect.** { *; }
-keep class com.fasterxml.jackson.module.kotlin.** { *; }
-keep class com.audiobookshelf.app.data.** { *; }
-keep enum com.audiobookshelf.app.data.** { *; }
-keep class com.audiobookshelf.app.models.** { *; }
-keep class com.audiobookshelf.app.plugins.**$* { *; }
-keep class com.audiobookshelf.app.server.**$* { *; }

# PaperDB/Kryo persists DeviceData during login. Its ProGuard guidance requires
# preserving Kotlin empty collection implementations when models may contain
# emptyList/emptyMap/emptySet values.
-keep class kotlin.collections.* { *; }
