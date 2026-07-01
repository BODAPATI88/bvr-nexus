"""Replace GENERATE placeholders in .env with cryptographically strong secrets."""

import secrets
import os

env_file = ".env"
if not os.path.exists(env_file):
    open(env_file, "w").close()

with open(env_file, "r") as f:
    lines = f.readlines()

secrets_map = {}
for line in lines:
    if "=" in line and not line.startswith("#"):
        key, val = line.strip().split("=", 1)
        if val.strip() == "GENERATE":
            secrets_map[key] = secrets.token_urlsafe(32)

with open(env_file, "w") as f:
    for line in lines:
        if "=" in line and not line.startswith("#"):
            key, val = line.strip().split("=", 1)
            if key in secrets_map:
                f.write(f"{key}={secrets_map[key]}\n")
            else:
                f.write(line)
        else:
            f.write(line)

for key in secrets_map:
    print(f"  Generated {key}")

print("Secrets written to .env")
