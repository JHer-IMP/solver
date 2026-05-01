#399a6f4d89b91c235696f093aa2ae506
import pandas as pd
import requests
import time
import re

# ==================== 配置区域 ====================
ORIGIN = "南通市崇川区"
INPUT_FILE = "destination.xlsx"
OUTPUT_FILE = "destination_with_distance.xlsx"
API_KEY = "399a6f4d89b91c235696f093aa2ae506"
# ================================================

def geocode(address):
    """地理编码：将中文地址转换为经纬度坐标"""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": API_KEY,
        "address": address,
        "output": "JSON"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data["status"] == "1" and data["geocodes"]:
            location = data["geocodes"][0]["location"]
            return location
        else:
            print(f"    解析失败: {data.get('info', '未知错误')}")
            return None
    except Exception as e:
        print(f"    网络错误: {e}")
        return None

def measure_distance(origin_loc, destination_loc):
    """距离测量：获取两点之间的驾车距离（米）"""
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "key": API_KEY,
        "origin": origin_loc,
        "destination": destination_loc,
        "extensions": "base",
        "output": "JSON"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data["status"] == "1" and data["route"]["paths"]:
            distance_m = float(data["route"]["paths"][0]["distance"])
            return round(distance_m / 1000, 2)
        else:
            print(f"    路径规划失败: {data.get('info', '未知错误')}")
            return None
    except Exception as e:
        print(f"    网络错误: {e}")
        return None

def clean_address(address):
    """清理地址中的括号说明"""
    address = re.sub(r'（[^）]*）', '', address)
    address = re.sub(r'\([^)]*\)', '', address)
    address = ' '.join(address.split())
    return address

def read_file_auto(filename):
    """自动识别文件格式读取"""
    try:
        df = pd.read_excel(filename)
        print(f"✓ 以 Excel 格式读取成功")
        return df
    except:
        pass
    
    for enc in ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']:
        try:
            df = pd.read_excel(filename, encoding=enc)
            print(f"✓ 以 Excel 格式读取成功 (编码: {enc})")
            return df
        except:
            continue
    
    raise ValueError(f"无法读取文件 {filename}")

def main():
    # 1. 读取文件
    print(f"[1/4] 读取文件: {INPUT_FILE}")
    df = read_file_auto(INPUT_FILE)
    
    # 确认目的地列
    dest_col = 'destination' if 'destination' in df.columns else df.columns[0]
    print(f"      使用列: '{dest_col}'")
    print(f"      共 {len(df)} 行")
    
    # 2. 解析起点坐标
    print(f"\n[2/4] 解析起点坐标: {ORIGIN}")
    origin_loc = geocode(ORIGIN)
    if not origin_loc:
        print("❌ 起点地址解析失败，程序终止")
        return
    print(f"      起点坐标: {origin_loc}")
    
    # 3. 查询所有距离
    print(f"\n[3/4] 开始查询距离...")
    distances = []
    success_count = 0
    fail_count = 0
    
    for idx, row in df.iterrows():
        dest = str(row[dest_col]).strip()
        if not dest or dest.lower() == 'nan':
            print(f"  [{idx+1}/{len(df)}] 跳过空行")
            distances.append(None)
            fail_count += 1
            continue
        
        # 清理地址
        clean_dest = clean_address(dest)
        
        print(f"  [{idx+1}/{len(df)}] {dest[:50]} ...", end=" ", flush=True)
        
        # 地理编码
        dest_loc = geocode(clean_dest)
        if not dest_loc:
            distances.append(None)
            fail_count += 1
            continue
        
        # 距离测量
        distance = measure_distance(origin_loc, dest_loc)
        if distance is not None:
            print(f"-> {distance} km")
            distances.append(distance)
            success_count += 1
        else:
            print("-> 失败")
            distances.append(None)
            fail_count += 1
        
        # QPS控制：高德限制每秒30次
        time.sleep(0.1)
    
    # 4. 保存结果
    print(f"\n[4/4] 写入结果到: {OUTPUT_FILE}")
    df["distance_km"] = distances
    df.to_excel(OUTPUT_FILE, index=False)
    
    # 统计
    print(f"\n{'='*50}")
    print(f"完成! 成功: {success_count}, 失败: {fail_count}")
    print(f"成功率: {success_count/(success_count+fail_count)*100:.1f}%")
    
    # 显示失败地址
    if fail_count > 0:
        print(f"\n失败地址列表:")
        failed = df[pd.isna(df['distance_km'])]
        for idx, row in failed.iterrows():
            print(f"  [{idx+1}] {str(row[dest_col])[:60]}")
    
    print(f"\n结果已保存至: {OUTPUT_FILE}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()