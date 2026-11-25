"""Build and deploy the stack with secrets taken from .env.

    python scripts/deploy.py

An alternative to `sam deploy --guided`: secrets are passed as parameter
overrides straight from .env, so they are never written to samconfig.toml.
"""

import os
import subprocess
import sys

import _env

STACK = "planabot"
REGION = "eu-central-1"

_env.require("BOT_TOKEN", "WEBHOOK_SECRET", "OWNER_CHAT_ID")


def run(cmd):
    # shell=True is needed on Windows to find sam.cmd; arguments contain no user input.
    result = subprocess.run(cmd, cwd=_env.ROOT, shell=(os.name == "nt"))
    if result.returncode:
        sys.exit(result.returncode)


def main():
    run(["sam", "build"])
    overrides = [
        f"BotToken={os.environ['BOT_TOKEN']}",
        f"WebhookSecret={os.environ['WEBHOOK_SECRET']}",
        f"OwnerChatId={os.environ['OWNER_CHAT_ID']}",
    ]
    run([
        "sam", "deploy",
        "--stack-name", STACK,
        "--region", REGION,
        "--resolve-s3",
        "--capabilities", "CAPABILITY_IAM",
        "--no-confirm-changeset",
        "--no-fail-on-empty-changeset",
        "--parameter-overrides", *overrides,
    ])


if __name__ == "__main__":
    main()
