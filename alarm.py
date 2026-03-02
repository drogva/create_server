
import os
import json
import requests
import mysql.connector
from dotenv import load_dotenv

# 1. 환경 변수 로드 (가장 먼저 실행)
load_dotenv()

# 2. 설정 정보 세팅 (os.getenv 활용)
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': os.getenv("DB_PASSWORD"),
    'database': 'server_info'
}

NHN_AUTH = {
    "auth": {
        "tenantId": os.getenv("NHN_TENANT_ID"),
        "passwordCredentials": {
            "username": os.getenv("NHN_USERNAME"),
            "password": os.getenv("NHN_PASSWORD")
        }
    }
}

# 카카오 키 정보
KAKAO_KEY = os.getenv("KAKAO_REST_KEY")
KAKAO_RT = os.getenv("KAKAO_REFRESH_TOKEN")

# 3. 카카오톡 관련 함수
def get_kakao_at():
    url = "https://kauth.kakao.com/oauth/token"

    # 1. 데이터를 확실하게 정의 (앞뒤 공백 제거 포함)
    payload = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_KEY.strip(),
        "refresh_token": KAKAO_RT.strip()
    }

    # 2. 카카오가 요구하는 헤더 명시
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
    }

    try:
        # data=payload 로 보내면 requests가 자동으로 form-encoding 해줍니다.
        res = requests.post(url, data=payload, headers=headers)
        result = res.json()

        if 'access_token' not in result:
            # 실패 시 이유를 정확히 찍어줍니다 (예: KOE010, KOE322 등)
            print(f"❌ 카톡 토큰 갱신 실패 사유: {result}")
            return None

        return result.get('access_token')
    except Exception as e:
        print(f"🔥 네트워크 오류 발생: {e}")
        return None

def send_kakao(text):
    at = get_kakao_at()
    if not at:
        # 이미 get_kakao_at에서 에러 로그를 찍으므로 여기서는 리턴만 합니다.
        return

    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    payload = {
        'template_object': json.dumps({
            "object_type": "text",
            "text": text,
            "link": {"web_url": "http://localhost"}
        })
    }

    try:
        res = requests.post(url, headers={"Authorization": f"Bearer {at}"}, data=payload)
        # 성공/실패 여부를 확인하기 위해 로그 출력
        print(f"📡 카톡 전송 결과: {res.json()}")
    except Exception as e:
        print(f"🔥 카톡 전송 중 오류 발생: {e}")


# 4. 모니터링 메인 로직
def monitor():
    print(f"🚀 [모니터링] NHN Cloud 서버 상태 체크 시작...")

    # NHN 토큰 발행
    auth_url = "https://api-identity-infrastructure.nhncloudservice.com/v2.0/tokens"
    try:
        token_res = requests.post(auth_url, json=NHN_AUTH)
        token = token_res.json()['access']['token']['id']
    except Exception as e:
        return print(f"❌ NHN 인증 실패: {e}")

    # 서버 리스트 조회
    server_url = f"https://kr1-api-instance-infrastructure.nhncloudservice.com/v2/{NHN_AUTH['auth']['tenantId']}/servers/detail"
    current_servers = requests.get(server_url, headers={"X-Auth-Token": token}).json().get('servers', [])

    # DB 연결 및 상태 비교
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    changes = []

    for s in current_servers:
        s_id, s_name, s_status = s['id'], s['name'], s['status']
        cursor.execute("SELECT status FROM server_status WHERE server_id = %s", (s_id,))
        row = cursor.fetchone()

        if row:
            if row['status'] != s_status:
                changes.append(f"🔄 {s_name}: {row['status']} -> {s_status}")
                cursor.execute("UPDATE server_status SET status=%s, server_name=%s WHERE server_id=%s", (s_status, s_name, s_id))
        else:
            changes.append(f"🆕 {s_name}: {s_status}")
            cursor.execute("INSERT INTO server_status (server_id, server_name, status) VALUES (%s, %s, %s)", (s_id, s_name, s_status))

    conn.commit()
    conn.close()

    # 리포트 생성
    report = [f"📊 서버 {len(current_servers)}대 모니터링 중"]
    if changes:
        report.append("\n🔍 변동 사항:")
        report.extend(changes[:15])
        if len(changes) > 15:
            report.append(f"...외 {len(changes)-15}건 더 있음")
    else:
        report.append("\n✅ 변동 사항 없음")

    final_text = "\n".join(report)
    print(final_text)
    send_kakao(final_text)

# 5. 실행
if __name__ == "__main__":
    monitor()
