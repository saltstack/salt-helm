#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=========================================================="
echo "⛵ Salt-Kubernetes Aligned Helm Chart Release Tool"
echo "=========================================================="

# 1. Sanity Check: Ensure we are in a Git repository
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "❌ Error: This script must be run inside a Git repository."
    exit 1
fi

# 2. Synchronize tracking branches to avoid pushing tags on stale commits
echo "📥 Syncing local state with upstream GitHub main branch..."
git checkout main
git pull origin main

# 3. Interactive Prompts for Helm Chart SemVer Versions
echo ""
echo "Please enter the target Helm Chart versions (e.g., 1.0.0 or 0.1.0):"
read -p "🔹 salt-master Chart Version:     " MASTER_CHART_VER
read -p "🔹 salt-minion Chart Version:     " MINION_CHART_VER
read -p "🔹 salt-key-operator Chart Version: " OPERATOR_CHART_VER

# Validate that input fields weren't left blank
if [[ -z "$MASTER_CHART_VER" || -z "$MINION_CHART_VER" || -z "$OPERATOR_CHART_VER" ]]; then
    echo "❌ Error: One or more chart version strings were empty. Aborting."
    exit 1
fi

# 4. Map Helm Tag Entities (Strictly aligned with Chart names)
TAG_MASTER_CHART="chart-salt-master-v${MASTER_CHART_VER}"
TAG_MINION_CHART="chart-salt-minion-v${MINION_CHART_VER}"
TAG_OPERATOR_CHART="chart-salt-key-operator-v${OPERATOR_CHART_VER}"

echo ""
echo "=========================================================="
echo "📋 Summary of Aligned Git Tags to Generate:"
echo "=========================================================="
echo " ⛵ Salt Master Chart (helm/salt-master):     $TAG_MASTER_CHART"
echo " ⛵ Salt Minion Chart (helm/salt-minion):     $TAG_MINION_CHART"
echo " ⛵ Key Operator Chart (helm/salt-key-operator): $TAG_OPERATOR_CHART"
echo "=========================================================="
read -p "⚠️ Do you want to generate and push these tags to GitHub? (y/N): " CONFIRM

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "❌ Operation cancelled by user."
    exit 0
fi

# Function to safely clear, build, and push annotated git tags
create_and_push_helm_tag() {
    local tag_name=$1
    local chart_name=$2

    echo ""
    echo "➡️ Processing tag for $chart_name..."
    
    # Check if the tag already exists locally or remotely to clear out older entries
    if git rev-parse "$tag_name" >/dev/null 2>&1; then
        echo "⚠️ Tag '$tag_name' already exists. Overwriting local and remote instances..."
        git tag -d "$tag_name"
        git push origin --delete "$tag_name" || true
    fi

    # Create the fresh annotated tag pointing to the HEAD of main
    git tag -a "$tag_name" -m "Release $tag_name aligned perfectly with Helm chart properties"
    
    # Push the tag to upstream to trigger target workflow pipelines
    git push origin "$tag_name"
    echo "✨ Successfully pushed $tag_name!"
}

# 5. Execute Tag Tracking Pushes
create_and_push_helm_tag "$TAG_MASTER_CHART" "Salt Master Chart"
sleep 10
create_and_push_helm_tag "$TAG_MINION_CHART" "Salt Minion Chart"
sleep 10
create_and_push_helm_tag "$TAG_OPERATOR_CHART" "Salt Key Operator Chart"

echo ""
echo "=========================================================="
echo "🎉 All Done! Monitor chart actions at: https://github.com"
echo "=========================================================="

