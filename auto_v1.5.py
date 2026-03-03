import requests
import threading
import re
import os
from dotenv import load_dotenv
import streamlit as st
import time
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
# .env 로드
load_dotenv()

# --- [인증 정보: 이제 os.getenv로 가져옵니다] ---
DOORAY_TOKEN = os.getenv("DOORAY_TOKEN")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")

def get_nhn_token_for_background():
    auth_url = os.getenv("NHN_AUTH_URL")
    tenant_id = os.getenv("NHN_TENANT_ID")
    username = os.getenv("NHN_USERNAME")
    password = os.getenv("NHN_PASSWORD")
    
    payload = {
        "auth": {
            "tenantId": tenant_id,
            "passwordCredentials": {
                "username": username,
                "password": password
            }
        }
    }
    
    headers = {"Content-Type": "application/json"}
    res = requests.post(f"{auth_url}/tokens", json=payload, headers=headers, timeout=20)
    res.raise_for_status()
    return res.json()["access"]["token"]["id"]

# --- [1. 두레이 검증 및 검색 로직] ---
def get_recent_view_tasks():
    PROJECT_ID = os.getenv("DOORAY_PROJECT_ID")
    # API 호출 시에도 하드코딩 대신 가져온 TOKEN 사용
    URL = f"https://api.dooray.com/project/v1/projects/{PROJECT_ID}/posts?size=100&order=-createdAt"
    headers = {"Authorization": f"dooray-api {DOORAY_TOKEN}"}

    # 스캔 범위 설정
    scan_limit = datetime.now() - timedelta(days=10)
    found_tasks = []

    try:
        res = requests.get(URL, headers=headers).json()
        posts = res.get("result", [])

        if not posts:
            print("📡 데이터를 가져오지 못했습니다.")
            return []

        for post in posts:
            created_at_str = post.get("createdAt", "")
            created_at_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))

            if created_at_dt.replace(tzinfo=None) > scan_limit:
                subject = post.get("subject", "")
                if "xxx" in subject:
                    found_tasks.append({
                        "id": post["id"],
                        "title": subject,
                        "date": created_at_str[:10],
                        "number": post.get("number")
                    })
            else:
                break
    except Exception as e:
        print(f"❌ API 오류: {e}")

    return found_tasks

if __name__ == "__main__":
    print(f"🔍 최근 50일 내 'xxx' 건 검색 및 슬랙 발송 시작...")
    
    # [수정] 발송 시에도 환경변수에서 로드된 정보 사용
    tasks = get_recent_view_tasks()
    client = WebClient(token=SLACK_BOT_TOKEN)

    if tasks:
        # 중복 방지를 위한 기존 로그 로드 (이전에 만든 함수 활용 권장)
        # sent_tasks = load_sent_tasks() 
        
        print(f"✅ 총 {len(tasks)}건 발견! 슬랙으로 전송합니다.")
        for task in tasks:
            # [수정] 공백 허용 정규식 적용
            match = re.search(r"([가-힣]+)\s*\((\d+)\)", task['title'])
            if match:
                name, no = match.group(1), match.group(2)
                
                # 중복 체크 로직이 여기에 들어오면 완벽합니다.
                # if task['id'] in sent_tasks: continue

                client.chat_postMessage(
                    channel=CHANNEL_ID,
                    text=f"🔔 새로운 요청",
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"🔔 *대상*: {name}({no})\n*제목*: {task['title']}"}
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button", 
                                    "text": {"type": "plain_text", "text": "🚀 서버 즉시 생성"},
                                    "style": "primary", 
                                    "value": f"{name}:{no}", 
                                    "action_id": "approve_create_server"
                                }
                            ]
                        }
                    ]
                )
                print(f"📩 {name}({no}) 슬랙 발송 완료")
    else:
        print("📭 새로 발송할 기안이 없습니다.")

