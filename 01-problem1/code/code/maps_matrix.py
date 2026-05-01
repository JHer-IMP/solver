import pandas as pd
import requests
import time
import re
import numpy as np

# ==================== 配置区域 ====================
API_KEY = "399a6f4d89b91c235696f093aa2ae506"         # 高德API密钥
INPUT_FILE = "destination.xlsx"                      # 输入文件，必须包含“地点”列
PLACE_COL = "地点"                                   # 地点列名
ORIGIN = "南通市崇川区"                              # 起点（也会加入矩阵）
OUTPUT_DIST = "distance_matrix.xlsx"                 # 距离矩阵
OUTPUT_DURA = "duration_matrix.xlsx"                 # 时间矩阵（分钟）
# ================================================

def geocode(address):
    """地理编码：地址 -> 'lng,lat'"""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {"key": API_KEY, "address": address, "output": "JSON"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data["status"] == "1" and data["geocodes"]:
            return data["geocodes"][0]["location"]
        else:
            print(f"      [地理编码] {address[:20]}... 失败: {data.get('info', '未知错误')}")
            return None
    except Exception as e:
        print(f"      [地理编码] 网络错误: {e}")
        return None

def get_distance_duration(origin_loc, dest_loc):
    """驾车距离(km)和时间(分钟)，失败返回 None,None"""
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "key": API_KEY,
        "origin": origin_loc,
        "destination": dest_loc,
        "extensions": "base",
        "output": "JSON"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data["status"] == "1" and data["route"]["paths"]:
            path = data["route"]["paths"][0]
            dist_km = round(float(path["distance"]) / 1000, 2)
            dura_min = round(float(path["duration"]) / 60, 2)
            return dist_km, dura_min
        else:
            print(f"      [路径] 失败: {data.get('info', '未知错误')}")
            return None, None
    except Exception as e:
        print(f"      [路径] 网络错误: {e}")
        return None, None

def clean_address(address):
    """去除地址中的括号说明"""
    address = re.sub(r'（[^）]*）', '', address)
    address = re.sub(r'\([^)]*\)', '', address)
    return ' '.join(address.split())

def main():
    # ========== 1. 读取地点并加入起点 ==========
    print(f"[1/5] 读取文件: {INPUT_FILE}")
    df = pd.read_excel(INPUT_FILE)
    if PLACE_COL not in df.columns:
        raise ValueError(f"文件中找不到列 '{PLACE_COL}'，实际列名: {list(df.columns)}")
    
    # 提取地点列表（去重、去空）
    places = df[PLACE_COL].dropna().astype(str).str.strip().tolist()
    places = [clean_address(p) for p in places if p]
    # 去重保留顺序
    seen = set()
    unique_places = []
    for p in places:
        if p not in seen:
            seen.add(p)
            unique_places.append(p)
    places = unique_places
    
    # 添加起点（放在最前面，并保证唯一）
    origin_clean = clean_address(ORIGIN)
    if origin_clean in seen:
        print(f"      起点 '{origin_clean}' 已存在，将移到列表首位")
        places.insert(0, places.pop(places.index(origin_clean)))
    else:
        places.insert(0, origin_clean)
    
    n = len(places)
    print(f"      共 {n} 个地点（含起点）:")
    for i, p in enumerate(places):
        print(f"        [{i+1}] {p}")
    
    # ========== 2. 对所有地点进行地理编码 ==========
    print(f"\n[2/5] 地理编码所有地点...")
    locs = []  # 保存经纬度字符串
    valid_idx = []  # 编码成功的索引
    for i, place in enumerate(places):
        print(f"  ({i+1}/{n}) {place[:40]} ...", end=" ")
        loc = geocode(place)
        if loc:
            print(f"-> {loc}")
            locs.append(loc)
            valid_idx.append(i)
        else:
            print("-> 失败")
            locs.append(None)
        time.sleep(0.1)  # 控制QPS
    
    success_geo = sum(1 for l in locs if l is not None)
    print(f"      地理编码成功: {success_geo}/{n}")
    if success_geo < 2:
        print("❌ 成功编码的地点少于2个，无法生成矩阵")
        return
    
    # ========== 3. 初始化矩阵（用地点名称作为索引和列名）==========
    dist_mat = pd.DataFrame(np.nan, index=places, columns=places)
    dura_mat = pd.DataFrame(np.nan, index=places, columns=places)
    
    # 对角线全为0
    for i in range(n):
        dist_mat.iat[i, i] = 0.0
        dura_mat.iat[i, i] = 0.0
    
    # ========== 4. 两两计算距离和时长 ==========
    total_pairs = n * (n - 1) // 2
    print(f"\n[3/5] 开始计算 {total_pairs} 对路径...")
    pair_count = 0
    for i in range(n):
        if locs[i] is None:
            continue
        for j in range(i + 1, n):
            if locs[j] is None:
                continue
            pair_count += 1
            print(f"  [{pair_count}/{total_pairs}] {places[i]} ↔ {places[j]} ...", end=" ")
            dist, dura = get_distance_duration(locs[i], locs[j])
            if dist is not None:
                print(f"距离:{dist}km 时间:{dura}min")
                dist_mat.iat[i, j] = dist
                dist_mat.iat[j, i] = dist
                dura_mat.iat[i, j] = dura
                dura_mat.iat[j, i] = dura
            else:
                print("失败")
            time.sleep(0.1)  # 控制QPS，确保不超过每秒30次
    
    # ========== 5. 保存矩阵 ==========
    print(f"\n[4/5] 保存距离矩阵: {OUTPUT_DIST}")
    dist_mat.to_excel(OUTPUT_DIST, index=True)
    print(f"[5/5] 保存时间矩阵: {OUTPUT_DURA}")
    dura_mat.to_excel(OUTPUT_DURA, index=True)
    
    # ========== 统计 ==========
    valid_pairs = dist_mat.notna().sum().sum() // 2  # 成功对数
    failed_pairs = total_pairs - valid_pairs
    print(f"\n{'='*50}")
    print(f"完成! 总地点数: {n}")
    print(f"矩阵保存为: {OUTPUT_DIST} 和 {OUTPUT_DURA}")
    print(f"成功路径对: {valid_pairs}/{total_pairs}, 失败: {failed_pairs}")
    if failed_pairs > 0:
        print("失败的点对可在矩阵中查看到空值(NaN)")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()