import os
import asyncio
import httpx
import uvicorn
import certifi
import logging
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo.errors import PyMongoError
from typing import List, Dict
import dotenv

dotenv.load_dotenv()

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
HEALTH_PORT = int(os.getenv("HEALTH_PORT", 8051))
MONGO_URI = os.getenv("MONGO_URI", "")
MY_SERVER_ID = os.getenv("SERVER_ID", "unknown-server")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Parse Targets: "IP|NAME,IP2|NAME2" -> [{"ip": "...", "name": "..."}]
raw_targets = os.getenv("TARGETS", "")
TARGETS: List[Dict[str, str]] = []
if raw_targets:
    for item in raw_targets.split(","):
        if "|" in item:
            ip, name = item.split("|")
            TARGETS.append({"ip": ip.strip(), "name": name.strip()})
        else:
            TARGETS.append({"ip": item.strip(), "name": "Unknown-GPU"})

DB_NAME = "gpu_monitor"
COLLECTION_ACTIVE = "crashes"
COLLECTION_HISTORY = "crash_history"

CONFIRMATION_DELAY_MINUTES = 3
REMINDER_INTERVAL_HOURS = 2
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 10
GOOGLE_HEALTH_CHECK_URL = "https://www.google.com"

# --- GLOBALS ---
mongo_client = None
active_collection = None
history_collection = None

# --- HELPERS ---
async def send_slack_alert(message: str):
    if not SLACK_WEBHOOK_URL:
        return
    webhooks = [url.strip() for url in SLACK_WEBHOOK_URL.split(",") if url.strip()]
    async with httpx.AsyncClient() as client:
        for url in webhooks:
            try:
                await client.post(url, json={"text": message})
            except Exception as e:
                logger.error(f"Slack Error for {url}: {e}")

