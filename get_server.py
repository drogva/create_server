# get2.py — 모든 리전/모든 VPC 서버 + 사설/공인 IP 수집 → file_sd JSON 저장
import os, time, hmac, base64, hashlib, requests, json, re, copy, ipaddress
from urllib.parse import urlencode

BASE = "https://ncloud.apigw.ntruss.com"
AK = os.getenv("NCP_ACCESS_KEY")
SK = os.getenv("NCP_SECRET_KEY")

# --- 공통 서명/요청 ---
def _sign(method, uri, query, ts):
    sign_uri = f"{uri}?{query}" if query else uri
    msg = f"{method} {sign_uri}\n{ts}\n{AK}"
    return base64.b64encode(hmac.new(SK.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def ncp_get(uri, params=None):
    p = {"responseFormatType": "json"}
    if params:
        p.update(params)
    q  = urlencode(p, doseq=True)
    ts = str(int(time.time()*1000))
    sig = _sign("GET", uri, q, ts)
    headers = {
        "x-ncp-apigw-timestamp": ts,
        "x-ncp-iam-access-key": AK,
        "x-ncp-apigw-signature-v2": sig,
    }
    url = f"{BASE}{uri}?{q}"
    r = requests.get(url, headers=headers, timeout=25)
    if not r.ok:
        print("URL:", url)
        print("STATUS:", r.status_code)
        print("BODY:", r.text[:2000])
        r.raise_for_status()
    return r.json()

# --- 메타 조회 ---
def get_region_list():
    obj = ncp_get("/vserver/v2/getRegionList")
    return (obj.get("getRegionListResponse") or {}).get("regionList") or []

def get_zone_list(regionCode):
    obj = ncp_get("/vserver/v2/getZoneList", {"regionCode": regionCode})
    return (obj.get("getZoneListResponse") or {}).get("zoneList") or []

# --- 페이징 유틸 ---
def _paged_get_servers(extra_params, page_size=1000):
    page, out = 1, []
    while True:
        params = {
            "pageNo": page, "pageSize": page_size,
            "sortedBy": "serverInstanceNo", "sortingOrder": "ASC",
        }
        params.update(extra_params or {})
        obj = ncp_get("/vserver/v2/getServerInstanceList", params)
        data  = (obj.get("getServerInstanceListResponse") or {})
        items = data.get("serverInstanceList") or []
        out.extend(items)
        total = int(data.get("totalRows", len(out)))
        if len(out) >= total or not items:
            break
        page += 1
    return out

def _paged_get_public_ips(extra_params, page_size=1000):
    page, out = 1, []
    while True:
        params = {
            "pageNo": page, "pageSize": page_size,
            "sortedBy": "publicIpInstanceNo", "sortingOrder": "ASC",
        }
        params.update(extra_params or {})
        obj = ncp_get("/vserver/v2/getPublicIpInstanceList", params)
        data  = (obj.get("getPublicIpInstanceListResponse") or {})
        items = data.get("publicIpInstanceList") or []
        out.extend(items)
        total = int(data.get("totalRows", len(out)))
        if len(out) >= total or not items:
            break
        page += 1
    return out

# --- 유틸 ---
def first_private_ip(server):
    def is_private(ip):
        try:
            return ip and ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    ip = server.get("privateIp")
    if is_private(ip):
        return ip

    for nic in (server.get("networkInterfaceList") or []):
        pip = nic.get("privateIp") or nic.get("ip")
        if is_private(pip):
            return pip
    return None

def get_nic_map_by_region(regionCode, page_size=1000):
    page, out = 1, []
    while True:
        obj = ncp_get("/vserver/v2/getNetworkInterfaceList", {
            "regionCode": regionCode,
            "pageNo": page,
            "pageSize": page_size,
            "sortedBy": "networkInterfaceNo",
            "sortingOrder": "ASC",
        })
        data  = (obj.get("getNetworkInterfaceListResponse") or {})
        items = data.get("networkInterfaceList") or []
        out.extend(items)
        total = int(data.get("totalRows", len(out)))
        if len(out) >= total or not items:
            break
        page += 1

    def is_private(ip):
        try:
            return ip and ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    nic_map = {}
    for nic in out:
        sin = nic.get("serverInstanceNo") or nic.get("instanceNo")
        ip  = nic.get("privateIp") or nic.get("ip")
        if not sin or not is_private(ip):
            continue
        nic_map.setdefault(sin, []).append(ip)
    return nic_map

def public_ip_map(pub_list):
    m = {}
    for p in pub_list:
        sin = p.get("serverInstanceNo")
        ip  = p.get("publicIp")
        if not sin or not ip:
            continue
        m.setdefault(sin, []).append(ip)
    return m

def get_servers_by_region(regionCode, page_size=1000):
    page, out = 1, []
    while True:
        params = {
            "regionCode": regionCode,
            "pageNo": page,
            "pageSize": page_size,
            "sortedBy": "serverInstanceNo",
            "sortingOrder": "ASC",
        }
        obj = ncp_get("/vserver/v2/getServerInstanceList", params)
        data  = (obj.get("getServerInstanceListResponse") or {})
        items = data.get("serverInstanceList") or []
        out.extend(items)
        total = int(data.get("totalRows", len(out)))
        if len(out) >= total or not items:
            break
        page += 1
    return out

# --- 이름/그룹/선택 ---
USER_PAT = re.compile(r"^(user\d{2})-(cpu|gpu|win)$")

def pick_best_ip(row):
    if row.get("privateIp"):
        return row["privateIp"]
    pubs = (row.get("publicIps") or "").split(",")
    return pubs[0] if pubs and pubs[0] else None

def collect_all_regions(vpc_filter=None):
    if isinstance(vpc_filter, (str, int)):
        vpc_filter = {str(vpc_filter)}
    elif isinstance(vpc_filter, (list, set, tuple)):
        vpc_filter = {str(x) for x in vpc_filter}
    else:
        vpc_filter = None

    rows = []
    regions = get_region_list()
    for reg in regions:
        regionCode = reg.get("regionCode")
        regionName = reg.get("regionName")
        if not regionCode:
            continue

        nic_map = get_nic_map_by_region(regionCode)
        servers = get_servers_by_region(regionCode)
        pubs    = _paged_get_public_ips({"regionCode": regionCode})
        pmap    = public_ip_map(pubs)

        for s in servers:
            vpc_no = str(s.get("vpcNo") or "")
            if vpc_filter and vpc_no not in vpc_filter:
                continue

            priv = first_private_ip(s)
            if not priv:
                sin = s.get("serverInstanceNo") or s.get("instanceNo")
                cand = nic_map.get(sin) or []
                if cand:
                    priv = cand[0]

            rows.append({
                "regionCode": regionCode,
                "regionName": regionName,
                "zoneNo": s.get("zoneNo"),
                "zoneCode": s.get("zoneCode"),
                "zoneName": s.get("zoneName"),
                "vpcNo": vpc_no,
                "serverInstanceNo": s.get("serverInstanceNo"),
                "serverName": s.get("serverName"),
                "serverInstanceType": (s.get("serverInstanceType") or {}).get("code"),
                "statusCode": (s.get("serverInstanceStatus") or {}).get("code"),
                "privateIp": priv,
                "publicIps": ",".join(pmap.get(s.get("serverInstanceNo"), [])),
                "created": s.get("createDate"),
            })
    return rows

def build_prom_lists(rows):
    grouped = {}
    for r in rows:
        name = r.get("serverName") or ""
        m = USER_PAT.match(name)
        if not m:
            continue
        user_key, role = m.group(1), m.group(2)
        grouped.setdefault(user_key, {}).setdefault(role, []).append(r)

    def to_triplet(row):
        return [row["serverName"], pick_best_ip(row), row["serverInstanceNo"]]

    cpu_prom_list, gpu_prom_list = [], []

    for user_key, role_map in grouped.items():
        if "cpu" in role_map:
            cpu_row = role_map["cpu"][0]
            entry = {"cpu": to_triplet(cpu_row)}
            if "win" in role_map:
                entry["win"] = to_triplet(role_map["win"][0])
            cpu_prom_list.append(entry)

        if "gpu" in role_map:
            gpu_row = role_map["gpu"][0]
            entry = {"gpu": to_triplet(gpu_row)}
            if "win" in role_map:
                entry["win"] = to_triplet(role_map["win"][0])
            gpu_prom_list.append(entry)

    return cpu_prom_list, gpu_prom_list

def write_file_sd_json(format_path, cpu_prom_list, gpu_prom_list, cpu_json_path, gpu_json_path):
    with open(format_path, encoding="utf-8") as f:
        user_format = json.load(f)

    def add_target(obj_list, ip, port, job, inst_type, uniq, iid):
        if not ip:
            return
        x = copy.deepcopy(user_format)
        # format.json 은 최소 ["<placeholder>"] 형태의 targets 리스트가 있다고 가정
        if "targets" not in x or not isinstance(x["targets"], list) or not x["targets"]:
            x["targets"] = [""]
        x["targets"][0] = f"{ip}:{port}"
        x["labels"]["job"] = job            # (주의) 환경에 따라 'windows_exporter' vs 'window_exporter'
        x["labels"]["server_type"] = inst_type
        x["labels"]["hostname"] = uniq
        x["labels"]["server_name"] = uniq
        x["labels"]["server_id"] = iid
        obj_list.append(x)

    # CPU
    cpu_json = []
    for d in cpu_prom_list:
        uniq, ip, iid = d["cpu"]
        add_target(cpu_json, ip, "9100", "node_exporter", "CPU", uniq, iid)
        if "win" in d:
            wuniq, wip, wiid = d["win"]
            add_target(cpu_json, wip, "9182", "window_exporter", "CPU", wuniq, wiid)  # 필요 시 windows_exporter 로 변경

    with open(cpu_json_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(cpu_json, ensure_ascii=False, indent=4))

    # GPU
    gpu_json = []
    for d in gpu_prom_list:
        uniq, ip, iid = d["gpu"]
        add_target(gpu_json, ip, "9100", "node_exporter", "GPU", uniq, iid)
        if "win" in d:
            wuniq, wip, wiid = d["win"]
            add_target(gpu_json, wip, "9182", "window_exporter", "GPU", wuniq, wiid)
        add_target(gpu_json, ip, "9401", "dcgm_exporter", "GPU", uniq, iid)

    with open(gpu_json_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(gpu_json, ensure_ascii=False, indent=4))

# ---- 실행 예시 ----
if __name__ == "__main__":
    VPC_FILTER = os.environ.get("117758")  # "12345,67890" 형태 지원
    if VPC_FILTER:
        VPC_FILTER = [v.strip() for v in VPC_FILTER.split(",") if v.strip()]

    rows = collect_all_regions(vpc_filter=VPC_FILTER)
    cpu_prom_list, gpu_prom_list = build_prom_lists(rows)
    write_file_sd_json(
        format_path="format.json",
        cpu_prom_list=cpu_prom_list,
        gpu_prom_list=gpu_prom_list,
        cpu_json_path="cpu_nodes.json",
        gpu_json_path="gpu_nodes.json",
    )
    print(f"CPU targets: {len(cpu_prom_list)}, GPU targets: {len(gpu_prom_list)}")


