# Go stx CLI. The daemon is built via Gradle; this only covers the Go client, which is the
# sole stx client (bin/stx → bin/stx-go).
GO_BIN    := bin/stx-go
GO_PKG    := ./cmd/stx
VERSION   := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS   := -X github.com/phansen314/stx/internal/version.Version=$(VERSION)

.PHONY: go go-test go-tidy

go: ## build the Go client → bin/stx-go
	go build -ldflags "$(LDFLAGS)" -o $(GO_BIN) $(GO_PKG)

go-test: ## run the Go unit tests
	go test ./...

go-tidy: ## sync go.mod / go.sum
	go mod tidy
