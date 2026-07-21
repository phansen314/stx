# Go stx CLI (transition build). The daemon is still built via Gradle; this only covers the
# Go client. Python remains the default bin/stx until Go reaches parity.
GO_BIN    := bin/stx-go
GO_PKG    := ./cmd/stx
VERSION   := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS   := -X github.com/phansen314/stx/internal/version.Version=$(VERSION)

.PHONY: go go-test parity go-tidy

go: ## build the Go client → bin/stx-go
	go build -ldflags "$(LDFLAGS)" -o $(GO_BIN) $(GO_PKG)

go-test: ## run the Go unit tests
	go test ./...

go-tidy: ## sync go.mod / go.sum
	go mod tidy

parity: go ## diff Go vs the Python oracle against a live daemon
	./scripts/parity.sh
