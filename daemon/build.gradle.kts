plugins {
    kotlin("jvm") version "2.3.10"
    kotlin("plugin.serialization") version "2.3.10"
    application
}

repositories {
    mavenCentral()
}

dependencies {
    // HTTP server (loopback only). SunHttp server backend ships in http4k-core.
    implementation("org.http4k:http4k-core:5.41.0.0")

    // JSON wire format
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // write-actor coroutine
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")

    // plain JDBC + SQLite (no ORM)
    implementation("org.xerial:sqlite-jdbc:3.50.1.0")

    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
}

kotlin {
    jvmToolchain(21)
}

application {
    mainClass.set("stx.MainKt")
}

tasks.test {
    useJUnitPlatform()
}