if __name__ == "__main__":
    print(f"🔍 최근 50일 내 'xxx' 건 검색 및 슬랙 발송 시작...")
    tasks = get_recent_view_tasks()
    
    # 슬랙 클라이언트 초기화 (기존 토큰 사용)
    client = WebClient(token=SLACK_BOT_TOKEN)

    if tasks:
        print(f"✅ 총 {len(tasks)}건 발견! 슬랙으로 전송합니다.")
        for task in tasks:
            # 제목에서 이름과 번호 추출 시도
            match = re.search(r"([가-힣]+)\s*\((\d+)\)", task['title'])
            if match:
                name, no = match.group(1), match.group(2)
                
                # [핵심] 슬랙으로 메시지 쏘기
                client.chat_postMessage(
                    channel=CHANNEL_ID,
                    text=f"🔔 새로운 요청.",
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"🔔 *대상*: {name}({no})\n*제목*: {task['title']}"}
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button", 
                                    "text": {"type": "plain_text", "text": "🚀 서버 즉시 생성"},
                                    "style": "primary", 
                                    "value": f"{name}:{no}", 
                                    "action_id": "approve_create_server"
                                }
                            ]
                        }
                    ]
                )
                print(f"📩 {name}({no}) 슬랙 발송 완료")
    else:
        print("📭 새로 발송할 기안이 없습니다.")


# --- [2. 중복 방지 로직] ---
SENT_LOG = "sent_tasks.txt"
def load_sent_tasks():
    if not os.path.exists(SENT_LOG): return set()
    with open(SENT_LOG, "r") as f:
        return set(line.strip() for line in f)

def save_sent_task(task_id):
    with open(SENT_LOG, "a") as f:
        f.write(f"{task_id}\n")

# --- [3. 슬랙 인터랙션 핸들러] ---
# --- [수정 1: 백그라운드용 순수 서버 생성 함수] ---
# --- [백그라운드 전용 서버 생성 함수] ---
def create_user_server_background(user_no, token):
    if not token:
        print("❌ 에러: 전달된 NHN 토큰이 없습니다!")
        return False


    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    
    # 이제 모든 ID를 메모리(os.environ)에서 가져옵니다.
    net_id = os.getenv("NHN_NET_ID")
    sub_id = os.getenv("NHN_SUB_ID")
    key_name = os.getenv("NHN_KEY_NAME")
    
    # 엔드포인트와 테넌트 ID도 env에서 관리 가능
    tenant_id = os.getenv("NHN_TENANT_ID_COMPUTE")
    compute_endpoint = os.getenv("COMPUTE_ENDPOINT")
    network_endpoint = compute_endpoint.replace('instance', 'network')

    try:
        # 1. 보안 그룹 조회
        sg_url = f"{network_endpoint}/v2.0/security-groups?name=Test-User-{user_no}"
        sg_res = requests.get(sg_url, headers=headers).json()
        sg_user = sg_res['security_groups'][0]['id']
        
        # 보안그룹 리스트도 env에서 로드
        sg_list = [os.getenv("NHN_SG_CO"), os.getenv("NHN_SG_MANAGER"), sg_user]

        def _request_server_with_ip(name, flavor, img, vol_size, ip_suffix):
             
            target_ip = f"10.0.0.{ip_suffix}"
            port_url = f"{network_endpoint}/v2.0/ports"
            
            ###########################################################
            ### [수정] 기존 포트가 있는지 먼저 조회하는 로직 추가 ###
            ###########################################################
            # 1) 해당 IP로 이미 생성된 포트가 있는지 GET 요청으로 확인
            check_port_url = f"{port_url}?fixed_ips=ip_address={target_ip}"
            check_res = requests.get(check_port_url, headers=headers).json()
            
            if check_res.get('ports') and len(check_res['ports']) > 0:
                # 이미 존재한다면 기존 포트 ID 사용
                port_id = check_res['ports'][0]['id']
                print(f"ℹ️ {name}: 기존 포트 재사용 ({target_ip})")
            else:
                # 존재하지 않는다면 새로 생성 (POST)
                port_data = {
                    "port": {
                        "name": f"{name}-port",
                        "network_id": net_id,
                        "fixed_ips": [{"subnet_id": sub_id, "ip_address": target_ip}],
                        "security_groups": sg_list
                    }
                }
                port_res = requests.post(port_url, headers=headers, json=port_data).json()
                if 'port' not in port_res:
                    print(f"❌ {name} 포트 생성 실패: {port_res}")
                    return False
                port_id = port_res['port']['id']
            ###########################################################

            # 서버 생성 (확보된 port_id 사용)
            server_url = f"{compute_endpoint}/v2/{tenant_id}/servers"
            server_payload = {
                "server": {
                    "name": name,
                    "flavorRef": flavor,
                    "key_name": key_name,
                    "networks": [{"port": port_id}],
                    "block_device_mapping_v2": [{
                        "source_type": "image",
                        "uuid": img,
                        "boot_index": 0,
                        "destination_type": "volume",
                        "volume_type": "General SSD",
                        "volume_size": vol_size,
                        "delete_on_termination": True
                    }]
                }
            }
            res = requests.post(server_url, headers=headers, json=server_payload)
            return res.status_code in [200, 202]
        
            # ... (이전과 동일한 포트 조회/생성 로직) ...
            # 서버 생성 시 flavor, img 변수도 env 로드값을 전달받음
           
        # 3. CPU & WIN 생성 호출 (env에서 가져온 이미지/플래버 사용)
        cpu_ok = _request_server_with_ip(
            f"test{user_no}@linux", 
            os.getenv("NHN_FLAVOR_CPU"), 
            os.getenv("NHN_IMG_CPU"), 
            500, f"1{user_no}"
        )
        win_ok = _request_server_with_ip(
            f"test{user_no}@window", 
            os.getenv("NHN_FLAVOR_WIN"), 
            os.getenv("NHN_IMG_WIN"), 
            100, user_no
        )

        return cpu_ok and win_ok

    except Exception as e:
        print(f"🔥 IP 할당 중 에러 발생: {e}")
        return False
