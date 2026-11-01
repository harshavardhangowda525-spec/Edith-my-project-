import java.net.URI
import java.util.zip.ZipInputStream

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Offline speech model used for the "Edith" wake word (Vosk, Apache-2.0, ~40 MB).
// Downloaded at build time into build/ (not committed) and packed into the APK.
val voskModelName = "vosk-model-small-en-us-0.15"
val voskModelUrl = "https://alphacephei.com/vosk/models/$voskModelName.zip"
val voskAssetsDir = layout.buildDirectory.dir("generated/vosk-assets")

val fetchVoskModel by tasks.registering {
    description = "Downloads the Vosk wake-word model into the APK assets"
    val outDir = voskAssetsDir
    outputs.dir(outDir)
    doLast {
        val target = outDir.get().asFile.resolve("model-en-us")
        if (target.resolve("uuid").readTextOrNull() == voskModelName) return@doLast
        target.deleteRecursively()
        target.mkdirs()
        ZipInputStream(URI(voskModelUrl).toURL().openStream().buffered()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val rel = entry.name.substringAfter('/', "")
                if (rel.isEmpty()) continue
                val file = target.resolve(rel)
                if (entry.isDirectory) file.mkdirs()
                else {
                    file.parentFile.mkdirs()
                    file.outputStream().use { zip.copyTo(it) }
                }
            }
        }
        // StorageService copies the model out of the APK only when this marker changes.
        target.resolve("uuid").writeText(voskModelName)
    }
}

fun File.readTextOrNull(): String? = if (isFile) readText() else null

android {
    namespace = "ai.edith.assistant"
    compileSdk = 35

    defaultConfig {
        applicationId = "ai.edith.assistant"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0.${System.getenv("GITHUB_RUN_NUMBER") ?: "0"}"
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a") // phones; keeps the APK smaller
        }
    }

    sourceSets["main"].assets.srcDir(voskAssetsDir)
    packaging {
        jniLibs.useLegacyPackaging = true // compress native libraries: smaller download
    }

    // A fixed signing key so new versions install over old ones (keeping your settings).
    // See android/README.md. Override with your own key via environment variables.
    signingConfigs {
        create("sideload") {
            storeFile = file(System.getenv("EDITH_KEYSTORE") ?: "../keystore/edith-sideload.jks")
            storePassword = System.getenv("EDITH_KEYSTORE_PASSWORD") ?: "edith-sideload"
            keyAlias = System.getenv("EDITH_KEY_ALIAS") ?: "edith"
            keyPassword = System.getenv("EDITH_KEY_PASSWORD") ?: "edith-sideload"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("sideload")
        }
        debug {
            signingConfig = signingConfigs.getByName("sideload")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("com.alphacephei:vosk-android:0.3.75@aar")
    implementation("net.java.dev.jna:jna:5.18.1@aar")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}

tasks.named("preBuild") { dependsOn(fetchVoskModel) }
