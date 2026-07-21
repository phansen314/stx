// Package version holds the build version, injected via -ldflags at build time.
package version

// Version is set with `-ldflags "-X .../internal/version.Version=<v>"`; "dev" when unset.
var Version = "dev"