# --- [수정 2: 슬랙 인터랙션 핸들러 업데이트] ---
def handle_slack_interaction(client, req):
    if req.type == "interactive":
        payload = req.payload
        action = payload["actions"][0]
        
        if action["action_id"] == "approve_create_server":
            user_info = action["value"] 
            user_name, user_no = user_info.split(":")
            
            print(f"⚙️ {user_name}({user_no}) 서버 생성 프로세스 가동...")
            
            try:
                # 1. 백그라운드용 전용 토큰 발급
                token = get_nhn_token_for_background() 
                
                # 2. [핵심] 주석을 풀고 백그라운드 전용 함수 호출!
                create_user_server_background(user_no, token) 
                print(f"✅ {user_name} 서버 생성 API 호출 완료")
                
                # 3. 슬랙 피드백 발송
                client.web_client.chat_postMessage(
                    channel=payload["channel"]["id"],
                    text=f"🚀 *작업 성공*: {user_name}({user_no})님 서버 생성이 시작되었습니다!"
                )
            except Exception as e:
                print(f"❌ 에러: {e}")
                client.web_client.chat_postMessage(
                    channel=payload["channel"]["id"],
                    text=f"⚠️ *작업 실패*: {user_name}님 서버 생성 중 오류가 발생했습니다. ({e})"
                )
            
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            

# --- [4. 메인 감지 루프] ---
def start_auto_monitoring():
    slack_bot = SocketModeClient(
    app_token=SLACK_APP_TOKEN,               # 반드시 xapp- 토큰이 들어와야 함
    web_client=WebClient(token=SLACK_BOT_TOKEN) # 반드시 xoxb- 토큰이 들어와야 함
)
    slack_bot.socket_mode_request_listeners.append(handle_slack_interaction)
    slack_bot.connect()
    
    sent_tasks = load_sent_tasks()
    print("🚀 MSP 자동화 봇 가동! 5분 주기로 두레이를 스캔합니다.")

    while True:
        try:
            tasks = get_recent_view_tasks()
            for task in tasks:
                if task['id'] not in sent_tasks:
                    # 제목에서 이름/번호 추출
                    match = re.search(r"\]\s*([가-힣]+)\((\d+)\)", task['title'])
                    if match:
                        name, no = match.group(1), match.group(2)
                        
                        slack_bot.web_client.chat_postMessage(
                            channel=CHANNEL_ID,
                            blocks=[
                                {"type": "section", "text": {"type": "mrkdwn", "text": f"🔔 *신규 서버 생성 요청 기안 감지*\n*대상*: {name}({no})\n*제목*: {task['title']}"}},
                                {"type": "actions", "elements": [
                                    {"type": "button", "text": {"type": "plain_text", "text": "🚀 서버 즉시 생성"},
                                     "style": "primary", "value": f"{name}:{no}", "action_id": "approve_create_server"}
                                ]}
                            ]
                        )
                        sent_tasks.add(task['id'])
                        save_sent_task(task['id'])
            
            time.sleep(300) # 5분 대기
        except Exception as e:
            print(f"⚠️ 루프 에러: {e}")
            time.sleep(60)



