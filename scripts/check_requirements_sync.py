#!/usr/bin/env python3
"""
Check that Pipfile and airflow/requirements.txt contain compatible package versions.

This script:
1. Verifies that packages common to both files have compatible versions
2. Auto-syncs packages marked with '# sync-to-requirements' from Pipfile to requirements.txt
3. Prevents deployment issues from version mismatches

Usage:
    python scripts/check_requirements_sync.py           # Verify and auto-sync
    python scripts/check_requirements_sync.py --check   # Verify only (no modifications)
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Set, Tuple


def parse_pipfile_packages(pipfile_path: Path) -> Tuple[Dict[str, str], Set[str]]:
    """
    Parse packages from Pipfile [packages] section.

    Returns:
        Tuple of (packages_dict, sync_packages_set)
        - packages_dict: {package_name: version_spec}
        - sync_packages_set: Set of package names marked with '# sync-to-requirements'
    """
    packages = {}
    sync_packages = set()

    with open(pipfile_path, "r") as f:
        lines = f.readlines()

    in_packages_section = False

    for line in lines:
        stripped = line.strip()

        # Track when we enter/exit [packages] section
        if stripped == "[packages]":
            in_packages_section = True
            continue
        elif stripped.startswith("[") and stripped.endswith("]"):
            in_packages_section = False
            continue

        if not in_packages_section:
            continue

        # Skip empty lines and pure comments
        if not stripped or stripped.startswith("#"):
            continue

        # Check if this package should be synced to requirements.txt
        should_sync = "# sync-to-requirements" in line

        # Handle different Pipfile formats:
        # package = "*"
        # package = "==1.2.3"
        # package = "<2.0,>=1.9"
        # package = {version = "==1.2.3", extras = ["postgres"]}
        if "=" in stripped and not stripped.startswith("["):  # Avoid section headers
            # Split on first '=' to get package name
            parts = stripped.split("=", 1)
            package_name = parts[0].strip()

            # Strip quotes from package name if present (e.g., "pyannote.audio")
            if package_name.startswith('"') and package_name.endswith('"'):
                package_name = package_name[1:-1]
            elif package_name.startswith("'") and package_name.endswith("'"):
                package_name = package_name[1:-1]

            # Extract version from various formats
            version_part = parts[1].strip()

            # Remove inline comments for version parsing
            if "#" in version_part:
                version_part = version_part.split("#")[0].strip()

            if version_part.startswith("{"):
                # Dictionary format: {version = "==1.2.3", extras = ["postgres"]}
                version_match = re.search(r'version\s*=\s*"([^"]*)"', version_part)
                version = version_match.group(1) if version_match else "*"
            elif version_part.startswith('"') and version_part.endswith('"'):
                # Quoted string version: "==1.2.3" or "*" or "<2.0,>=1.9"
                version = version_part[1:-1]
            else:
                # Unquoted version (shouldn't happen in valid TOML, but let's handle it)
                version = version_part

            packages[package_name] = version

            if should_sync:
                sync_packages.add(package_name)

    return packages, sync_packages


def parse_requirements_txt(requirements_path: Path) -> Dict[str, str]:
    """Parse packages from requirements.txt."""
    packages = {}

    with open(requirements_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Handle package==version or package>=version etc.
            # Split on comparison operators to extract package name
            for op in ["==", ">=", "<=", "<", ">"]:
                if op in line:
                    package, version = line.split(op, 1)
                    packages[package.strip()] = f"{op}{version.strip()}"
                    break
            else:
                # No version specified
                packages[line] = "*"

    return packages


def normalize_package_name(name: str) -> str:
    """Normalize package names for comparison (handle dashes vs underscores)."""
    return name.lower().replace("_", "-")


def convert_pipfile_version_to_requirements(version_spec: str) -> str:
    """
    Convert Pipfile version specification to requirements.txt format.

    Examples:
        ">=1.5.0,<3.0" -> ">=1.5.0,<3.0"
        "==2.9.1" -> "==2.9.1"
        "*" -> ""  (no version constraint)
    """
    if version_spec == "*":
        return ""
    return version_spec


def check_compatibility(pipfile_version: str, requirements_version: str) -> bool:
    """Check if two version specs are compatible."""
    # If either is "*", they're compatible
    if pipfile_version == "*" or requirements_version == "*":
        return True

    # If both have exact versions, they must match
    if pipfile_version.startswith("==") and requirements_version.startswith("=="):
        return pipfile_version == requirements_version

    # For now, assume other combinations are compatible
    # (Could be enhanced with proper version parsing)
    return True


def sync_packages_to_requirements(
    requirements_path: Path,
    pipfile_packages: Dict[str, str],
    sync_packages: Set[str],
    existing_requirements: Dict[str, str],
) -> Tuple[int, list]:
    """
    Sync packages from Pipfile to requirements.txt.

    Returns:
        Tuple of (num_added, added_packages_list)
    """
    added_packages = []
    requirements_normalized = {
        normalize_package_name(k): k for k in existing_requirements.keys()
    }

    # Find packages that need to be added
    for package_name in sync_packages:
        normalized_name = normalize_package_name(package_name)

        # Skip if already in requirements.txt
        if normalized_name in requirements_normalized:
            continue

        version_spec = pipfile_packages.get(package_name, "*")
        requirements_version = convert_pipfile_version_to_requirements(version_spec)

        added_packages.append((package_name, requirements_version or "(latest)"))

    if not added_packages:
        return 0, []

    # Append new packages to requirements.txt
    with open(requirements_path, "a") as f:
        for package_name, version_display in added_packages:
            version_spec = pipfile_packages.get(package_name, "*")
            requirements_version = convert_pipfile_version_to_requirements(version_spec)
            if requirements_version:
                f.write(f"{package_name}{requirements_version}\n")
            else:
                f.write(f"{package_name}\n")

    return len(added_packages), added_packages


def main():
    """Main function to check requirements synchronization."""
    parser = argparse.ArgumentParser(
        description="Verify and sync Pipfile packages to requirements.txt"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check compatibility without modifying files",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Force sync mode (automatically add missing packages)",
    )
    args = parser.parse_args()

    # Default behavior: sync unless --check is specified
    sync_mode = not args.check or args.sync

    repo_root = Path(__file__).parent.parent
    pipfile_path = repo_root / "Pipfile"
    requirements_path = repo_root / "airflow" / "requirements.txt"

    if not pipfile_path.exists():
        print(f"Error: {pipfile_path} not found")
        return 1

    if not requirements_path.exists():
        print(f"Error: {requirements_path} not found")
        return 1

    # Parse both files
    pipfile_packages, sync_packages = parse_pipfile_packages(pipfile_path)
    requirements_packages = parse_requirements_txt(requirements_path)

    # Normalize package names for comparison
    pipfile_normalized = {
        normalize_package_name(k): v for k, v in pipfile_packages.items()
    }
    requirements_normalized = {
        normalize_package_name(k): v for k, v in requirements_packages.items()
    }

    # Find common packages
    common_packages = set(pipfile_normalized.keys()) & set(
        requirements_normalized.keys()
    )

    # Check for conflicts
    conflicts = []
    for package in common_packages:
        pipfile_version = pipfile_normalized[package]
        requirements_version = requirements_normalized[package]

        if not check_compatibility(pipfile_version, requirements_version):
            conflicts.append(
                {
                    "package": package,
                    "pipfile": pipfile_version,
                    "requirements": requirements_version,
                }
            )

    # Report conflicts
    if conflicts:
        print("Requirements synchronization check FAILED")
        print("\nVersion conflicts found:")
        for conflict in conflicts:
            print(f"  {conflict['package']}:")
            print(f"    Pipfile: {conflict['pipfile']}")
            print(f"    requirements.txt: {conflict['requirements']}")

        print(
            f"\nPlease ensure {pipfile_path} and {requirements_path} have compatible versions."
        )
        return 1

    # Check for orphaned packages in requirements.txt
    # (packages that exist in requirements.txt but not in Pipfile with sync marker)
    orphaned_packages = []
    pipfile_sync_normalized = {normalize_package_name(pkg) for pkg in sync_packages}

    for req_package in requirements_normalized.keys():
        # Skip if this package is in Pipfile (regardless of sync marker)
        if req_package in pipfile_normalized:
            # Check if it SHOULD have sync marker
            if req_package not in pipfile_sync_normalized:
                # Package exists in both but missing sync marker in Pipfile
                orphaned_packages.append(
                    {
                        "package": req_package,
                        "in_pipfile": True,
                        "has_sync_marker": False,
                    }
                )
        else:
            # Package in requirements.txt but not in Pipfile at all
            orphaned_packages.append(
                {"package": req_package, "in_pipfile": False, "has_sync_marker": False}
            )

    if orphaned_packages:
        print("Requirements synchronization check FAILED")
        print(
            f"\nFound {len(orphaned_packages)} package(s) in requirements.txt that should be in Pipfile:"
        )

        for orphan in orphaned_packages:
            if orphan["in_pipfile"]:
                print(
                    f"  - {orphan['package']}: EXISTS in Pipfile but MISSING '# sync-to-requirements' comment"
                )
            else:
                print(
                    f"  - {orphan['package']}: NOT FOUND in Pipfile [packages] section"
                )

        print("\nTo fix:")
        print("  1. Add missing packages to Pipfile [packages] section")
        print("  2. Add '# sync-to-requirements' comment to packages that should sync")
        print(
            f"  3. Or remove them from {requirements_path} if not needed in containers"
        )
        return 1

    # Sync packages if enabled
    if sync_mode and sync_packages:
        num_added, added_packages = sync_packages_to_requirements(
            requirements_path, pipfile_packages, sync_packages, requirements_packages
        )

        if num_added > 0:
            print(f"\n📦 Auto-synced {num_added} package(s) to requirements.txt:")
            for package_name, version in added_packages:
                print(f"  + {package_name} {version}")
            print(
                f"\nUpdated {requirements_path} with packages marked '# sync-to-requirements'"
            )
    elif sync_packages and not sync_mode:
        # Check mode: report what would be synced
        packages_to_sync = []
        for package_name in sync_packages:
            normalized_name = normalize_package_name(package_name)
            if normalized_name not in requirements_normalized:
                version_spec = pipfile_packages.get(package_name, "*")
                packages_to_sync.append(
                    (
                        package_name,
                        convert_pipfile_version_to_requirements(version_spec)
                        or "(latest)",
                    )
                )

        if packages_to_sync:
            print(
                f"\n{len(packages_to_sync)} package(s) marked for sync but missing from requirements.txt:"
            )
            for package_name, version in packages_to_sync:
                print(f"  - {package_name} {version}")
            print(
                f"\nRun without --check flag to automatically add these packages to {requirements_path}"
            )

    # Final status
    print("\nRequirements synchronization check PASSED")
    if common_packages:
        print(f"Found {len(common_packages)} common packages with compatible versions")
    if sync_packages:
        print(
            f"Found {len(sync_packages)} package(s) marked with '# sync-to-requirements'"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
