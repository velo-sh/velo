import json
import os
import requests
from pathlib import Path

DEFAULT_CREDENTIALS_PATH = Path.home() / ".config" / "moltbook" / "credentials.json"
BASE_URL = "https://www.moltbook.com/api/v1"

def load_credentials(path=DEFAULT_CREDENTIALS_PATH):
    if not path.exists():
        raise FileNotFoundError(f"Credentials not found at {path}")
    with open(path, 'r') as f:
        return json.load(f)

class MoltbookClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _request(self, method, url, **kwargs):
        import time
        max_retries = 3
        backoff = 2
        
        # Ensure we always have headers
        headers = kwargs.pop('headers', self.headers)

        for i in range(max_retries):
            try:
                resp = requests.request(method, url, headers=headers, **kwargs)
                
                if resp.status_code == 429:
                    # Try to get retry time from header or body
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait = int(retry_after) if retry_after else None
                    except ValueError:
                        wait = None
                    
                    if not wait:
                        # Fallback to body parsing for Moltbook specific format
                        try:
                            data = resp.json()
                            wait = data.get("retry_after_seconds") or (data.get("retry_after_minutes", 0) * 60)
                        except:
                            wait = backoff * (2 ** i)
                    
                    print(f"Rate limited (429). Waiting {wait}s before retry {i+1}/{max_retries}...")
                    time.sleep(wait)
                    continue
                
                if resp.status_code == 401:
                    content = resp.text.lower()
                    # Expanded patterns for "Fake 401" caused by backend instability
                    fake_patterns = ["upstream", "reset", "disconnect", "authentication required"]
                    if any(p in content for p in fake_patterns):
                        wait = backoff * (2 ** i)
                        print(f"Detected potential backend overload (Fake 401: {content}). Waiting {wait}s before retry {i+1}/{max_retries}...")
                        time.sleep(wait)
                        continue
                    else:
                        print(f"Authentic Authentication Error (401) on {url}: {resp.text}")
                
                resp.raise_for_status()
                return resp.json()
            except (requests.exceptions.RequestException, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                wait = backoff * (2 ** i)
                if i == max_retries - 1:
                    print(f"Request failed after {max_retries} attempts: {e}")
                    raise
                print(f"Connection issue detected: {e}. Retrying in {wait}s ({i+1}/{max_retries})...")
                time.sleep(wait)
        
        raise Exception("Max retries exceeded for Moltbook API (Unhandled State)")

    def post(self, title, content, submolt="general"):
        url = f"{BASE_URL}/posts"
        data = {"title": title, "content": content, "submolt": submolt}
        return self._request("POST", url, json=data)

    def comment(self, post_id, content):
        url = f"{BASE_URL}/posts/{post_id}/comments"
        data = {"content": content}
        return self._request("POST", url, json=data)

    def get_feed(self, limit=20):
        url = f"{BASE_URL}/posts?limit={limit}"
        return self._request("GET", url)

    def get_notifications(self):
        url = f"{BASE_URL}/agents/status"
        return self._request("GET", url)
    def get_hotspots(self, min_score=0, unprocessed_only=True):
        """Helper for AI to read discovered technical hotspots from monitor.py"""
        path = Path(__file__).parent / "hotspots.json"
        if not path.exists():
            return []
        try:
            import fcntl
            with open(path, 'r') as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            
            if unprocessed_only:
                data = [h for h in data if not h.get('processed')]
            
            return [h for h in data if h.get('final_score', 0) >= min_score]
        except:
            return []

    def get_post_comments(self, post_id):
        url = f"{BASE_URL}/posts/{post_id}/comments"
        return self._request("GET", url)

    def update_avatar(self, file_path):
        """Upload a new avatar for the agent"""
        url = f"{BASE_URL}/agents/me/avatar"
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Avatar file not found: {file_path}")
        
        # We need to remove Content-Type from headers for multipart uploads
        headers = self.headers.copy()
        headers.pop("Content-Type", None)
        
        with open(file_path, 'rb') as f:
            files = {'file': f}
            return self._request("POST", url, headers=headers, files=files)
