#!/bin/bash
set -e

# Delete dist if it already exists
rm -rf dist
mkdir dist

# Install dependencies (none today: openai and httpx ship with COVAS:NEXT)
if [ -f "requirements.txt" ]; then
    pip install --target ./deps -r requirements.txt
fi

artifacts=("cn-plugin-cline.py" "manifest.json" "__init__.py" "README.md")
if [ -d "deps" ]; then
    artifacts+=("deps")
fi

# Zip with a top-level cn-plugin-cline folder so it unpacks straight into plugins/
mkdir -p dist/cn-plugin-cline
cp -r "${artifacts[@]}" dist/cn-plugin-cline/
(cd dist && zip -r -9 cn-plugin-cline.zip cn-plugin-cline)
rm -rf dist/cn-plugin-cline
