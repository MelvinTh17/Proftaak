import requests
from datetime import datetime, timedelta
import time
import os
import json
import argparse
import random
import logging
from dotenv import load_dotenv

last_deploy_time = None
last_destroy_time = None
last_notification_time = None
last_token_refresh_time = None
current_access_token = None

load_dotenv()

def load_config():
    config = {
        'azure': {
            'tenant_id': os.getenv('AZURE_TENANT_ID'),
            'client_id': os.getenv('AZURE_CLIENT_ID'),
            'client_secret': os.getenv('AZURE_CLIENT_SECRET'),
            'subscription_id': os.getenv('AZURE_SUBSCRIPTION_ID')
        },
        'elasticsearch': {
            'url': os.getenv('ELASTICSEARCH_URL'),
            'user': os.getenv('ELASTICSEARCH_USER'),
            'password': os.getenv('ELASTICSEARCH_PASSWORD')
        },
        'github': {
            'token': os.getenv('GITHUB_TOKEN'),
            'api_url': os.getenv('GITHUB_API_URL'),
            'destroy_url': os.getenv('GITHUB_DESTROY_URL')
        },
        'pushover': {
            'api_url': os.getenv('PUSHOVER_API_URL'),
            'configs': [
                {
                    'user_key': os.getenv('PUSHOVER_CONFIG_1_USER_KEY'),
                    'token': os.getenv('PUSHOVER_CONFIG_1_TOKEN')
                },
                {
                    'user_key': os.getenv('PUSHOVER_CONFIG_2_USER_KEY'),
                    'token': os.getenv('PUSHOVER_CONFIG_2_TOKEN')
                }
            ]
        },
        'thresholds': {
            'network_traffic': int(os.getenv('NETWORK_TRAFFIC_THRESHOLD', '768000')),
            'network_minimum': int(os.getenv('NETWORK_TRAFFIC_MINIMUM', '133120')),
            'deploy_cooldown': int(os.getenv('DEPLOY_COOLDOWN', '300')),
            'destroy_cooldown': int(os.getenv('DESTROY_COOLDOWN', '300')),
            'notification_cooldown': int(os.getenv('NOTIFICATION_COOLDOWN', '60'))
        }
    }
    return config

def setup_logging():
    logging.basicConfig(
        filename='container_actions.log',
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def format_bytes(bytes_value):
    if bytes_value >= 1024:
        return f"{bytes_value/1024:.1f} KB/s"
    return f"{bytes_value:.1f} B/s"

def send_pushover_notification(config, title, message, priority=0):
    global last_notification_time
    
    current_time = datetime.utcnow()
    if last_notification_time and (current_time - last_notification_time).total_seconds() < config['thresholds']['notification_cooldown']:
        return
        
    try:
        for pushover_config in config['pushover']['configs']:
            payload = {
                "token": pushover_config["token"],
                "user": pushover_config["user_key"],
                "title": title,
                "message": message,
                "priority": priority
            }
            
            response = requests.post(config['pushover']['api_url'], json=payload)
            response.raise_for_status()
            print(f"📱 Notificatie verzonden naar {pushover_config['user_key']}: {title}")
        
        last_notification_time = current_time
    except Exception as e:
        print(f"Fout bij verzenden notificatie: {e}")

def get_azure_token(config):
    global last_token_refresh_time, current_access_token
    
    current_time = datetime.utcnow()
    
    if (current_access_token and last_token_refresh_time and 
        (current_time - last_token_refresh_time).total_seconds() < 3600):
        return current_access_token
        
    try:
        response = requests.post(
            f"https://login.microsoftonline.com/{config['azure']['tenant_id']}/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": config['azure']['client_id'],
                "client_secret": config['azure']['client_secret'],
                "resource": "https://management.azure.com/"
            }
        )
        response.raise_for_status()
        token_data = response.json()
        current_access_token = token_data.get("access_token")
        last_token_refresh_time = current_time
        print(f"Azure token vernieuwd op {current_time.strftime('%H:%M:%S')}")
        return current_access_token
    except Exception as e:
        print(f"Fout bij ophalen Azure token: {e}")
        return None

