package stx.transport

import kotlinx.serialization.json.Json

/** Shared kotlinx.serialization config for the wire. `encodeDefaults` so clients see full shapes. */
val Wire: Json = Json {
    encodeDefaults = true
    ignoreUnknownKeys = true
    explicitNulls = true
}
