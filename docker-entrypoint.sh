#!/bin/sh
set -eu

# Docker 容器内统一使用挂载目录，不接受外部 DATA_DIR 覆盖。
export DATA_DIR=/data

exec python -m cqu_electricity "$@"