def send_github_workflow_dispatch(config, container_name, metric_value, is_destroy=False, total_containers=0, monitor_only=False):
    global last_deploy_time, last_destroy_time
    action = "deploy" if not is_destroy else "destroy"  
    
    if monitor_only:
        print(f"Monitor mode: Zou {'destroy' if is_destroy else 'deploy'} container {container_name}")
        logging.info(f"Monitor mode: Zou {'destroy' if is_destroy else 'deploy'} container {container_name}")
        return
        
    try:
        if is_destroy:
            if total_containers <= 1:
                print(f"Skipping destroy van {container_name}")
                logging.info(f"Skipping destroy van {container_name}")
                return
                
            current_time = datetime.utcnow()
            if last_destroy_time and (current_time - last_destroy_time).total_seconds() < config['thresholds']['destroy_cooldown']:
                remaining = config['thresholds']['destroy_cooldown'] - (current_time - last_destroy_time).total_seconds()
                print(f"Skipping destroy - cooldown periode actief ({remaining:.0f} seconden resterend)")
                logging.info(f"Skipping destroy - cooldown period actief ({remaining:.0f} seconden resterend)")
                return
                
            payload = {
                "ref": "master",
                "inputs": {
                    "containerName": container_name
                }
            }
            url = config['github']['destroy_url']
            last_destroy_time = current_time
            
            logging.info(f"Container {container_name} wordt verwijderd vanwege lage netwerk activiteit ({format_bytes(metric_value)})")
            logging.info(f"Totale containers over: {total_containers - 1}")
            
            send_pushover_notification(
                config,
                "Container Verwijderd",
                f"Container {container_name} wordt verwijderd vanwege lage netwerk activiteit ({format_bytes(metric_value)}).\n"
                f"Totale containers over: {total_containers - 1}",
                priority=1
            )
        else:
            current_time = datetime.utcnow()
            if last_deploy_time and (current_time - last_deploy_time).total_seconds() < config['thresholds']['deploy_cooldown']:
                remaining = config['thresholds']['deploy_cooldown'] - (current_time - last_deploy_time).total_seconds()
                print(f"Skipping deploy - cooldown periode actief ({remaining:.0f} seconden resterend)")
                logging.info(f"Skipping deploy - cooldown periode actief ({remaining:.0f} seconden resterend)")
                return
            
            payload = {
                "ref": "master"
            }
            url = config['github']['api_url']
            last_deploy_time = current_time
            
            logging.info(f"Nieuwe container wordt aangemaakt vanwege hoge netwerk activiteit ({format_bytes(metric_value)})")
            logging.info(f"Totale containers na aanmaken: {total_containers + 1}")
            
            send_pushover_notification(
                config,
                "Container Aangemaakt",
                f"Nieuwe container wordt aangemaakt vanwege hoge netwerk activiteit:\n"
                f"Netwerk activiteit: {format_bytes(metric_value)}",
                priority=1
            )
        
        response = requests.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {config['github']['token']}"
            },
            json=payload,
            timeout=5
        )
        response.raise_for_status()
        print(f"GitHub {action} workflow triggered voor {container_name} (Network traffic: {format_bytes(metric_value)})")
        logging.info(f"GitHub {action} workflow triggered voor {container_name} (Network traffic: {format_bytes(metric_value)})")
    except Exception as e:
        error_msg = f"Error triggering GitHub {action} workflow: {e}"
        print(error_msg)
        logging.error(error_msg)
        send_pushover_notification(
            config,
            f"Container {action.capitalize()} Failed",
            f"Failed to {action} container {container_name}: {str(e)}",
            priority=2
        )

