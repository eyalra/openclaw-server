#!/bin/bash
# verify-shared-collections.sh
# Verify shared collections are synced and accessible in containers

set -e

echo "=========================================="
echo "Verify Shared Collections"
echo "=========================================="
echo ""

# Check host-side sync
echo "Step 1: Checking host-side sync..."
SHARED_ROOT="/home/openclaw/data/shared"
if [ -d "$SHARED_ROOT" ]; then
    echo "  ✓ Shared collections root exists: $SHARED_ROOT"
    echo ""
    echo "  Collections found:"
    find "$SHARED_ROOT" -mindepth 1 -maxdepth 1 -type d | while read -r collection_dir; do
        collection_name=$(basename "$collection_dir")
        file_count=$(find "$collection_dir" -type f | wc -l)
        echo "    - $collection_name ($file_count files)"
    done
else
    echo "  ✗ Shared collections root not found: $SHARED_ROOT"
    echo "  Run: clawctl shared-collections sync"
fi

echo ""
echo "Step 2: Checking inside containers..."
CONTAINERS=$(docker ps -a --filter "name=openclaw-" --format "{{.Names}}" || echo "")
if [ -z "$CONTAINERS" ]; then
    echo "  ⚠ No OpenClaw containers found"
else
    echo "$CONTAINERS" | while read -r container; do
        STATUS=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")
        echo ""
        echo "  Container: $container (status: $STATUS)"
        
        if [ "$STATUS" = "running" ]; then
            echo "    Checking /mnt/shared mount..."
            if docker exec "$container" test -d /mnt/shared 2>/dev/null; then
                echo "    ✓ /mnt/shared exists"
                echo "    Collections available:"
                docker exec "$container" ls -1 /mnt/shared 2>/dev/null | while read -r collection; do
                    file_count=$(docker exec "$container" find "/mnt/shared/$collection" -type f 2>/dev/null | wc -l)
                    echo "      - $collection ($file_count files)"
                done
            else
                echo "    ✗ /mnt/shared not found - container may need to be recreated"
                echo "    Run: clawctl user remove <username> && clawctl user add <username>"
            fi
        else
            echo "    ⚠ Container is not running (status: $STATUS)"
            echo "    Start it with: docker start $container"
        fi
    done
fi

echo ""
echo "Step 3: Quick test - list files in a collection..."
if [ -d "$SHARED_ROOT/reports" ]; then
    echo "  Files in 'reports' collection:"
    ls -lh "$SHARED_ROOT/reports" | tail -n +2 | awk '{print "    " $9 " (" $5 ")"}'
fi

echo ""
echo "=========================================="
echo "To access files inside a container:"
echo "  docker exec -it openclaw-<username> ls -la /mnt/shared/reports/"
echo "=========================================="
