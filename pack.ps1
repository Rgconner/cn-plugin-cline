# Delete dist if it already exists
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

# Create dist
New-Item "dist" -ItemType Directory | Out-Null

# Install dependencies (none today: openai and httpx ship with COVAS:NEXT)
if (Test-Path "requirements.txt") {
    pip install --target ./deps -r requirements.txt
}

$artifacts = "cn-plugin-cline.py", "manifest.json", "__init__.py", "README.md", "LICENSE"

if (Test-Path "deps") {
    $artifacts += "deps"
}

# Zip with a top-level cn-plugin-cline folder so it unpacks straight into plugins\
$staging = Join-Path "dist" "cn-plugin-cline"
New-Item $staging -ItemType Directory | Out-Null
Copy-Item -Path $artifacts -Destination $staging -Recurse

Compress-Archive -Path $staging -DestinationPath "dist\cn-plugin-cline.zip" -CompressionLevel Fastest
Remove-Item -Recurse -Force $staging
