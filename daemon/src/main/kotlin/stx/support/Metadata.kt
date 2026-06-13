package stx.support

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import stx.Metadata

/**
 * Codec for the `metadata_json` blob columns. We model metadata as a flat string→string map
 * (the design's `jira_key`, `deadline`, … are all scalar strings). Stored as a JSON object;
 * decoding tolerates non-string scalar values by coercing them to their text form.
 */
object MetadataCodec {
    private val json = Json { ignoreUnknownKeys = true }

    fun encode(metadata: Metadata): String =
        JsonObject(metadata.mapValues { (_, v) -> JsonPrimitive(v) }).toString()

    fun decode(text: String?): Metadata {
        if (text.isNullOrBlank()) return emptyMap()
        val obj = json.parseToJsonElement(text).jsonObject
        return obj.mapValues { (_, v) -> v.jsonPrimitive.content }
    }
}
