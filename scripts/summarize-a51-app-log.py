"""Print narrowly selected diagnostic facts without account data or URL queries."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def analyze(path):
    raw = path.read_bytes()
    result = {"source": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
              "requests": [], "errors": [], "app_events": [], "keyword_counts": {}}
    counts = Counter()
    for number, line in enumerate(raw.decode(errors="replace").splitlines(), 1):
        stamp = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?", line)
        stamp = stamp[0] if stamp else None
        if "hakios: Instagram: starting a session task for " in line:
            value = line.split("starting a session task for ", 1)[1]
            try:
                url = urlsplit(value)
                host = url.hostname
                path_value = re.sub(r"(?<=/)\d+(?=/|$)", "<id>", url.path)
                # Only service endpoints, never user profile paths.
                endpoint = path_value if host in ("graph.facebook.com", "i.instagram.com") else None
            except ValueError:
                host, endpoint = None, None
            result["requests"].append({"line": number, "host": host, "endpoint": endpoint})
        for domain in ("NSURLErrorDomain", "kCFErrorDomainCFNetwork", "OSStatus", "NSCocoaErrorDomain"):
            if domain in line:
                code = re.search(re.escape(domain) + r"(?:\s+Code[= :]+|\s+error[: ]*\[?|\s+)(-?\d+)", line)
                if code:
                    result["errors"].append({"line": number, "time": stamp,
                                              "domain": domain, "code": int(code[1])})
        if line.startswith("hakios: Instagram:"):
            if any(token in line for token in ("started as uid", "SIGNAL", "UNCAUGHT EXCEPTION")):
                kind = "start" if "started as uid" in line else "signal" if "SIGNAL" in line else "exception"
                result["app_events"].append({"line": number, "kind": kind})
            for token in ("asking UIKit for", "the background task is", "starting a session task",
                          "SecItemCopyMatching returned", "SecItemUpdate returned", "persistent fallback cache",
                          "SecItemDelete returned", "SecItemAdd returned"):
                if token in line:
                    counts[token] += 1
        for token in ("loadServerConfigurationWithCompletionBlock failed", "SSLHandshake failed", "TLS handshake failed"):
            if token in line:
                counts[token] += 1
    result["keyword_counts"] = dict(counts)
    return result


if __name__ == "__main__":
    print(json.dumps(analyze(Path(sys.argv[1])), indent=2))