if __name__ == "__main__":
    # 1. 두레이 감지 봇을 별도의 쓰레드(백그라운드)에서 실행
    if "bot_thread" not in st.session_state:
        thread = threading.Thread(target=start_auto_monitoring, daemon=True)
        thread.start()
        st.session_state.bot_thread = True

st.title("NHN Cloud 백업 관리 대시보드 (RDS AUTO → OBS Export + Instance Image)")

# ===== Secrets =====
AUTH_URL = st.secrets["NHN_AUTH_URL"]
APP_KEY = st.secrets["NHN_RDS_APP_KEY"]
AUTH_ID = st.secrets["NHN_RDS_AUTH_ID"]
AUTH_SECRET = st.secrets["NHN_RDS_AUTH_SECRET"]

TENANT_ID_RDS = st.secrets["NHN_TENANT_ID_RDS"]
TENANT_ID_COMPUTE = st.secrets["NHN_TENANT_ID_COMPUTE"]
DB_GROUP_IDS = st.secrets["NHN_DB_GROUP_IDS"] # ["uuid-1", "uuid-2"]
USERNAME = st.secrets["NHN_USERNAME"]
PASSWORD = st.secrets["NHN_PASSWORD"]
CONTAINER = st.secrets.get("OBS_CONTAINER", "backup-db")

RDS_ENDPOINT = "https://kr1-rds-mysql.api.nhncloudservice.com"
COMPUTE_ENDPOINT = st.secrets.get("COMPUTE_ENDPOINT", "https://kr1-api-instance-infrastructure.nhncloudservice.com").rstrip("/")
TARGET_SERVER_NAMES = ["mw-n8n", "ssh-backup-billing-auto"]


def get_nhn_token():
    # secrets에서 설정된 COMPUTE용 TENANT_ID와 인증 정보를 사용합니다.
    return issue_token_v2(AUTH_URL, TENANT_ID_COMPUTE, USERNAME, PASSWORD)["token"]

