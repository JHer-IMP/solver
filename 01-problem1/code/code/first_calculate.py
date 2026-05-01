import pandas as pd
import numpy as np
import re
from datetime import datetime

# ==================== 配置 ====================
TASK_FILE = "排货信息表.xlsx"
DISTANCE_FILE = "destination_with_distance.xlsx"  # 支持 .csv 和 .xlsx 格式
ORIGIN = "南通市崇川区"
# ==============================================

class Vehicle:
    """车辆成本参数"""
    def __init__(self, name, annual_insurance, annual_inspection, 
                 road_transport_inspection, fuel_cost_per_km, toll_per_km,
                 daily_labor, monthly_violation, monthly_tire, monthly_maintenance):
        self.name = name
        self.annual_insurance = annual_insurance
        self.annual_inspection = annual_inspection
        self.road_transport_inspection = road_transport_inspection
        self.fuel_cost_per_km = fuel_cost_per_km
        self.toll_per_km = toll_per_km
        self.daily_labor = daily_labor
        self.monthly_violation = monthly_violation
        self.monthly_tire = monthly_tire
        self.monthly_maintenance = monthly_maintenance
    
    def daily_fixed_cost(self):
        """每日固定成本"""
        daily_insurance = self.annual_insurance / 365
        daily_inspection = (self.annual_inspection + self.road_transport_inspection) / 365
        daily_violation = self.monthly_violation / 30
        daily_tire = self.monthly_tire / 30
        daily_maintenance = self.monthly_maintenance / 30
        return (daily_insurance + daily_inspection + daily_violation + 
                daily_tire + daily_maintenance + self.daily_labor)


# 定义三种车型
VEHICLES = {
    '4.2': Vehicle('4.2米', 11506, 550, 1100, 1.1, 0.6, 600, 5000, 1800, 7000),
    '7.6': Vehicle('7.6米', 16050, 650, 1100, 1.5, 0.9, 600, 5000, 3000, 8000),
    '9.6': Vehicle('9.6米', 16286, 650, 1100, 1.9, 1.1, 600, 5000, 3000, 8000),
}


def parse_vehicle(vehicle_str):
    """解析车型字符串 -> '4.2', '7.6', '9.6'"""
    s = str(vehicle_str)
    if '4.2' in s:
        return '4.2'
    elif '7.6' in s:
        return '7.6'
    elif '9.6' in s:
        return '9.6'
    return None


def parse_count(count_val):
    """解析车辆数目，默认1"""
    if pd.isna(count_val) or str(count_val) == '1900-01-01 00:00:00':
        return 1
    try:
        return int(float(count_val))
    except:
        return 1


def parse_date(date_val):
    """解析日期"""
    if pd.isna(date_val) or str(date_val) == '1900-01-01 00:00:00':
        return None
    try:
        return pd.to_datetime(date_val)
    except:
        return None


def load_tasks(excel_file):
    """从Excel读取任务，提取必要字段"""
    print(f"[1/4] 读取排货信息表: {excel_file}")
    xl = pd.ExcelFile(excel_file)
    all_rows = []
    
    for sheet_name in xl.sheet_names:
        print(f"      读取工作表: {sheet_name}")
        # 关键修复：使用 header=2（第3行作为表头）
        df = pd.read_excel(excel_file, sheet_name=sheet_name, header=2)
        
        # 列名清理：去掉前后空格并转换为标准格式
        df.columns = [col.strip() if isinstance(col, str) else str(col) for col in df.columns]
        
        print(f"      找到列名: {list(df.columns)[:10]}...")
        
        # 只保留必要列，使用灵活的列名匹配
        vehicle_col = next((c for c in df.columns if '车型' in c), None)
        count_col = next((c for c in df.columns if '车辆数目' in c), None)
        pickup_col = next((c for c in df.columns if '实际提货日期' in c), None)
        delivery_col = next((c for c in df.columns if '实际到货日期' in c), None)
        destination_col = next((c for c in df.columns if '收货方地址' in c), None)
        
        if not all([vehicle_col, pickup_col, delivery_col, destination_col]):
            print(f"      ⚠️  缺少必要列，跳过此工作表")
            continue
        
        # 提取行
        for idx, row in df.iterrows():
            vehicle_type = parse_vehicle(row.get(vehicle_col, ''))
            pickup_date = parse_date(row.get(pickup_col))
            delivery_date = parse_date(row.get(delivery_col))
            destination = str(row.get(destination_col, '')).strip()
            
            if not vehicle_type or not destination or destination == 'nan':
                continue
            if not pickup_date or not delivery_date:
                continue
            
            days = max((delivery_date - pickup_date).days, 1)
            count = parse_count(row.get(count_col, 1) if count_col else 1)
            
            all_rows.append({
                'vehicle': vehicle_type,
                'count': count,
                'pickup': pickup_date,
                'delivery': delivery_date,
                'days': days,
                'destination': destination,
                'sheet': sheet_name
            })
    
    df = pd.DataFrame(all_rows)
    print(f"      共提取 {len(df)} 条有效运输任务\n")
    return df


