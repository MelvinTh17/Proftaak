import requests
import argparse
import time
from datetime import datetime
from tabulate import tabulate
import os
from dotenv import load_dotenv

load_dotenv()

PROMETHEUS_URL = os.getenv('PROMETHEUS_URL')
CPU_QUERY = os.getenv('PROMETHEUS_QUERY_CPU', '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)')
RAM_QUERY = os.getenv('PROMETHEUS_QUERY_RAM', '100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))')
ZAMMAD_URL = os.getenv('ZAMMAD_URL')
ZAMMAD_TOKEN = os.getenv('ZAMMAD_TOKEN')
CPU_THRESHOLD = float(os.getenv('CPU_THRESHOLD', '80.0'))
RAM_THRESHOLD = float(os.getenv('RAM_THRESHOLD', '80.0'))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '10'))
ZAMMAD_CUSTOMER = os.getenv('ZAMMAD_CUSTOMER')

PUSHOVER_API_URL = os.getenv('PUSHOVER_API_URL')
PUSHOVER_USER_KEY = os.getenv('PUSHOVER_USER_KEY')
PUSHOVER_TOKEN = os.getenv('PUSHOVER_TOKEN')

parser = argparse.ArgumentParser(description="Prometheus CPU monitor + Zammad ticket creator")
parser.add_argument("-d", "--debug", action="store_true", help="Debug mode, maakt geen tickets aan")
args = parser.parse_args()

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

def get_metrics():
    try:
        log("Haalt metrics op via Prometheus API")
        metrics = {}
        
        cpu_resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": CPU_QUERY},
            timeout=5
        )
        cpu_resp.raise_for_status()
        cpu_results = cpu_resp.json()["data"]["result"]
        
        ram_resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": RAM_QUERY},
            timeout=5
        )
        ram_resp.raise_for_status()
        ram_results = ram_resp.json()["data"]["result"]
        
        for result in cpu_results:
            instance = result["metric"]["instance"]
            metrics[instance] = {
                "cpu": float(result["value"][1]),
                "ram": 0.0 
            }
        
        for result in ram_results:
            instance = result["metric"]["instance"]
            if instance in metrics:
                metrics[instance]["ram"] = float(result["value"][1])
        
        log(f"Gebruikspercentages: {metrics}")
        return metrics
    except Exception as e:
        log(f"Fout bij ophalen metrics: {e}")
        return {}

def ticket_exists(instance, resource_type):
    try:
        search_url = f"{ZAMMAD_URL}/api/v1/tickets"
        headers = {
            "Authorization": f"Token token={ZAMMAD_TOKEN}",
            "Content-Type": "application/json"
        }
        search_query = f"{instance} {resource_type}"
        params = {"query": search_query}
        r = requests.get(search_url, headers=headers, params=params)
        r.raise_for_status()
        tickets = r.json()

        for ticket in tickets:
            if (instance in ticket.get("title", "") and 
                resource_type in ticket.get("title", "") and 
                ticket.get("state_id") == 1): 
                log(f"Ticket bestaat al voor {instance} {resource_type} (ID: {ticket['id']})")
                return True

        return False
    except Exception as e:
        log(f"Fout bij ticket-check: {e}")
        return False

def send_pushover_notification(instance, resource_type, usage):
    try:
        message = f"ALERT: {resource_type} gebruik {usage:.1f}% op {instance}"
        payload = {
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "message": message,
            "title": f"Monitoring Alert - {resource_type}",
            "priority": 1  
        }
        
        response = requests.post(PUSHOVER_API_URL, json=payload)
        if response.status_code == 200:
            log(f"Pushover notificatie verzonden voor {instance} {resource_type}")
        else:
            log(f"Fout bij verzenden Pushover notificatie: {response.status_code} - {response.text}")
    except Exception as e:
        log(f"Fout bij verzenden Pushover notificatie: {e}")

def create_ticket(instance, resource_type, usage):
    if ticket_exists(instance, resource_type):
        log(f"Geen nieuw ticket aangemaakt – er bestaat al een open ticket voor {instance} {resource_type}")
        return

    log(f"Aanmaken ticket voor {instance} ({resource_type}: {usage:.2f}%)")

    send_pushover_notification(instance, resource_type, usage)

    payload = {
        "title": f"{resource_type} gebruik hoog op {instance}",
        "group": "Users",
        "customer": ZAMMAD_CUSTOMER,
        "article": {
            "subject": f"{resource_type} gebruik {instance}",
            "body": f"Het {resource_type} gebruik op instantie {instance} is momenteel {usage:.2f}%.",
            "type": "note",
            "internal": True
        }
    }

    headers = {
        "Authorization": f"Token token={ZAMMAD_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(f"{ZAMMAD_URL}/api/v1/tickets", json=payload, headers=headers)
        if r.status_code == 201:
            log(f"Ticket succesvol aangemaakt voor {instance} {resource_type}")
        else:
            log(f"Ticketfout {instance}: {r.status_code} - {r.text}")
    except Exception as e:
        log(f"Fout tijdens ticket-aanmaak: {e}")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

log("Resource monitoring gestart...")
while True:
    clear_screen()
    metrics = get_metrics()
    
    table_data = []
    for instance, values in metrics.items():
        cpu_status = "!ALERT!" if values["cpu"] > CPU_THRESHOLD else "OK"
        ram_status = "!ALERT!" if values["ram"] > RAM_THRESHOLD else "OK"
        table_data.append([
            instance,
            f"{values['cpu']:.2f}%",
            cpu_status,
            f"{values['ram']:.2f}%",
            ram_status
        ])
    
    headers = ["Host", "CPU Usage", "CPU Status", "RAM Usage", "RAM Status"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print(f"\nLaatste update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Check interval: {CHECK_INTERVAL} seconden")
    
    for instance, values in metrics.items():
        if args.debug:
            if values["cpu"] > CPU_THRESHOLD:
                log(f"CPU drempel overschreden voor {instance}, maar debugmodus actief")
            if values["ram"] > RAM_THRESHOLD:
                log(f"RAM drempel overschreden voor {instance}, maar debugmodus actief")
        else:
            if values["cpu"] > CPU_THRESHOLD:
                create_ticket(instance, "CPU", values["cpu"])
            if values["ram"] > RAM_THRESHOLD:
                create_ticket(instance, "RAM", values["ram"])

    time.sleep(CHECK_INTERVAL)
