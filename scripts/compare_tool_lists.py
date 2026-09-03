import argparse
import json
from urllib.request import Request, urlopen


def list_tools(endpoint: str, token: str) -> list[dict]:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ).encode()
    request = Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urlopen(request) as response:
        return json.load(response)["result"]["tools"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://localhost:8000/mcp")
    parser.add_argument("--user-a-token", default="demo-engineer")
    parser.add_argument("--user-b-token", default="demo-finance")
    args = parser.parse_args()

    user_a = {tool["name"] for tool in list_tools(args.endpoint, args.user_a_token)}
    user_b = {tool["name"] for tool in list_tools(args.endpoint, args.user_b_token)}

    print("Only User A:", sorted(user_a - user_b))
    print("Only User B:", sorted(user_b - user_a))
    print("Shared:", sorted(user_a & user_b))


if __name__ == "__main__":
    main()