def load_distances(distance_file):
    """加载距离数据（支持csv和xlsx格式，无表头）"""
    print(f"[2/4] 加载距离文件: {distance_file}")
    
    try:
        # 根据文件扩展名选择读取方式
        if distance_file.endswith('.csv'):
            df = pd.read_csv(distance_file, header=None, encoding='utf-8')
        elif distance_file.endswith('.xlsx') or distance_file.endswith('.xls'):
            df = pd.read_excel(distance_file, header=None)
        else:
            raise ValueError(f"不支持的文件格式: {distance_file}")
        
        # 手动命名列
        df.columns = ['destination', 'distance_km']
        
        print(f"      列名: {list(df.columns)}")
        print(f"      共 {len(df)} 行")
        if len(df) > 0:
            print(f"      前3行预览:")
            for i in range(min(3, len(df))):
                print(f"        [{i}] {str(df.iloc[i]['destination'])[:50]} -> {df.iloc[i]['distance_km']} km")
    except FileNotFoundError:
        print(f"      ❌ 文件不存在: {distance_file}")
        df = pd.DataFrame(columns=['destination', 'distance_km'])
    except Exception as e:
        print(f"      ❌ 文件读取错误: {e}")
        df = pd.DataFrame(columns=['destination', 'distance_km'])
    
    # 构建查找字典
    distance_dict = {}
    for _, row in df.iterrows():
        key = str(row['destination']).strip()
        val = row['distance_km']
        if not pd.isna(val) and key and key != 'nan':
            distance_dict[key] = val
            # 去掉括号的版本
            key_clean = re.sub(r'（[^）]*）', '', key).strip()
            key_clean = re.sub(r'\([^)]*\)', '', key_clean).strip()
            if key_clean != key:
                distance_dict[key_clean] = val
    
    valid_count = sum(1 for v in distance_dict.values() if not pd.isna(v))
    print(f"      构建字典: {valid_count} 个地址有有效距离\n")
    return distance_dict


def match_distance(destination, distance_dict):
    """匹配距离"""
    # 精确匹配
    if destination in distance_dict:
        return distance_dict[destination]
    
    # 去掉括号匹配
    clean = re.sub(r'（[^）]*）', '', destination).strip()
    clean = re.sub(r'\([^)]*\)', '', clean).strip()
    if clean in distance_dict:
        return distance_dict[clean]
    
    # 模糊匹配
    for key, val in distance_dict.items():
        if len(key) > 4 and (key in destination or destination in key):
            return val
    
    return None