async def check_external_connectivity() -> bool:
    """Check if WE have internet before blaming the peer."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(GOOGLE_HEALTH_CHECK_URL)
            return resp.status_code == 200
    except:
        return False

async def ping_peer(target_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target_url)
            return resp.status_code == 200
    except:
        return False

# --- MONITOR LOOP ---
async def monitor_peers():
    await asyncio.sleep(5)  # Warmup
    logger.info(f"🚀 {MY_SERVER_ID} Monitoring started. Watching: {[t['name'] for t in TARGETS]}")
    
    # State tracker for isolation
    was_isolated = False 
    
    while True:
        # 1. Global Safety Checks
        if active_collection is None:
            logger.warning("Waiting for DB connection...")
            await asyncio.sleep(30)
            continue

        if not await check_external_connectivity():
            logger.warning("Local internet down — Pausing monitoring loop.")
            await asyncio.sleep(30)
            continue

        # --- 2. THE TRUTHFUL ISOLATION CHECK ---
        successful_pings_count = 0
        peer_results = {} 

        # Scan all targets first
        for target in TARGETS:
            url = f"http://{target['ip']}:{HEALTH_PORT}/health"
            alive = await ping_peer(url)
            peer_results[target['ip']] = alive
            if alive:
                successful_pings_count += 1
        
        # LOGIC GATE: Are we isolated?
        is_isolated = (len(TARGETS) > 0 and successful_pings_count == 0)

        # STATE TRANSITION: Entering Isolation
        if is_isolated and not was_isolated:
            logger.warning(f"ISOLATION DETECTED: {MY_SERVER_ID} cannot reach any peers.")
            
            await send_slack_alert(
                f"*MONITOR ISOLATED:* *{MY_SERVER_ID}* cannot reach ANY peers.\n"
                f"Please verify manually."
            )
            was_isolated = True
            await asyncio.sleep(30)
            continue

        # STATE TRANSITION: Still Isolated
        elif is_isolated and was_isolated:
            logger.info("... still isolated.")
            await asyncio.sleep(30)
            continue

        # STATE TRANSITION: Recovered from Isolation
        elif not is_isolated and was_isolated:
            logger.info("Connection restored. Exiting isolation mode.")
            await send_slack_alert(f" *MONITOR RECONNECTED:* *{MY_SERVER_ID}* has rejoined the mesh.")
            was_isolated = False

        # --- 3. NORMAL MONITORING (Only if not isolated) ---
        for target in TARGETS:
            target_ip = target["ip"]
            target_name = target["name"]
            
            # Start with the result from our isolation scan
            is_alive = peer_results.get(target_ip, False)
            
            # --- RETRY LOGIC (Restored) ---
            # If the initial scan failed, double-check before declaring it down
            if not is_alive:
                if not await check_external_connectivity():
                    continue # Internet died mid-loop

                logger.info(f"{target_name} ({target_ip}) failed check. Retrying...")
                for attempt in range(MAX_RETRIES):
                    await asyncio.sleep(INITIAL_BACKOFF_SECONDS)
                    url = f"http://{target_ip}:{HEALTH_PORT}/health"
                    if await ping_peer(url):
                        is_alive = True
                        logger.info(f"{target_name} recovered on retry {attempt + 1}.")
                        break
            
            try:
                if is_alive:
                    # RECOVERY LOGIC
                    crash_record = active_collection.find_one({"_id": target_ip})
                    if crash_record:
                        down_since = crash_record["down_since"].replace(tzinfo=timezone.utc)
                        recovered_at = datetime.now(timezone.utc)
                        duration_mins = int((recovered_at - down_since).total_seconds() / 60)

                        active_collection.delete_one({"_id": target_ip})

                        # Noise Filter: Only alert if down > 1 min
                        if duration_mins >= 1:
                            archive_record = crash_record.copy()
                            archive_record["status"] = "resolved"
                            archive_record["recovered_at"] = recovered_at
                            archive_record["_id"] = f"{target_ip}_{recovered_at.strftime('%Y%m%d_%H%M%S')}"
                            history_collection.insert_one(archive_record)

                            logger.info(f"Recovery detected: {target_name} (Down {duration_mins} mins)")
                            await send_slack_alert(
                                f" *RECOVERY:* Server *{target_name}* ({target_ip}) is back online.\n"
                                f" Was down for: {duration_mins} mins"
                            )
                        else:
                            logger.info(f"{target_name} blip resolved (<1 min). No alert.")

                else:
                    # CRASH LOGIC
                    current_time = datetime.now(timezone.utc)
                    
                    active_collection.update_one(
                        {"_id": target_ip}, 
                        {
                            "$set": {"status": "down", "target_name": target_name},
                            "$setOnInsert": {
                                "down_since": current_time, 
                                "last_alert_sent_at": None 
                            },
                            "$addToSet": {"witnesses": MY_SERVER_ID}
                        },
                        upsert=True
                    )
                    
                    # Check for Alert Timing
                    crash_doc = active_collection.find_one({"_id": target_ip})
                    if crash_doc:
                        down_since = crash_doc["down_since"].replace(tzinfo=timezone.utc)
                        last_alert = crash_doc.get("last_alert_sent_at")
                        if last_alert: last_alert = last_alert.replace(tzinfo=timezone.utc)
                        
                        time_down = (current_time - down_since).total_seconds() / 60
                        
                        if time_down >= CONFIRMATION_DELAY_MINUTES:
                            should_alert = False
                            if last_alert is None:
                                should_alert = True
                            elif (current_time - last_alert) > timedelta(hours=REMINDER_INTERVAL_HOURS):
                                should_alert = True
                            
                            if should_alert:
                                witnesses = crash_doc.get("witnesses", [])
                                msg = (
                                    f" *CRASH ALERT:* *{target_name}* ({target_ip}) is DOWN.\n"
                                    f" Down for: {int(time_down)} mins\n"
                                    f" Confirmed by: {', '.join(witnesses)}"
                                )
                                if last_alert: msg = " *REMINDER:* " + msg
                                
                                logger.warning(f"Sending alert for {target_name} (Down {int(time_down)} mins)")
                                active_collection.update_one(
                                    {"_id": target_ip},
                                    {"$set": {"last_alert_sent_at": current_time}}
                                )
                                await send_slack_alert(msg)

            except Exception as e:
                logger.error(f"Error processing {target_name}: {e}")

        await asyncio.sleep(30)

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, active_collection, history_collection
    if MONGO_URI:
        try:
            mongo_client = MongoClient(MONGO_URI, server_api=ServerApi('1'), tlsCAFile=certifi.where())
            mongo_client.admin.command('ping')
            logger.info("MongoDB Connected!")
            db = mongo_client[DB_NAME]
            active_collection = db[COLLECTION_ACTIVE]
            history_collection = db[COLLECTION_HISTORY]
        except Exception as e:
            logger.error(f"DB Connect Fail: {e}")
    
    monitor_task = asyncio.create_task(monitor_peers())
    yield
    monitor_task.cancel()
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed.")

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health_check():
    return {"status": "alive", "server": MY_SERVER_ID}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8051)