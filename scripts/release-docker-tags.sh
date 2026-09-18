#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=========================================================="
echo "🚀 Salt-Kubernetes Automated Release Tag Generator"
echo "=========================================================="

# 1. Sanity Check: Ensure we are in a Git repository
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "❌ Error: This script must be run inside a Git repository."
    exit 1
fi

# 2. Synchronize tracking branches to ensure we have the absolute latest pipeline commits
echo "📥 Syncing branch states with origin..."
git checkout main
git pull origin main

# 3. Interactive Prompts for Component SemVer Versions
echo ""
echo "Please enter the target version numbers (e.g., 0.1.0 or 1.0.0):"
read -p "🔹 Salt Master Version: " MASTER_VER
read -p "🔹 Salt Minion K8s Version: " MINION_K8S_VER
read -p "🔹 Salt Minion VCF Version: " MINION_VCF_VER
read -p "🔹 Salt Key Operator Version: " OPERATOR_VER

# Validate that input fields weren't left blank
if [[ -z "$MASTER_VER" || -z "$MINION_K8S_VER" || -z "$MINION_VCF_VER" || -z "$OPERATOR_VER" ]]; then
    echo "❌ Error: One or more version strings were empty. Aborting process."
    exit 1
fi

# 4. Map Tag Entities
TAG_MASTER="salt-master-v${MASTER_VER}"
TAG_MINION_K8S="salt-minion-kubernetes-v${MINION_K8S_VER}"
TAG_MINION_VCF="salt-minion-vcf-v${MINION_VCF_VER}"
TAG_OPERATOR="salt-key-operator-v${OPERATOR_VER}"

echo ""
echo "=========================================================="
echo "📋 Summary of New Git Tags to Generate:"
echo "=========================================================="
echo " 📦 Salt Master:        $TAG_MASTER"
echo " 📦 Minion Kubernetes:  $TAG_MINION_K8S"
echo " 📦 Minion VCF:         $TAG_MINION_VCF"
echo " 📦 Key Operator:       $TAG_OPERATOR"
echo "=========================================================="
read -p "⚠️ Do you want to generate and push these tags to GitHub? (y/N): " CONFIRM

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "❌ Operation cancelled by user."
    exit 0
fi

# Function to safely create and push an annotated tag
create_and_push_tag() {
    local tag_name=$1
    local component_name=$2

    echo ""
    echo "➡️ Processing tag for $component_name..."
    
    # Check if the tag already exists locally or remotely to clear out older broken builds
    if git rev-parse "$tag_name" >/dev/null 2>&1; then
        echo "⚠️ Tag '$tag_name' already exists. Cleaning it up..."
        git tag -d "$tag_name"
        git push origin --delete "$tag_name" || true
    fi

    # Create the fresh annotated tag pointing to the HEAD of main
    git tag -a "$tag_name" -m "Release $tag_name built automatically via shell-engine"
    
    # Push the tag to upstream to fire the specific Component Release Workflow
    git push origin "$tag_name"
    echo "✨ Successfully pushed $tag_name!"
}

# 5. Execute Tag Builds
create_and_push_tag "$TAG_MASTER" "Salt Master"
sleep 10
create_and_push_tag "$TAG_MINION_K8S" "Salt Minion Kubernetes"
sleep 10
create_and_push_tag "$TAG_MINION_VCF" "Salt Minion VCF"
sleep 10
create_and_push_tag "$TAG_OPERATOR" "Salt Key Operator"

echo ""
echo "=========================================================="
echo "🎉 All Done! Monitor actions at: https://github.com"
echo "=========================================================="

