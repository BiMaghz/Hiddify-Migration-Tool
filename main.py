import requests
import json
import re
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'HIDDIFY': {
        'DOMAIN': os.getenv("HIDDIFY_DOMAIN"),
        'API_KEY': os.getenv("HIDDIFY_API_KEY"),
        'API_URL': os.getenv("HIDDIFY_DOMAIN") + "/api/v2/admin/user/"
    },
    'TARGET_SYSTEM': {
        'DOMAIN': os.getenv("DOMAIN"),
        'PORT': os.getenv("PORT"),
        'USERNAME': os.getenv("USERNAME"),
        'PASSWORD': os.getenv("PASSWORD"),
        'USER_PATH': os.getenv("USER_PATH")
    }
}

def process_username(name, existing_usernames, user_id):
    processed = re.sub(r'(?<=\S) (?=\S)', '_', name).lower()
    processed = re.sub(r'[^A-Za-z0-9_]', '', processed).lower()
    if len(processed) < 3:
        processed = f"user_{user_id}"
    processed = processed[:32]
    original = processed
    counter = 1
    while processed in existing_usernames:
        processed = f"{original}_{counter}"
        counter += 1
    return processed

def hiddify_fetch_users():
    headers = {
        "Accept": "application/json",
        "Hiddify-API-Key": CONFIG['HIDDIFY']['API_KEY']
    }
    response = requests.get(CONFIG['HIDDIFY']['API_URL'], headers=headers)
    if response.status_code == 403:
        raise SystemExit("ERROR: Hiddify Access Denied (403)")
    response.raise_for_status()
    return response.json()

def filter_active_users(users):
    active_users = [u for u in users if u.get("is_active", False)]
    return active_users, len(users) - len(active_users)

def transform_user_data(raw_users):
    processed_users = []
    existing_usernames = set()

    for user in raw_users:
        username = process_username(
            user.get("name", "unknown"),
            existing_usernames,
            user.get("id", "N/A")
        )
        existing_usernames.add(username)

        usage_limit = user.get("usage_limit_GB", 0) * 1024**3
        current_usage = user.get("current_usage_GB", 0) * 1024**3
        data_limit = max(0, int(usage_limit - current_usage))

        start_date = user.get("start_date")
        expire_date = (
            datetime.strptime(start_date, "%Y-%m-%d") 
            if start_date 
            else datetime.today()
        ) + timedelta(days=user.get("package_days", 0))

        mode_mapping = {
	    "yearly": "year",
            "monthly": "month",
            "weekly": "week",
            "daily": "day"
        }
        mode = mode_mapping.get(user.get("mode", ""), "no_reset")

        processed_users.append({
            "name": username,
            "uuid": user.get("uuid", "N/A"),
            "data_limit": data_limit,
            "expire_date": expire_date.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": mode
        })
    
    return processed_users

def get_auth_token():
    api_url = f"{CONFIG['TARGET_SYSTEM']['DOMAIN']}:{CONFIG['TARGET_SYSTEM']['PORT']}/api/admins/token"
    payload = {
        'username': CONFIG['TARGET_SYSTEM']['USERNAME'],
        'password': CONFIG['TARGET_SYSTEM']['PASSWORD'],
        'grant_type': 'password'
    }
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    response = requests.post(api_url, headers=headers, data=urlencode(payload))
    if response.status_code == 200:
        return response.json().get('access_token')
    print(f"Authentication Failed: {response.status_code} - {response.text}")
    return None

def migrate_users(users_data, token):
    services = get_services(token)
    if not services:
        return False

    service_ids = validate_services(services)
    if not service_ids:
        return False

    success_count = 0
    for user in users_data:
        if create_user(token, user, service_ids):
            success_count += 1
    
    print(f"\nMigration Summary:")
    print(f"Success: {success_count}")
    print(f"Failed: {len(users_data) - success_count}")
    return success_count > 0

def get_services(token):
    api_url = f"{CONFIG['TARGET_SYSTEM']['DOMAIN']}:{CONFIG['TARGET_SYSTEM']['PORT']}/api/services"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json'
    }
    response = requests.get(api_url, headers=headers)
    if response.status_code == 200:
        return response.json().get('items', [])
    print(f"Failed to fetch services: {response.status_code} - {response.text}")
    return None

