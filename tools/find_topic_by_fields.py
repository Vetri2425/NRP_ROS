#!/usr/bin/env python3
"""
find_topic_by_fields.py

Scan ROS2 topics and read a single sample from each topic, searching for
fields/patterns such as "hrms", "vrms", "imu_status", or "imu_aligned".

Usage:
  python3 tools/find_topic_by_fields.py                # run with defaults
  python3 tools/find_topic_by_fields.py -p hrms,vrms    # search only hrms and vrms
  python3 tools/find_topic_by_fields.py -t 2 -v        # increase echo timeout to 2s and verbose

Notes:
  - This script uses the `ros2` CLI. Ensure your ROS2 environment is sourced
    (for example: `source /opt/ros/<distro>/setup.bash`) before running.
  - The script calls `ros2 topic echo <topic> --once` for each topic. Some topics
    may not allow a quick `--once` sample; you can increase --timeout via -t.
  - Run with -v/--verbose to see progress and non-matching samples.

Output:
  - Prints matching topic names and the matched snippet(s).

Exit codes:
  0 - completed (may or may not have found matches)
  2 - ros2 CLI missing or other fatal error

"""
import argparse
import re
import shutil
import subprocess
import sys
from typing import List, Pattern, Optional


def require_ros2_cli() -> None:
    if not shutil.which("ros2"):
        print("ERROR: `ros2` CLI not found in PATH. Source your ROS2 environment.", file=sys.stderr)
        sys.exit(2)


def get_topics() -> List[str]:
    try:
        out = subprocess.check_output(["ros2", "topic", "list"], stderr=subprocess.DEVNULL)
        topics = [t.strip() for t in out.decode().splitlines() if t.strip()]
        return topics
    except subprocess.CalledProcessError:
        return []


def build_patterns(patterns: List[str]) -> Pattern:
    # Build a single case-insensitive regex to search output lines
    escaped = [re.escape(p) for p in patterns]
    regex = r"(" + r"|".join(escaped) + r")"
    return re.compile(regex, re.IGNORECASE)


def sample_topic(topic: str, timeout: float) -> str:
    # Use ros2 topic echo --once; some topics may print nothing or error
    try:
        out = subprocess.check_output(["ros2", "topic", "echo", topic, "--once"], stderr=subprocess.DEVNULL, timeout=timeout)
        return out.decode(errors="ignore")
    except subprocess.TimeoutExpired:
        return ""  # treat as no sample
    except subprocess.CalledProcessError:
        return ""


def get_topic_type(topic: str) -> Optional[str]:
    """Return the message type for a topic (e.g. std_msgs/msg/String) or None."""
    try:
        out = subprocess.check_output(["ros2", "topic", "info", topic], stderr=subprocess.DEVNULL)
        text = out.decode(errors="ignore")
        for line in text.splitlines():
            if line.strip().startswith("Type:"):
                # line like: "Type: std_msgs/msg/String"
                _, _, t = line.partition(":")
                return t.strip()
        return None
    except subprocess.CalledProcessError:
        return None


def get_interface_definition(msg_type: str) -> Optional[str]:
    """Call `ros2 interface show <msg_type>` and return the textual definition, or None on error."""
    try:
        out = subprocess.check_output(["ros2", "interface", "show", msg_type], stderr=subprocess.DEVNULL)
        return out.decode(errors="ignore")
    except subprocess.CalledProcessError:
        return None


def scan_topics(patterns: List[str], timeout: float, verbose: bool, inspect_types: bool) -> List[str]:
    require_ros2_cli()
    topics = get_topics()
    if verbose:
        print(f"Found {len(topics)} topics")

    pat = build_patterns(patterns)
    matches = []

    for t in topics:
        if verbose:
            print(f"Checking: {t}")
        sample = sample_topic(t, timeout)
        if not sample:
            if verbose:
                print("  (no sample or timeout)")
            # If requested, fall through to type inspection when no sample
            if not inspect_types:
                continue
            sample = ""

        # Search the sample for any of the pattern tokens
        m = pat.search(sample)
        if m:
            # show a small context (the matching line(s))
            matched_lines = []
            for line in sample.splitlines():
                if pat.search(line):
                    matched_lines.append(line.strip())
            print("--- MATCH ---")
            print(f"Topic: {t}")
            for ln in matched_lines:
                print(f"  {ln}")
            print("--------------\n")
            matches.append(t)
        else:
            # No match in sample; optionally inspect message type definition
            if inspect_types:
                ttype = get_topic_type(t)
                if not ttype:
                    if verbose:
                        print("  (could not determine topic type)")
                    continue
                if verbose:
                    print(f"  Type: {ttype}")
                iface = get_interface_definition(ttype)
                if not iface:
                    if verbose:
                        print("  (could not fetch interface definition)")
                    continue
                if pat.search(iface):
                    print("--- MATCH (by type) ---")
                    print(f"Topic: {t}")
                    print(f"  Type: {ttype}")
                    # print matching lines from interface
                    for line in iface.splitlines():
                        if pat.search(line):
                            print(f"    {line.strip()}")
                    print("------------------------\n")
                    matches.append(t)
                else:
                    if verbose:
                        # show a tiny snippet of the interface to help diagnosis
                        shown = [l for l in iface.splitlines() if l.strip()][:2]
                        for ln in shown:
                            print(f"  iface: {ln}")
            else:
                if verbose:
                    # show first 2 non-empty lines to help diagnosis
                    shown = [l for l in sample.splitlines() if l.strip()][:2]
                    for ln in shown:
                        print(f"  sample: {ln}")

    return matches


def parse_args():
    parser = argparse.ArgumentParser(description="Find ROS2 topics that publish specific fields or tokens.")
    parser.add_argument("-p", "--patterns", default="hrms,vrms,imu_status,imu_aligned",
                        help="Comma-separated list of token patterns to search for (default: hrms,vrms,imu_status,imu_aligned)")
    parser.add_argument("-t", "--timeout", type=float, default=1.0,
                        help="Timeout in seconds for each `ros2 topic echo --once` call (default: 1.0)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose progress output")
    parser.add_argument("-i", "--inspect-types", action="store_true",
                        help="Inspect message type/interface definitions for the patterns (uses `ros2 interface show`) if sample search finds nothing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
    if not patterns:
        print("No patterns provided", file=sys.stderr)
        return 1

    matches = scan_topics(patterns, args.timeout, args.verbose, args.inspect_types)

    if matches:
        print("SUMMARY: Matching topics:")
        for m in matches:
            print(f"  {m}")
    else:
        print("SUMMARY: No matching topics found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
