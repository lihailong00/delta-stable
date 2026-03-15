from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.market.router import EventRouter


class EventRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_supports_channel_and_wildcard_subscribers(self) -> None:
        router = EventRouter()
        received: list[tuple[str, str]] = []

        router.subscribe("funding.update", lambda payload: received.append(("funding", payload["exchange"])))
        router.subscribe("*", lambda payload: received.append(("all", payload["channel"])))

        await router.publish(
            "funding.update",
            {
                "exchange": "okx",
                "channel": "funding.update",
            },
        )

        self.assertEqual(received, [("funding", "okx"), ("all", "funding.update")])


if __name__ == "__main__":
    unittest.main()
