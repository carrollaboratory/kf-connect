#!/usr/bin/env python
"""
AWS SSM port-forwarding tunnel with SAML login.

Usage:
    kfdb --environment dev --port 5432 --local-port 15432 --hostname my-db.internal.example.com
    kfdb --environment prod --port 3306 --local-port 13306 --hostname my-db.internal.example.com --region us-west-2
    kfdb --host d3b
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from rich import print
from yaml import safe_load


def parse_args() -> argparse.Namespace:
    # Use ~/.kfhosts if found
    hostcfg = {}
    hostsfile = Path.home() / ".kfhosts"
    available_hosts = []
    if not hostsfile.exists():
        print(f"[red]Unable to find file, ~/.kfhosts. This should be used[/red]")
        # sys.exit(1)
        epilog = "You really should create a ~/.kfhosts file. It will make life easier."
    else:
        epilog = "~/.kfhosts found, allowing you to use --host instead of providing the full path"
        with hostsfile.open("rt") as file:
            hostcfg = safe_load(file)
            available_hosts = hostcfg["warehouse"].keys()

    parser = argparse.ArgumentParser(
        description="Open an AWS SSM port-forwarding session to a remote host via a bastion.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=epilog,
    )
    if len(available_hosts) > 0:
        parser.add_argument(
            "--host",
            choices=available_hosts,
            help="Choose from a list of your configured hosts (from ~/.kfhosts). This will provide the port if chosen",
        )
    parser.add_argument(
        "--environment",
        "-e",
        # required=True,
        default="prd",
        help="Service level / environment (e.g. dev, staging, prod).",
    )
    parser.add_argument(
        "--port",
        "-p",
        default=None,
        # required=True,
        type=int,
        help="Remote port on the target host.",
    )
    parser.add_argument(
        "--local-port",
        "-l",
        default=None,
        type=int,
        dest="local_port",
        help="Local port to bind the tunnel to (only required if local port should differ from the remote host's port).",
    )
    parser.add_argument(
        "--hostname",
        "-H",
        default=None,
        # required=True,
        help="DNS name or IP of the remote host to tunnel to.",
    )
    parser.add_argument(
        "--region",
        "-r",
        default="us-east-1",
        help="AWS region. Defaults to the region in your AWS CLI config.",
    )
    parser.add_argument(
        "--profile",
        default="saml",
        help="AWS CLI profile to use for SAML login and all subsequent calls.",
    )
    args = parser.parse_args()

    if args.host:
        if not args.port:
            args.port = hostcfg.get("warehouse").get(args.host).get("port")
        if not args.hostname:
            args.hostname = hostcfg.get("warehouse").get(args.host).get("host")
    return args


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, streaming stdout/stderr live, and raise on non-zero exit."""
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


def saml_login(profile: str) -> None:
    """Perform AWS SSO / SAML login for the given profile."""
    print(f"[*] Logging in with AWS profile '{profile}' ...", file=sys.stderr)
    run(["saml2aws", "login", "--profile", profile])


def get_region(profile: str, region_override: str | None) -> str:
    if region_override:
        return region_override
    print("[*] No region provided — reading from AWS CLI config ...", file=sys.stderr)
    result = subprocess.run(
        ["aws", "configure", "get", "region", "--profile", profile],
        capture_output=True,
        text=True,
    )
    region = result.stdout.strip()
    if not region:
        print(
            "ERROR: Could not determine AWS region. Pass --region explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[*] Using region: {region}", file=sys.stderr)
    return region


def get_instance_id(profile: str, region: str, environment: str) -> str:
    tag_value = f"aws-infra-bastion-ssm-ec2-{environment}-0"
    print(
        f"[*] Looking up bastion instance with tag Name={tag_value} ...",
        file=sys.stderr,
    )
    result = subprocess.run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--region",
            region,
            "--profile",
            profile,
            "--filters",
            f"Name=tag:Name,Values={tag_value}",
            "--query",
            "Reservations[].Instances[].InstanceId",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    instance_id = result.stdout.strip()
    if not instance_id:
        print(
            f"ERROR: No EC2 instance found with tag Name={tag_value} in region {region}.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[*] Found instance: {instance_id}", file=sys.stderr)
    return instance_id


def start_tunnel(
    profile: str,
    region: str,
    instance_id: str,
    port: int,
    local_port: int,
    hostname: str,
) -> None:
    parameters = json.dumps(
        {
            "portNumber": [str(port)],
            "localPortNumber": [str(local_port)],
            "host": [hostname],
        }
    )
    print(
        f"[*] Starting SSM tunnel: {hostname}:{port} -> localhost:{local_port}",
        file=sys.stderr,
    )
    # Use run() so stdout/stderr stream directly to the terminal.
    run(
        [
            "aws",
            "ssm",
            "start-session",
            "--region",
            region,
            "--profile",
            profile,
            "--target",
            instance_id,
            "--document-name",
            "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters",
            parameters,
        ],
    )


def main() -> None:
    args = parse_args()

    print(args)
    if args.local_port is None:
        args.local_port = args.port

    saml_login(args.profile)
    region = get_region(args.profile, args.region)
    instance_id = get_instance_id(args.profile, region, args.environment)
    start_tunnel(
        profile=args.profile,
        region=region,
        instance_id=instance_id,
        port=args.port,
        local_port=args.local_port,
        hostname=args.hostname,
    )


if __name__ == "__main__":
    main()
