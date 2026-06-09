#!/usr/bin/env python3
import os
import re
import sys
import zipfile
import subprocess

def run_cmd(cmd, allow_fail=False):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0 and not allow_fail:
        print(f"Error executing: {' '.join(cmd)}")
        sys.exit(result.returncode)
    return result.returncode == 0

def main():
    manifest_path = "blender_manifest.toml"
    
    if not os.path.exists(manifest_path):
        print(f"Error: {manifest_path} not found.")
        sys.exit(1)

    # 1. Read manifest and bump version
    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r'version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', content)
    if not match:
        print("Could not find the version in blender_manifest.toml.")
        sys.exit(1)

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    
    # Increment the patch version (e.g. 1.0.0 -> 1.0.1)
    patch += 1
    new_version = f"{major}.{minor}.{patch}"

    # Update manifest
    new_content = re.sub(
        r'(version\s*=\s*")\d+\.\d+\.\d+(")',
        rf'\g<1>{new_version}\g<2>',
        content
    )

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✅ Bumped version in manifest to {new_version}.")

    # 2. Create ZIP file
    # Important for Blender 4.2 Extensions: The manifest must be at the root of the ZIP!
    zip_name = f"flat_uv_mapper_v{new_version}.zip"
    files_to_zip = ["__init__.py", "blender_manifest.toml", "LICENSE", "README.md"]

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in files_to_zip:
            if os.path.exists(file):
                zipf.write(file, arcname=file)
            else:
                print(f"Warning: {file} was not found and will not be included in the zip.")

    print(f"✅ Created ZIP file {zip_name}.")

    # 3. Git Commit and Tag
    # Check if a Git repo exists
    if os.path.exists(".git"):
        print("Creating Git Commit and Tag...")
        run_cmd(["git", "add", manifest_path])
        run_cmd(["git", "commit", "-m", f"Bump version to {new_version}"])
        run_cmd(["git", "tag", f"v{new_version}"])
        run_cmd(["git", "push"])
        run_cmd(["git", "push", "--tags"])
        print("✅ Git Push and Tag completed.")

        # 4. GitHub Release (requires GitHub CLI 'gh')
        print("Attempting to create GitHub Release...")
        # Check if gh is installed
        has_gh = subprocess.run(["gh", "--version"], capture_output=True).returncode == 0
        if has_gh:
            success = run_cmd([
                "gh", "release", "create", f"v{new_version}", zip_name,
                "--title", f"Release v{new_version}",
                "--generate-notes"
            ], allow_fail=True)
            if success:
                print(f"🎉 GitHub Release v{new_version} successfully created!")
            else:
                print("❌ Error creating the GitHub Release. Are you authenticated with 'gh auth login'?")
        else:
            print("⚠️ GitHub CLI ('gh') is not installed. The release must be uploaded manually.")
            print("You can download the CLI here: https://cli.github.com/")
    else:
        print("No .git directory found. Skipping Git commit and GitHub release.")

if __name__ == "__main__":
    main()