def send_to_elasticsearch(config, container_data, network_stats):
    try:
        doc = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "data_stream": {
                "dataset": "azure.container_instance"
            },
            "azure": {
                "container_instance": {
                    "network_bytes_received_per_second": {
                        "avg": network_stats.get("bytes_received", 0)
                    },
                    "network_bytes_transmitted_per_second": {
                        "avg": network_stats.get("bytes_transmitted", 0)
                    },
                    "cpu_usage": {
                        "avg": network_stats.get("cpu_usage", 0)
                    }
                },
                "resource": {
                    "name": container_data.get("name", "Unknown"),
                    "id": container_data.get("id", "Unknown")
                }
            },
            "host": {
                "hostname": container_data.get("properties", {}).get("containers", [{}])[0].get("name", "Unknown")
            },
            "cloud": {
                "region": container_data.get("location", "Unknown")
            }
        }

        response = requests.post(
            f"{config['elasticsearch']['url']}/metrics-azure.container_instance/_doc",
            auth=(config['elasticsearch']['user'], config['elasticsearch']['password']),
            json=doc,
            timeout=5
        )
        response.raise_for_status()
        print(f"Metrics verzonden naar Elasticsearch voor {container_data.get('name')}")
    except Exception as e:
        print(f"Fout bij verzenden naar Elasticsearch: {e}")

def send_container_count_to_elasticsearch(config, total_containers):
    try:
        doc = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "data_stream": {
                "dataset": "azure.container_count"
            },
            "azure": {
                "container_count": {
                    "total": total_containers
                }
            }
        }

        response = requests.post(
            f"{config['elasticsearch']['url']}/metrics-azure.container_count/_doc",
            auth=(config['elasticsearch']['user'], config['elasticsearch']['password']),
            json=doc,
            timeout=5
        )
        response.raise_for_status()
        print(f"Container count ({total_containers}) verzonden naar Elasticsearch")
    except Exception as e:
        print(f"Fout bij verzenden container count naar Elasticsearch: {e}")

def generate_fake_container_data(config):
    containers = []
    base_time = datetime.utcnow()
    
    for i in range(2):
        container_name = f"test-container-{i+1}-{int(base_time.timestamp())}"
        containers.append({
            "name": container_name,
            "id": f"/subscriptions/{config['azure']['subscription_id']}/resourceGroups/test-rg/providers/Microsoft.ContainerInstance/containerGroups/{container_name}",
            "location": "westeurope",
            "properties": {
                "containers": [{
                    "name": f"test-container-{i+1}"
                }]
            }
        })
    return {"value": containers}

def generate_fake_metrics():
    rx = random.randint(10 * 1024, 300 * 1024)
    tx = random.randint(5 * 1024, 150 * 1024)
    
    return {
        "value": [
            {
                "timeseries": [{
                    "data": [{"average": rx}]
                }]
            },
            {
                "timeseries": [{
                    "data": [{"average": tx}]
                }]
            }
        ]
    }