def create_user_server(user_no, token):
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }
    
    try:
        # 1. 보안 그룹 조회
        sg_url = f"{COMPUTE_ENDPOINT.replace('instance', 'network')}/v2.0/security-groups?name=Test-User-{user_no}"
        sg_res = requests.get(sg_url, headers=headers).json()
        
        if not sg_res.get('security_groups'):
            st.error(f"❌ User {user_no}의 보안 그룹을 찾을 수 없습니다.")
            return

        sg_user = sg_res['security_groups'][0]['id']
        sg_list = [st.secrets["nhn_ids"]["SG_CO"], st.secrets["nhn_ids"]["SG_MANAGER"], sg_user]

        # 2. 서버 생성 내부 함수
        def _request_server(name, flavor, img, ip_suffix, sg_json_list):
            # [수정] 포트 생성 전 존재 여부 확인 로직 (안정성 강화)
            port_base_url = f"{COMPUTE_ENDPOINT.replace('instance', 'network')}/v2.0/ports"
            target_ip = f"10.0.0.{ip_suffix}"
            
            # 기존 포트 조회
            check_port = requests.get(f"{port_base_url}?fixed_ips=ip_address={target_ip}", headers=headers).json()
            
            if check_port.get('ports'):
                port_id = check_port['ports'][0]['id']
                st.info(f"ℹ️ {name}: 기존 포트 재사용 ({target_ip})")
            else:
                # 포트 새로 생성
                port_data = {
                    "port": {
                        "name": f"{name}-port",
                        "network_id": st.secrets["nhn_ids"]["NET_ID"],
                        "fixed_ips": [{"subnet_id": st.secrets["nhn_ids"]["SUB_ID"], "ip_address": target_ip}],
                        "security_groups": sg_json_list
                    }
                }
                port_res = requests.post(port_base_url, headers=headers, json=port_data).json()
                if 'port' not in port_res:
                    raise Exception(f"포트 생성 실패: {port_res}")
                port_id = port_res['port']['id']

            # 인스턴스 생성 (T_ID 참조 수정)
            server_url = f"{COMPUTE_ENDPOINT}/v2/{TENANT_ID_COMPUTE}/servers"
            server_data = {
                "server": {
                    "name": name,
                    "flavorRef": flavor,
                    "key_name": st.secrets["nhn_ids"]["KEY_NAME"],
                    "networks": [{"port": port_id}],
                    "block_device_mapping_v2": [{
                        "source_type": "image",
                        "uuid": img,
                        "boot_index": 0,
                        "destination_type": "volume",
                        "volume_type": "General SSD",
                        "volume_size": 500 if "cpu" in name else 100,
                        "delete_on_termination": True
                    }]
                }
            }
            return requests.post(server_url, headers=headers, json=server_data)

        # 3. CPU/WIN 생성 실행
        cpu_res = _request_server(f"test{user_no}@linux", st.secrets["nhn_ids"]["FLAVOR_CPU"], st.secrets["nhn_ids"]["CPU_IMG"], f"1{user_no}", sg_list)
        if cpu_res.status_code in [200, 202]:
            st.success(f"✅ Test {user_no} linux 생성 성공")
        else:
            st.error(f"❌ CPU 생성 실패: {cpu_res.text}")

        win_res = _request_server(f"test{user_no}@win", st.secrets["nhn_ids"]["FLAVOR_WIN"], st.secrets["nhn_ids"]["WIN_IMG"], user_no, sg_list)
        if win_res.status_code in [200, 202]:
            st.success(f"✅ Test {user_no} Window 생성 성공")

    except Exception as e:
        st.error(f"🔥 User {user_no} 처리 중 오류: {e}")

# ===== [핵심] RDS 전용 인증 헤더 생성 =====
def get_nhn_rds_headers():
    return {
        "Content-Type": "application/json",
        "X-TC-APP-KEY": APP_KEY,
        "X-TC-AUTHENTICATION-ID": AUTH_ID,
        "X-TC-AUTHENTICATION-SECRET": AUTH_SECRET
    }

# ===== RDS Functions =====
def rds_get_group_instances(group_id: str) -> list[str]:
    url = f"{RDS_ENDPOINT}/v3.0/db-instance-groups/{group_id}"
    headers = get_nhn_rds_headers()
    r = requests.get(url, headers=headers, timeout=30)
    data = r.json()
    
    if not data.get("header", {}).get("isSuccessful"):
        st.error(f"❌ 그룹 조회 실패 ({group_id}): {data.get('header', {}).get('resultMessage')}")
        return []

    # curl 결과에 맞춰 루트의 dbInstances 참조
    candidates = data.get("dbInstances", [])
    return [x["dbInstanceId"] for x in candidates if isinstance(x, dict) and x.get("dbInstanceId")]

def rds_list_backups(db_instance_id: str, page: int = 1, size: int = 100) -> dict:
    url = f"{RDS_ENDPOINT}/v3.0/backups"
    params = {"page": page, "size": size, "dbInstanceId": db_instance_id}
    headers = get_nhn_rds_headers()
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def rds_export_backup(backup_id: str, obs_tenant_id: str, username: str, password: str,
                      target_container: str, object_path: str) -> str:
    url = f"{RDS_ENDPOINT}/v3.0/backups/{backup_id}/export"
    payload = {
        "tenantId": obs_tenant_id,
        "username": username,
        "password": password,
        "targetContainer": target_container,
        "objectPath": object_path,
    }
    headers = get_nhn_rds_headers()
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    job_id = data.get("jobId") or data.get("body", {}).get("jobId")
    if not job_id:
        raise RuntimeError(f"Export 응답에 jobId가 없습니다: {data}")
    return job_id
