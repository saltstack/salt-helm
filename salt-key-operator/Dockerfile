# syntax=docker/dockerfile:1
#
# CRD controller for SaltMinionKey - see README.md. Multi-stage build:
# compiled with the full Go toolchain, then copied into a distroless
# static base with nothing else in it (no shell, no package manager, not
# even libc) - this binary makes outbound Kubernetes API calls only, so
# there's no reason for the runtime image to contain anything more than
# the binary and CA certificates.
FROM golang:1.27-bookworm AS build

WORKDIR /workspace

COPY go.mod go.sum ./
RUN go mod download

COPY api/ api/
COPY cmd/ cmd/
COPY internal/ internal/

# CGO_ENABLED=0 for a fully static binary (required for distroless/static,
# which has no libc). GOOS/GOARCH left to the builder's default single-arch
# build - see docs/building.md for the multi-arch buildx pattern used
# elsewhere in this repo if that's ever needed here too.
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /salt-key-operator ./cmd

FROM gcr.io/distroless/static-debian12:nonroot

# distroless/static-debian12:nonroot already runs as uid/gid 65532 ("nonroot")
# - no USER directive needed, unlike this repo's other (apt/onedir-based)
# images, which have to create their own non-root user themselves.
COPY --from=build /salt-key-operator /salt-key-operator

ENTRYPOINT ["/salt-key-operator"]
