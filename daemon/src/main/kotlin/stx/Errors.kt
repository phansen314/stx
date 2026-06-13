package stx

/**
 * Service-layer error taxonomy. The HTTP façade maps each to a status code:
 *   Validation → 400, NotFound → 404, Conflict → 409.
 * Anything else is an unhandled 500.
 */
sealed class StxException(message: String) : RuntimeException(message) {
    /** Bad input or a violated invariant (cycle, illegal status move, bad shape). */
    class Validation(message: String) : StxException(message)

    /** A referenced entity does not exist (or is archived where a live one is required). */
    class NotFound(message: String) : StxException(message)

    /** A uniqueness/state conflict (e.g. duplicate live edge, second root segment). */
    class Conflict(message: String) : StxException(message)
}
