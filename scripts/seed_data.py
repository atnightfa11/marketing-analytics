# Minimal synthetic sender that hits /api/shuffle with privatized presence bits
import os, json, time, random, requests, datetime as dt

API = os.environ.get("API_URL", "http://localhost:8000")
TOKEN = os.environ.get("UPLOAD_TOKEN", "DEV_TOKEN")
SITE = os.environ.get("SITE_ID", "dev-site")
ORIGIN = os.environ.get("ORIGIN", "http://localhost:5173")

def main(n_users=50, eps=0.5):
    day = dt.datetime.utcnow().strftime("%Y-%m-%d")
    batch = []
    for _ in range(n_users):
        bit = 1 if random.random() < 0.7 else 0  # 70 percent show up
        # client already privatizes in real flow; we fake it here
        rr = 1 if random.random() < 0.65 else 0
        batch.append({
            "kind": "presence_day",
            "site_id": SITE,
            "day": day,
            "bit": rr,
            "epsilon_used": eps,
            "sampling_rate": 1.0,
            "ts_client": int(time.time() * 1000)
        })
    r = requests.post(
        f"{API}/api/shuffle",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "X-Site-ID": SITE,
            "X-Origin": ORIGIN
        },
        data=json.dumps(batch),
        timeout=10
    )
    print("status", r.status_code, r.text)

if __name__ == "__main__":
    main()
