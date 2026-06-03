# LoganSquare loads generated mappers reflectively as
# <model class name>$$JsonObjectMapper. Keep model names and mapper names in sync.
-keepattributes Signature,*Annotation*,InnerClasses,EnclosingMethod
-keep class **$$JsonObjectMapper { *; }
-keepnames @com.bluelinelabs.logansquare.annotation.JsonObject class *
-keepclassmembers @com.bluelinelabs.logansquare.annotation.JsonObject class * {
    public <init>();
}

# Retrofit reads service annotations and generic return types at runtime.
-keep interface com.nextcloud.talk.api.** { *; }
-keepclasseswithmembers interface * {
    @retrofit2.http.* <methods>;
}

# WebRTC native code looks up Java helper classes by their original names.
-keep class org.webrtc.** { *; }

# ChatKit stores message ViewHolder classes and instantiates them reflectively.
# R8 can otherwise merge/strip Kotlin constructors, producing abstract classes
# without the required (View) or (View, Object) constructor at chat render time.
-keep class com.nextcloud.talk.adapters.messages.**ViewHolder { *; }

# Optional transitive integrations referenced by libraries but absent in this APK.
-dontwarn com.google.common.base.Objects$ToStringHelper
-dontwarn org.joda.convert.**
-dontwarn org.slf4j.impl.StaticLoggerBinder
