#!/bin/sh
set -eu
IMAGE="${IMAGE:-salt-minion-vcf}"
TAG="${TAG:-0.1.0}"
docker build -t "${IMAGE}:${TAG}" .
