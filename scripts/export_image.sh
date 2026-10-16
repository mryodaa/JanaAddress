#!/usr/bin/env sh
# Собрать образ офлайн и сохранить в tar для передачи жюри (если они запускают готовый образ).
#   ./scripts/export_image.sh            -> jana-address.tar
#   docker load -i jana-address.tar && docker run -p 8000:8000 jana-address:latest
set -eu
cd "$(dirname "$0")/.."
TAG="${TAG:-jana-address:latest}"
OUT="${1:-jana-address.tar}"
docker build --network=none -t "$TAG" .
docker save -o "$OUT" "$TAG"
ls -lh "$OUT"
echo "загрузка: docker load -i $OUT && docker run --rm -p 8000:8000 $TAG"