def main():
    config = load_config()
    
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Azure Container Monitor")
    parser.add_argument("-m", "--monitor", action="store_true", help="Monitor only mode - no container changes")
    parser.add_argument("-d", "--debug", action="store_true", help="Debug mode - use fake data instead of Azure")
    args = parser.parse_args()
    
    logging.info("Script gestart")
    if args.monitor:
        logging.info("Monitor mode actief - Geen container wijzigingen")
    if args.debug:
        logging.info("Debug mode actief - Gebruik nep data")
    
    access_token = get_azure_token(config)
    if not access_token:
        error_msg = "Kon geen Azure token ophalen. Script stopt."
        print(f"{error_msg}")
        logging.error(error_msg)
        return
        
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    while True:
        clear_screen()
        print("\n" + "="*50)
        print(f"Update op {datetime.now().strftime('%H:%M:%S')}")
        if args.monitor:
            print("Monitor mode actief - Geen container wijzigingen")
        if args.debug:
            print("Debug mode actief - Gebruik nep data")
        print("="*50)
        
        if args.debug:
            container_data = generate_fake_container_data(config)
        else:
            try:
                container_url = f"https://management.azure.com/subscriptions/{config['azure']['subscription_id']}/providers/Microsoft.ContainerInstance/containerGroups?api-version=2021-07-01"
                container_resp = requests.get(container_url, headers=headers)
                
                if container_resp.status_code == 401:
                    print("Token verlopen, nieuwe token ophalen...")
                    access_token = get_azure_token(config)
                    if not access_token:
                        print("Kon geen nieuwe token ophalen. Script stopt.")
                        return
                    headers["Authorization"] = f"Bearer {access_token}"
                    container_resp = requests.get(container_url, headers=headers)
                
                container_resp.raise_for_status()
                container_data = container_resp.json()
            except Exception as e:
                print(f"Fout bij ophalen containers: {e}")
                time.sleep(10)
                continue
        
        total_containers = len(container_data.get("value", []))
        
        send_container_count_to_elasticsearch(config, total_containers)
        
        if total_containers == 0:
            print("Geen containers gevonden! Er moet minimaal 1 container draaien.")
            send_pushover_notification(
                config,
                "Container Status Alert",
                "Er zijn geen containers actief! Er moet minimaal 1 container draaien.",
                priority=2
            )
            time.sleep(10)
            continue
            
        print("\nGevonden container groups:")
        for c in container_data.get("value", []):
            print("-", c["name"])
            
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=1)
        timespan = f"{start_time.isoformat()}Z/{end_time.isoformat()}Z"

        total_rx = 0
        total_tx = 0
        container_metrics = []

        for container in container_data.get("value", []):
            cid = container["id"]
            name = container["name"]

            if args.debug:
                data = generate_fake_metrics()
            else:
                metric_url = f"https://management.azure.com{cid}/providers/microsoft.insights/metrics"
                params = {
                    "api-version": "2018-01-01",
                    "metricnames": "NetworkBytesReceivedPerSecond,NetworkBytesTransmittedPerSecond,CpuUsage",
                    "interval": "PT1M",
                    "timespan": timespan
                }
                r = requests.get(metric_url, headers=headers, params=params)
                data = r.json()

            try:
                rx = data["value"][0]["timeseries"][0]["data"]
                tx = data["value"][1]["timeseries"][0]["data"]
                cpu = data["value"][2]["timeseries"][0]["data"]
                avg_rx = sum(p.get("average", 0) for p in rx) / len(rx)
                avg_tx = sum(p.get("average", 0) for p in tx) / len(tx)
                avg_cpu = sum(p.get("average", 0) for p in cpu) / len(cpu)
                
                network_stats = {
                    "bytes_received": avg_rx,
                    "bytes_transmitted": avg_tx,
                    "cpu_usage": avg_cpu
                }
                send_to_elasticsearch(config, container, network_stats)
                
                total_rx += avg_rx
                total_tx += avg_tx
                container_metrics.append({
                    "name": name,
                    "rx": avg_rx,
                    "tx": avg_tx,
                    "cpu": avg_cpu
                })
                
                print(f"{name} → Received: {format_bytes(avg_rx)} | Transmitted: {format_bytes(avg_tx)} | CPU: {avg_cpu:.1f}%")
            except Exception as e:
                print(f"Geen data voor {name} ({e})")
        
        if container_metrics:
            avg_rx = total_rx / len(container_metrics)
            avg_tx = total_tx / len(container_metrics)
            avg_cpu = sum(m.get("cpu", 0) for m in container_metrics) / len(container_metrics)
            print(f"\nGemiddelde metrics:")
            print(f"Received: {format_bytes(avg_rx)} | Transmitted: {format_bytes(avg_tx)} | CPU: {avg_cpu:.1f}%")
            
            if avg_rx > config['thresholds']['network_traffic']:
                print(f"    ALERT: Hoge gemiddelde netwerk activiteit!")
                print(f"    Gemiddeld ontvangen: {format_bytes(avg_rx)}")
                print(f"    Gemiddeld verzonden: {format_bytes(avg_tx)}")
                send_github_workflow_dispatch(config, "average", avg_rx, monitor_only=args.monitor)
            elif avg_rx < config['thresholds']['network_minimum']:
                print(f"    ALERT: Lage gemiddelde netwerk activiteit!")
                print(f"    Gemiddeld ontvangen: {format_bytes(avg_rx)}")
                print(f"    Gemiddeld verzonden: {format_bytes(avg_tx)}")
                
                if len(container_metrics) > 1:  
                    sorted_containers = sorted(container_data.get("value", []), key=lambda x: x["name"].split("-")[-1])
                    oldest_container = sorted_containers[0]["name"]
                    print(f"    Oudste container gevonden: {oldest_container}")
                    send_github_workflow_dispatch(config, oldest_container, avg_rx, is_destroy=True, total_containers=len(container_metrics), monitor_only=args.monitor)
        
        time.sleep(10)

if __name__ == "__main__":
    main() 