def main():
    # 1. 加载数据
    tasks = load_tasks(TASK_FILE)
    distance_dict = load_distances(DISTANCE_FILE)
    
    # 2. 匹配距离并计算
    print(f"[3/4] 匹配距离并计算成本...\n")
    print(f"{'序号':<6} {'车型':<6} {'车数':<5} {'天数':<5} {'距离(km)':<12} {'行驶费':<10} {'时间费':<10} {'单次总费':<12} {'目的地'}")
    print("-" * 140)
    
    results = []
    matched_count = 0
    unmatched_count = 0
    total_cost = 0
    
    for idx, task in tasks.iterrows():
        dest = task['destination']
        vehicle_type = task['vehicle']
        count = task['count']
        days = task['days']
        
        distance = match_distance(dest, distance_dict)
        
        if distance is None:
            unmatched_count += 1
            print(f"{idx+1:<6} {vehicle_type:<6} {count:<5} {days:<5} {'N/A':<12} {'N/A':<10} {'N/A':<10} {'N/A':<12} ❌ {dest[:50]}")
            results.append({
                '序号': idx + 1, '车型': vehicle_type, '车数': count, '天数': days,
                '目的地': dest, '距离_km': None, '行驶费': None, '时间费': None, '单次总费': None
            })
            continue
        
        matched_count += 1
        v = VEHICLES[vehicle_type]
        
        driving_cost = (v.fuel_cost_per_km + v.toll_per_km) * distance
        time_cost = v.daily_fixed_cost() * days
        single_cost = (driving_cost + time_cost) * count
        total_cost += single_cost
        
        # 每10条输出一次，避免刷屏
        if idx % 10 == 0 or idx < 3:
            print(f"{idx+1:<6} {vehicle_type:<6} {count:<5} {days:<5} {distance:<12.2f} {driving_cost:<10.2f} {time_cost:<10.2f} {single_cost:<12.2f} {dest[:50]}")
        
        results.append({
            '序号': idx + 1, '车型': vehicle_type, '车数': count, '天数': days,
            '目的地': dest, '距离_km': distance,
            '行驶费': round(driving_cost, 2), '时间费': round(time_cost, 2),
            '单次总费': round(single_cost, 2)
        })
    
    # 3. 输出结果
    # 确保DataFrame有正确的列名，即使为空也要有列
    if results:
        results_df = pd.DataFrame(results)
    else:
        results_df = pd.DataFrame(columns=['序号', '车型', '车数', '天数', '目的地', '距离_km', '行驶费', '时间费', '单次总费'])
    
    print(f"\n{'='*70}")
    print(f"[4/4] 计算结果汇总")
    print(f"{'='*70}")
    print(f"总任务数:     {len(tasks)}")
    print(f"匹配成功:     {matched_count}")
    print(f"匹配失败:     {unmatched_count}")
    if len(tasks) > 0:
        print(f"匹配率:       {matched_count/len(tasks)*100:.1f}%")
    else:
        print(f"⚠️  未加载到任何任务数据，请检查Excel文件结构")
    print(f"总运输费用:   {total_cost:,.2f} 元\n")
    
    # 按车型统计
    if len(results_df) > 0:
        matched = results_df[results_df['距离_km'].notna()]
    else:
        matched = results_df
    if len(matched) > 0:
        print("按车型统计:")
        print(f"{'车型':<8} {'任务数':<8} {'总距离(km)':<12} {'总费用':<14} {'平均费用':<12}")
        print("-" * 54)
        for vt in ['4.2', '7.6', '9.6']:
            subset = matched[matched['车型'] == vt]
            if len(subset) > 0:
                print(f"{vt:<8} {len(subset):<8} {subset['距离_km'].sum():<12.0f} "
                      f"{subset['单次总费'].sum():<14.2f} {subset['单次总费'].mean():<12.2f}")
    
    # 未匹配地址
    if unmatched_count > 0:
        print(f"\n未匹配地址（需手动补充距离）:")
        unmatched = results_df[results_df['距离_km'].isna()]
        for _, row in unmatched.iterrows():
            print(f"  [{int(row['序号'])}] {row['目的地'][:80]}")
    
    # 保存（同时生成xlsx和csv两种格式）
    if len(results_df) > 0:
        results_df.to_excel("运输成本明细.xlsx", index=False)
        results_df.to_csv("运输成本明细.csv", index=False, encoding='utf-8-sig')
        print(f"\n✅ 详细结果已保存至:")
        print(f"   - 运输成本明细.xlsx")
        print(f"   - 运输成本明细.csv")
    else:
        print(f"\n⚠️  没有成功匹配的数据，无法生成结果文件")
    
    return total_cost, results_df


if __name__ == "__main__":
    total_cost, details = main()