#!/bin/bash
# Start Ray cluster for distributed diarization processing
#
# Usage:
#   On head node:    ./scripts/start_ray_cluster.sh head
#   On worker nodes: ./scripts/start_ray_cluster.sh worker <head-node-ip>

set -e

MODE=${1:-}
HEAD_IP=${2:-}

if [ -z "$MODE" ]; then
    echo "Usage:"
    echo "  On head node:    $0 head"
    echo "  On worker nodes: $0 worker <head-node-ip>"
    exit 1
fi

# Check if ray is installed
if ! command -v ray &> /dev/null; then
    echo "Error: Ray is not installed"
    echo "Install with: pip install 'ray[default]>=2.7.0'"
    exit 1
fi

case "$MODE" in
    head)
        echo "Starting Ray head node..."
        ray start --head --port=6379 --dashboard-host=0.0.0.0 --dashboard-port=8265
        echo ""
        echo "✅ Ray head node started!"
        echo ""
        echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8265"
        echo ""
        echo "On worker nodes, run:"
        echo "  $0 worker $(hostname -I | awk '{print $1}')"
        echo ""
        echo "In your .env file, set:"
        echo "  USE_RAY=true"
        echo "  RAY_ADDRESS=ray://$(hostname -I | awk '{print $1}'):10001"
        ;;
    worker)
        if [ -z "$HEAD_IP" ]; then
            echo "Error: Head node IP required"
            echo "Usage: $0 worker <head-node-ip>"
            exit 1
        fi
        echo "Starting Ray worker node connecting to $HEAD_IP..."
        ray start --address="$HEAD_IP:6379"
        echo ""
        echo "✅ Ray worker node connected to $HEAD_IP"
        ;;
    *)
        echo "Error: Invalid mode '$MODE'"
        echo "Must be 'head' or 'worker'"
        exit 1
        ;;
esac

echo ""
echo "To stop Ray on this machine: ray stop"
echo "To check Ray status: ray status"