def export_today_auto_backups(db_instance_id: str, today_yyyymmdd: str) -> list[dict]:
    page, size = 1, 100
    exports: list[dict] = []

    # 1. DB 인스턴스 상세 조회를 통해 '진짜 이름' 가져오기
    real_db_name = db_instance_id  # 조회 실패 시 대비용 기본값
    try:
        # 말씀하신 GET /v3.0/db-instances/{dbInstanceId} 호출
        detail_url = f"{RDS_ENDPOINT}/v3.0/db-instances/{db_instance_id}"
        headers = get_nhn_rds_headers()
        
        detail_res = requests.get(detail_url, headers=headers, timeout=15)
        if detail_res.status_code == 200:
            detail_data = detail_res.json()
            # 응답 본문에서 dbInstanceName 추출
            # NHN API 특성상 'dbInstance' 객체 안에 들어있을 수 있으므로 안전하게 접근합니다.
            db_info = detail_data.get("dbInstance") or detail_data
            real_db_name = db_info.get("dbInstanceName", db_instance_id)
    except Exception as e:
        st.warning(f"⚠️ {db_instance_id}의 이름을 조회하는 데 실패했습니다. ID를 대신 사용합니다: {e}")

    # 2. 백업 리스트 순회 및 Export
    while True:
        data = rds_list_backups(db_instance_id, page=page, size=size)
        backups = data.get("backups") or data.get("body", {}).get("backups", [])
        total = int(data.get("totalCounts") or data.get("body", {}).get("totalCounts", 0))
        
        if not backups:
            break

        for b in backups:
            b_time = b.get("createdYmdt")
            if not is_today_created(b_time, today_yyyymmdd):
                continue

            backup_id = b["backupId"]
            
            # 💡 [최종 파일명 결정] 년월일-진짜DB이름
            file_name = f"{today_yyyymmdd}-{real_db_name}"
            object_path = file_name 

            try:
                job_id = rds_export_backup(
                    backup_id=backup_id,
                    obs_tenant_id=TENANT_ID_RDS,
                    username=USERNAME,
                    password=PASSWORD,
                    target_container=CONTAINER,
                    object_path=object_path
                )
                exports.append({
                    "backupName": file_name,
                    "jobId": job_id,
                    "createdYmdt": b_time
                })
            except Exception as e:
                st.error(f"❌ Export 실패 ({file_name}): {e}")

        if page * size >= total:
            break
        page += 1

    return exports
def is_today_created(created_ymdt: str, today_yyyymmdd: str) -> bool:
    if not created_ymdt: return False
    try:
        ymd = created_ymdt.split('T')[0].replace("-", "")
        return ymd == today_yyyymmdd
    except: return False

# ===== Auth / Compute Functions =====
def issue_token_v2(auth_url: str, tenant_id: str, username: str, password: str) -> dict:
    url = f"{auth_url.rstrip('/')}/tokens"
    payload = {"auth": {"tenantId": tenant_id, "passwordCredentials": {"username": username, "password": password}}}
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return {"token": data["access"]["token"]["id"], "raw": data}

def get_obs_endpoint(catalog: list, tenant_id: str):
    for service in catalog:
        if isinstance(service, dict) and service.get('type') in ['object-store', 'swift']:
            for ep in service.get('endpoints', []):
                if ep.get('interface') == 'public': return ep.get('url')
    return f"https://kr1-api-object-storage.nhncloudservice.com/v1/AUTH_{tenant_id}"

def ensure_obs_container(obs_base: str, container: str, token: str):
    url = f"{obs_base}/{container}"
    requests.put(url, headers={"X-Auth-Token": token}, timeout=30)

def nova_list_servers_detail(compute_base: str, tenant_id: str, token: str) -> list[dict]:
    url = f"{compute_base}/v2/{tenant_id}/servers/detail"
    r = requests.get(url, headers={"X-Auth-Token": token}, timeout=30)
    return r.json().get("servers", [])