def validate_services(services):
    service_map = {str(s['id']): s['name'] for s in services}
    print("\nAvailable Services:")
    for sid, name in service_map.items():
        print(f"ID: {sid} - {name}")
    
    selected = input("Enter service IDs (comma-separated): ").strip().split(',')
    invalid = [s.strip() for s in selected if s.strip() not in service_map]
    
    if invalid:
        print(f"Invalid service IDs: {', '.join(invalid)}")
        return None
    
    return [s.strip() for s in selected]

def create_user(token, user_data, service_ids):
    api_url = f"{CONFIG['TARGET_SYSTEM']['DOMAIN']}:{CONFIG['TARGET_SYSTEM']['PORT']}/api/users"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }

    try:
        payload = {
            "username": user_data['name'],
            "expire_strategy": "fixed_date",
            "expire_date": user_data['expire_date'],
            "data_limit": user_data['data_limit'],
            "data_limit_reset_strategy": user_data['mode'],
            "service_ids": service_ids
        }
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"Created user: {user_data['name']}")
            return True
        print(f"Failed to create {user_data['name']}: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error creating {user_data['name']}: {str(e)}")
    return False

def generate_subscription_rules(users_data, token):
    rules = ["RewriteEngine On"]
    for user in users_data:
        sub_url = get_subscription_url(token, user['name'])
        if sub_url:
            rules.append(
                f"RewriteCond %{{REQUEST_URI}} ^/{CONFIG['TARGET_SYSTEM']['USER_PATH']}/{user['uuid']}(/.*)?$"
            )
            rules.append(f"RewriteRule ^(.*)$ {sub_url} [P]")
    
    if len(rules) > 1:
        with open("htaccess", "w") as f:
            f.write("\n".join(rules))
        print("\nGenerated htaccess file successfully!")
    else:
        print("\nNo valid subscription URLs found!")

def get_subscription_url(token, username):
    api_url = f"{CONFIG['TARGET_SYSTEM']['DOMAIN']}:{CONFIG['TARGET_SYSTEM']['PORT']}/api/users/{username}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json'
    }
    response = requests.get(api_url, headers=headers)
    if response.status_code == 200:
        return response.json().get("subscription_url")
    print(f"Failed to get URL for {username}: {response.status_code}")
    return None

def main_menu():
    print("\n" + "="*41)
    print("\tHiddify Migration Toolkit")
    print("="*41)
    print("1. Export Users from Hiddify")
    print("2. Migrate Users to Marzneshin")
    print("3. Generate Subscription Rules")
    print("4. Full Migration (Export + Migrate + Generate)")
    print("5. Exit")
    
    choice = input("\nSelect an option: ").strip()
    return choice

def main():
    while True:
        choice = main_menu()
        
        if choice == '1':
            try:
                raw_users = hiddify_fetch_users()
                active_users, inactive_count = filter_active_users(raw_users)
                transformed = transform_user_data(active_users)
                with open("users_data.json", "w") as f:
                    json.dump(transformed, f, indent=2)
                print(f"\nExported {len(transformed)} users successfully!")
                print(f"Skipped {inactive_count} inactive users")
            except Exception as e:
                print(f"\nExport Failed: {str(e)}")
        
        elif choice == '2':
            token = get_auth_token()
            if token:
                try:
                    with open("users_data.json", "r") as f:
                        users = json.load(f)
                    migrate_users(users, token)
                except FileNotFoundError:
                    print("\nError: users_data.json not found! Export first")
        
        elif choice == '3':
            token = get_auth_token()
            if token:
                try:
                    with open("users_data.json", "r") as f:
                        users = json.load(f)
                    generate_subscription_rules(users, token)
                except FileNotFoundError:
                    print("\nError: users_data.json not found! Export first")
        
        elif choice == '4':
            try:
                print("\nStarting Export...")
                raw_users = hiddify_fetch_users()
                active_users, _ = filter_active_users(raw_users)
                transformed = transform_user_data(active_users)
                with open("users_data.json", "w") as f:
                    json.dump(transformed, f, indent=2)
                
                print("\nStarting Migration...")
                token = get_auth_token()
                if token and migrate_users(transformed, token):
                    print("\nGenerating Subscription Rules...")
                    generate_subscription_rules(transformed, token)
                
            except Exception as e:
                print(f"\nFull Migration Failed: {str(e)}")
        
        elif choice == '5':
            print("\nExiting...")
            break
        
        else:
            print("\nInvalid choice! Try again")
        
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main()
