---
name: embedded-pipeline
description: A fixture skill whose body embeds a long deterministic bash pipeline inline instead of calling a script. Use this whenever skill-doctor's regression tests need a case that must trigger the embedded-code warning about moving deterministic steps out of prose and into scripts.
---

# Embedded Pipeline

This body carries a large inline program on purpose, so the embedded-code check
should fire and recommend extracting it to `scripts/`.

```bash
set -euo pipefail
TAG="build-$(date +%Y%m%d-%H%M%S)"
REGISTRY="example.registry.local"
IMAGE="$REGISTRY/service:$TAG"
echo "building $IMAGE"
docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
echo "logging in to the registry"
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$REGISTRY"
echo "deploying"
ssh host "kubectl set image deployment/service service=$IMAGE"
ssh host "kubectl rollout status deployment/service --timeout=120s"
echo "verifying health"
curl -s https://service.example.local/health
for i in 1 2 3; do
  echo "poll attempt $i"
  sleep 1
done
echo "checking running image"
ssh host "kubectl get pods -l app=service -o jsonpath='{.items[0].status.containerStatuses[0].image}'"
echo "done"
```