def cinder_upload_volume_to_image(compute_base: str, tenant_id: str, server_id: str, token: str, image_name: str):
    """
    서버의 루트 볼륨을 이미지 서비스(Glance)로 업로드합니다.
    사용자님께서 확인해주신 infrastructure 엔드포인트를 사용합니다.
    """
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    
    try:
        # [Step 1] 서버 상세 조회하여 연결된 볼륨 ID 추출
        server_url = f"{compute_base}/v2/{tenant_id}/servers/{server_id}"
        srv_res = requests.get(server_url, headers=headers, timeout=20)
        srv_res.raise_for_status()
        srv_data = srv_res.json().get("server", {})
        attached_volumes = srv_data.get("os-extended-volumes:volumes_attached", [])
        
        if not attached_volumes:
            return "ERROR: 연결된 볼륨 없음"

        volume_id = attached_volumes[0].get("id")
        
        # [Step 2] 확인된 인프라 엔드포인트 직접 지정
        volume_endpoint = "https://kr1-api-block-storage-infrastructure.nhncloudservice.com"
        action_url = f"{volume_endpoint}/v2/{tenant_id}/volumes/{volume_id}/action"
        
        # [Step 3] Payload 구성
        payload = {
            "os-volume_upload_image": {
                "image_name": image_name,
                "force": True, 
                "disk_format": "qcow2",
                "container_format": "bare",
                "visibility": "private"
            }
        }
        
        # [Step 4] POST 요청 실행
        r = requests.post(action_url, json=payload, headers=headers, timeout=60)
        
        if r.status_code in (200, 202):
            res_data = r.json().get("os-volume_upload_image", {})
            return res_data.get("image_id")
        else:
            return f"ERROR: {r.status_code} - {r.text}"
            
    except Exception as e:
        return f"ERROR: {str(e)}"

def nova_create_image(compute_base: str, tenant_id: str, server_id: str, token: str, image_name: str):
    """
    NHN Cloud Instance Snapshot API (U2 타입 전용)
    """
    url = f"{compute_base}/v2/{tenant_id}/servers/{server_id}/action"
    
    # 1. API 명세에 따른 Payload 구성
    payload = {
        "createImage": {
            "name": image_name,
            "metadata": {
                "created_by": "streamlit_backup_dashboard",
                "backup_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
    }
    
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }

    try:
        # 2. POST 요청 실행
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        
        # 202 Accepted 등의 성공 상태 코드 확인
        if r.status_code in (200, 202, 204):
            # 응답 본문 대신 Location 헤더에서 이미지 확인 URL 추출
            location = r.headers.get("Location")
            return location
        else:
            st.error(f"❌ 이미지 생성 실패 ({r.status_code}): {r.text}")
            return None
            
    except Exception as e:
        st.error(f"❌ 이미지 생성 중 예외 발생: {e}")
        return None


# 페이지 설정
st.set_page_config(layout="wide", page_title="Test Infra Manager")

# 1. 탭 메뉴 구성
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 GPU 모니터링", 
    "💰 정산 관리", 
    "🚀 서버 자동 생성", 
    "💾 통합 백업 관리"
])

# --- [탭 1: GPU 모니터링] ---
with tab1:
    st.header("실시간 GPU 상태")
    # 기존에 만드신 Flux 쿼리 및 차트 로직을 여기에 넣으세요.
    st.info("현재 V100/T4 인스턴스 자원 사용률을 표시합니다.")

# --- [탭 2: 정산 관리] ---
with tab2:
    st.header("사용자별 정산 현황")
    # 기존 app_v1.5.py의 정산 로직을 여기에 넣으세요.
    st.success("이번 달 예상 청구 비용을 계산합니다.")

