"""Wait for local service readiness during systemd startup."""
import argparse
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(args.url, timeout=3) as response:
                if response.status == 200:
                    print(f"Ready: {args.url}", flush=True)
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    raise SystemExit(f"Readiness timed out: {args.url}")


if __name__ == "__main__":
    main()
