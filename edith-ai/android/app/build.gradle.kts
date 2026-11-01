plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ai.edith.assistant"
    compileSdk = 35

    defaultConfig {
        applicationId = "ai.edith.assistant"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0.${System.getenv("GITHUB_RUN_NUMBER") ?: "0"}"
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
    implementation("ai.picovoice:porcupine-android:4.0.2")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}