# --- [탭 3: 서버 자동 생성] ---
# --- [탭 3: 서버 자동 생성] ---
with tab3:
    st.header("🚀 NHN Cloud 서버 일괄 생성")
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        user_input = st.text_input("생성할 유저 번호 (쉼표 구분)", "31, 32")
    #with col2:
        # volume_size는 현재 create_user_server 내부 로직에 고정되어 있으나 향후 확장을 위해 배치
    #    vol_size = st.number_input("기본 볼륨 크기 (GB)", value=500) 

    if st.button("🚀 서버 생성 프로세스 시작"):
        try:
            with st.spinner("🔑 NHN Cloud 인증 및 토큰 발급 중..."):
                # 공통 함수를 통해 토큰 발급
                token = get_nhn_token()
            
            user_list = [u.strip() for u in user_input.split(",")]
            
            # 생성 진행 상황을 보여주기 위한 프로그레스 바 (선택 사항)
            for user_no in user_list:
                with st.status(f"🛠️ User {user_no} 인프라 구성 중...", expanded=True) as status:
                    create_user_server(user_no, token)
                    status.update(label=f"✅ User {user_no} 구성 완료", state="complete")
                    
            st.balloons()
            st.success("🎉 모든 유저의 서버 생성 요청이 완료되었습니다.")
                
        except Exception as e:
            st.error(f"🚨 서버 생성 중단: {e}")

with tab4:
    st.header("📦 일일 통합 백업 시스템")
    st.info("RDS 자동 백업을 OBS로 Export하고, 주요 Compute 인스턴스의 이미지를 생성합니다.")
    
    # 작업 실행 버튼
    if st.button("🚀 오늘 AUTO 백업 Export + 인스턴스 이미지 생성"):
        today = datetime.now().strftime("%Y%m%d")
        try:
            # 1) OBS 환경 준비
            with st.spinner("OBS 환경 준비 중..."):
                auth_res = issue_token_v2(AUTH_URL, TENANT_ID_RDS, USERNAME, PASSWORD)
                obs_token = auth_res["token"]
                obs_base = get_obs_endpoint(auth_res["raw"].get("access", {}).get("serviceCatalog", []), TENANT_ID_RDS)
                ensure_obs_container(obs_base, CONTAINER, obs_token)
            
            # 2) RDS 그룹 처리
            st.subheader("🔹 RDS Backup Export")
            all_exports = []
            for group_id in DB_GROUP_IDS:
                with st.expander(f"📁 DB Group: {group_id} 상세 보기", expanded=True):
                    real_ids = rds_get_group_instances(group_id)
                    for inst_id in real_ids:
                        st.write(f"🔍 인스턴스 확인: {inst_id}")
                        exports = export_today_auto_backups(inst_id, today)
                        if exports:
                            for e in exports:
                                st.success(f"✅ {e['backupName']} 요청 완료 (Job: {e['jobId']})")
                            all_exports.extend(exports)
                        else:
                            st.text("  - 오늘 백업 없음")
            
            # 3) Compute 인스턴스 이미지 생성
            st.divider()
            st.subheader("📸 Compute 인스턴스 이미지 생성")
            
            with st.spinner("Compute 토큰 발급 및 서버 조회 중..."):
                t_cmp = issue_token_v2(AUTH_URL, TENANT_ID_COMPUTE, USERNAME, PASSWORD)
                token_cmp = t_cmp["token"]
                servers = nova_list_servers_detail(COMPUTE_ENDPOINT, TENANT_ID_COMPUTE, token_cmp)
            
            for target_name in TARGET_SERVER_NAMES:
                target_server = next((s for s in servers if s.get("name") == target_name), None)
                image_name = f"{today}.{target_name}"

                if not target_server:
                    st.warning(f"⚠️ 서버 찾음 실패: {target_name}")
                    continue

                server_id = target_server["id"]
                status = target_server.get("status", "UNKNOWN")
                
                with st.spinner(f"📸 {target_name} 이미지 생성 중..."):
                    result = cinder_upload_volume_to_image(
                        COMPUTE_ENDPOINT, TENANT_ID_COMPUTE, server_id, token_cmp, image_name
                    )

                    if isinstance(result, str) and "ERROR" in result:
                        st.error(f"❌ {target_name} 실패: {result}")
                    else:
                        st.success(f"✅ {target_name} 완료! (ID: {result})")

            st.balloons()
            st.success("🎉 모든 백업 작업이 완료되었습니다!")

        except Exception as e:
            st.error(f"🚨 작업 중단: {e}")








