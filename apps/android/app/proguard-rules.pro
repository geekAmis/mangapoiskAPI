# Keep metadata used by Retrofit and kotlinx.serialization.
-keepattributes Signature, InnerClasses, EnclosingMethod, *Annotation*, RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations

# kotlinx.serialization generated serializers
-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class ru.mangapoisk.reborn.**$$serializer { *; }
-keepclassmembers class ru.mangapoisk.reborn.** {
    *** Companion;
}
-keepclasseswithmembers class ru.mangapoisk.reborn.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclassmembers @kotlinx.serialization.Serializable class ru.mangapoisk.reborn.** {
    *** INSTANCE;
    kotlinx.serialization.KSerializer serializer(...);
}

# Retrofit / OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**
-dontwarn org.conscrypt.**
# Tink (used by androidx.security:security-crypto) references errorprone
# annotations that are compile-time only.
-dontwarn com.google.errorprone.annotations.**
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class retrofit2.Response
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation

# Room entities and generated implementations
-keep class ru.mangapoisk.reborn.data.local.entity.** { *; }
-dontwarn androidx.room.paging.**

# WorkManager workers are instantiated reflectively.
-keep class ru.mangapoisk.reborn.download.DownloadWorker { *; }
