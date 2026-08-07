# Go stx CLI. The daemon is built via Gradle; this only covers the Go client, which is the
# sole stx client (bin/stx → bin/stx-go).
GO_BIN    := bin/stx-go
GO_PKG    := ./cmd/stx
VERSION   := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS   := -X github.com/phansen314/stx/internal/version.Version=$(VERSION)

UNIT      := packaging/systemd/stx.service
UNIT_DIR  := $(HOME)/.config/systemd/user

.PHONY: go go-test go-tidy deploy install-unit

go: ## build the Go client → bin/stx-go
	go build -ldflags "$(LDFLAGS)" -o $(GO_BIN) $(GO_PKG)

go-test: ## run the Go unit tests
	go test ./...

go-tidy: ## sync go.mod / go.sum
	go mod tidy

# `installDist` rewrites build/install/stx/lib/stx-*.jar IN PLACE. A JVM started earlier has the
# zip central directory cached and loads classes lazily, so a daemon left running across the swap
# keeps serving every route it already touched and fails only on the FIRST use of a route it
# hasn't — a failure that looks nothing like "you rebuilt under me". Stopping first makes that
# impossible, which is why deploying is a target and not three commands in a doc.
deploy: ## stop the daemon, rebuild it, start it again (the ONLY safe order)
	systemctl --user stop stx.service
	./gradlew installDist
	systemctl --user start stx.service
	@systemctl --user is-active stx.service

# The unit is SYMLINKED, not copied: a copy silently drifts from the repo the moment either side
# is edited, and nothing warns you. Machine-specific values (JAVA_HOME, PATH) belong in a drop-in
# via `systemctl --user edit stx.service`, never in the tracked unit.
install-unit: ## symlink the systemd user unit and reload
	mkdir -p $(UNIT_DIR)
	ln -sfn $(CURDIR)/$(UNIT) $(UNIT_DIR)/stx.service
	systemctl --user daemon-reload
	@echo "linked $(UNIT_DIR)/stx.service -> $(CURDIR)/$(UNIT)"
