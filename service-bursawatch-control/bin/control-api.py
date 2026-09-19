#!/usr/bin/env python3
"""Development entry point for the Bursawatch control-plane API."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "control_plane.api:create_app_from_environment",
        factory=True,
        host="127.0.0.1",
        port=9180,
    )
