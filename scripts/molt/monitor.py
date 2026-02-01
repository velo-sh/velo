import json
import fcntl
import requests
from datetime import datetime, timedelta
from pathlib import Path
from utils import MoltbookClient, load_credentials

HOTSPOTS_PATH = Path(__file__).parent / "hotspots.json"

# AI-focused Keywords for filtering relevant technical content
KEYWORDS = ["python", "startup", "performance", "cold start", "zygote", "rust", "low latency", "optimization", "runtime", "latency"]

def calculate_score(upvotes, comments_count, created_at_iso):
    """
    Score = (upvotes * 2 + comments) * decay_factor
    decay_factor = 1 / (1 + hours_since_post / 3)
    """
    try:
        # Expected format: "2025-01-28T..."
        created_at = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=created_at.tzinfo)
        hours_since = (now - created_at).total_seconds() / 3600
        
        # Decay factor: halve the score every 3 hours roughly
        decay_factor = 1 / (1 + hours_since / 3)
        
        raw_score = (upvotes * 2) + comments_count
        return raw_score, decay_factor, raw_score * decay_factor
    except Exception as e:
        # print(f"Scoring error: {e}")
        return 0, 1.0, 0

def is_question(title, content):
    """Heuristic to detect if the post is a question or request for help."""
    text = (title + " " + content).lower()
    question_marks = "?" in text
    question_words = ["how", "why", "what", "is there", "any way", "explain"]
    has_word = any(word in text for word in question_words)
    return question_marks or has_word

def load_hotspots():
    if not HOTSPOTS_PATH.exists():
        return []
    try:
        with open(HOTSPOTS_PATH, 'r') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except:
        return []

def save_hotspots(hotspots):
    try:
        with open(HOTSPOTS_PATH, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(hotspots, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        print(f"Failed to save hotspots: {e}")

def main():
    print("Moltbook Listener (v3.0) starting...")
    try:
        creds = load_credentials()
        client = MoltbookClient(creds["api_key"])
    except Exception as e:
        print(f"Auth error: {e}")
        return

    # 1. Load and purge entries older than 24h
    hotspots = load_hotspots()
    now_utc = datetime.utcnow()
    initial_count = len(hotspots)
    
    # Filter out TTL expired or malformed
    valid_hotspots = []
    for h in hotspots:
        try:
            discovered_at = datetime.fromisoformat(h.get('discovered_at'))
            if (now_utc - discovered_at).total_seconds() < 86400: # 24h
                valid_hotspots.append(h)
        except:
            continue
    
    if len(valid_hotspots) < initial_count:
        print(f"Purged {initial_count - len(valid_hotspots)} stale entries.")
    
    # 2. Fetch latest feed
    print("Scanning global feed...")
    try:
        feed = client.get_feed(limit=50)
        posts = feed.get("posts", [])
    except Exception as e:
        print(f"Failed to fetch feed: {e}")
        return

    new_found = 0
    existing_ids = {h['post_id'] for h in valid_hotspots}

    for post in posts:
        post_id = post.get("id")
        if post_id in existing_ids:
            continue
            
        title = post.get("title") or ""
        content = post.get("content") or ""
        if not content and not title:
            continue
        
        # 3. Keyword filter
        combined_text = (title + " " + content).lower()
        if not any(kw in combined_text for kw in KEYWORDS):
            continue
            
        # 4. Scoring logic
        upvotes = post.get("upvotes", 0)
        # Moltbook API usually returns comment count in the 'comments' field for feed posts
        # Sometimes it's a list, check type
        raw_comments = post.get("comments", 0)
        comments_count = len(raw_comments) if isinstance(raw_comments, list) else int(raw_comments)
        
        raw_score, decay, final_score = calculate_score(upvotes, comments_count, post.get("created_at", datetime.utcnow().isoformat()))
        
        q_status = is_question(title, content)
        if q_status:
            final_score += 10 # Question bonus
            
        # 5. Add to queue
        valid_hotspots.append({
            "post_id": post_id,
            "title": title,
            "author": post.get("author", {}).get("name"),
            "content_snippet": content[:200] + ("..." if len(content) > 200 else ""),
            "upvotes": upvotes,
            "comments": comments_count,
            "raw_score": raw_score,
            "decay_factor": round(decay, 2),
            "final_score": round(final_score, 2),
            "is_question": q_status,
            "discovered_at": now_utc.isoformat(),
            "processed": False
        })
        new_found += 1

    # 6. Final sort by priority score
    valid_hotspots.sort(key=lambda x: x['final_score'], reverse=True)

    # 7. Persistence
    save_hotspots(valid_hotspots)
    print(f"Scan complete. New: {new_found}, Total Active: {len(valid_hotspots)}")

if __name__ == "__main__":
    main()
