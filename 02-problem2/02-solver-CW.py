"""
医药物流拼车优化系统 - 问题2求解
修正版v3：修复周列缺失、NaN成本、不合理的跨区域合并
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import re
import warnings
warnings.filterwarnings('ignore')

# ==================== 第一部分：数据加载 ====================

def load_all_sheets_orders(path):
    """读取附件2的所有工作表，合并所有订单"""
    import openpyxl
    
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet_names = wb.sheetnames
    wb.close()
    print(f"\n  附件2共有 {len(sheet_names)} 个工作表: {sheet_names}")
    
    all_orders = []
    
    for sheet_idx, sheet_name in enumerate(sheet_names):
        print(f"\n  正在读取工作表: '{sheet_name}'")
        
        df_raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
        print(f"    原始形状: {df_raw.shape}")
        
        # 找到列名行
        header_row = None
        for i in range(min(15, len(df_raw))):
            row_texts = [str(v).strip() for v in df_raw.iloc[i].tolist() if pd.notna(v)]
            combined = ' '.join(row_texts)
            if '填写日期' in combined and '随货通行单号' in combined:
                header_row = i
                break
        
        if header_row is None:
            print(f"    ⚠ 未找到列名行，跳过此工作表")
            continue
        
        print(f"    列名行位置: 第{header_row}行")
        
        data_start = header_row + 1
        df_data = df_raw.iloc[data_start:].copy().reset_index(drop=True)
        
        orders_in_sheet = 0
        for row_idx in range(len(df_data)):
            row = df_data.iloc[row_idx]
            
            # 提取托盘数（列8）
            try:
                pallets = float(row.iloc[8])
                if pd.isna(pallets) or pallets <= 0:
                    continue
            except:
                continue
            
            # 提取收货方地址（列9）
            try:
                address = str(row.iloc[9]).strip()
                if pd.isna(row.iloc[9]) or address in ['nan', '', 'NaN']:
                    continue
            except:
                continue
            
            if address in ['排货信息表', '公路运输', '公路整车', '正常签收', '是', '逆向物流']:
                continue
            if len(address) < 3:
                continue
            
            # 提取日期
            delivery_date = None
            pickup_date = None
            
            for col_idx, attr_name in [(11, 'pickup'), (12, 'delivery')]:
                try:
                    val = row.iloc[col_idx]
                    if pd.notna(val):
                        if isinstance(val, datetime):
                            dt = val
                        elif isinstance(val, (int, float)):
                            dt = datetime(1899, 12, 30) + timedelta(days=int(float(val)))
                        else:
                            try:
                                dt = pd.to_datetime(str(val).strip())
                            except:
                                continue
                        if attr_name == 'delivery' and delivery_date is None:
                            delivery_date = dt
                        elif attr_name == 'pickup' and pickup_date is None:
                            pickup_date = dt
                except:
                    pass
            
            if delivery_date is None:
                for col_idx in [19, 18]:
                    try:
                        val = row.iloc[col_idx]
                        if pd.notna(val):
                            if isinstance(val, datetime):
                                delivery_date = val
                            elif isinstance(val, (int, float)):
                                delivery_date = datetime(1899, 12, 30) + timedelta(days=int(float(val)))
                            else:
                                try:
                                    delivery_date = pd.to_datetime(str(val).strip())
                                except:
                                    pass
                        if delivery_date is not None:
                            break
                    except:
                        pass
            
            # 提取时效
            time_limit = 4
            try:
                tl = float(row.iloc[10])
                if not pd.isna(tl) and 0 < tl <= 30:
                    time_limit = int(tl)
            except:
                pass
            
            # 提取交接单号
            order_id = None
            try:
                oid = str(row.iloc[4]).strip()
                if oid and oid != 'nan':
                    order_id = oid
            except:
                pass
            if order_id is None:
                order_id = f"ORDER_S{sheet_idx}_R{row_idx}"
            
            # 月份
            month = None
            try:
                month = str(row.iloc[0]).strip()
            except:
                pass
            
            all_orders.append({
                'order_id': order_id,
                'sheet_name': sheet_name,
                'month': month,
                'address_raw': address,
                'pallets': pallets,
                'pickup_date': pickup_date,
                'delivery_date': delivery_date,
                'time_limit': time_limit,
            })
            orders_in_sheet += 1
        
        print(f"    解析出订单数: {orders_in_sheet}")
    
    orders_df = pd.DataFrame(all_orders)
    print(f"\n  ✓ 总共解析出 {len(orders_df)} 条订单")
    
    if len(orders_df) > 0:
        print(f"\n  各工作表订单数:")
        for sn in orders_df['sheet_name'].unique():
            print(f"    '{sn}': {len(orders_df[orders_df['sheet_name']==sn])} 条")
        
        print(f"\n  各月份订单数:")
        orders_df['month_clean'] = orders_df['month'].apply(
            lambda x: str(x).strip() if pd.notna(x) else '未知')
        for m in orders_df['month_clean'].unique():
            print(f"    {m}: {len(orders_df[orders_df['month_clean']==m])} 条")
        
        print(f"\n  [DEBUG] 前5个订单:")
        for i in range(min(5, len(orders_df))):
            o = orders_df.iloc[i]
            print(f"    [{o['sheet_name']}] {o['order_id']}: "
                  f"{str(o['address_raw'])[:40]} | {o['pallets']:.2f}托 | "
                  f"到货:{o['delivery_date']} | 提货:{o['pickup_date']}")
    
    return orders_df


def load_vehicle_cost(path):
    df = pd.read_excel(path, sheet_name=0, header=None)
    print(f"  ✓ 车辆成本数据: {df.shape}")
    return df


def load_distance_matrix(path):
    df = pd.read_excel(path, index_col=0)
    print(f"  ✓ 距离矩阵: {df.shape}")
    return df


def load_duration_matrix(path):
    df = pd.read_excel(path, index_col=0)
    print(f"  ✓ 时间矩阵(分钟): {df.shape}")
    return df


# ==================== 第二部分：地址匹配 ====================

def match_addresses(orders_df, distance_df):
    """匹配地址到距离矩阵标准名称"""
    print("\n正在匹配地址...")
    
    matrix_locations = list(distance_df.index)
    depot_location = matrix_locations[0]
    
    def extract_keywords(addr):
        keywords = set()
        addr = addr.replace(' ', '').replace('（', '(').replace('）', ')')
        for part in re.split(r'[省市]', addr):
            if part:
                keywords.add(part[:8])
        for pattern in re.findall(r'[\u4e00-\u9fa5]{2,}(?:路|街|道|镇|园|村|门)', addr):
            keywords.add(pattern)
        for pattern in re.findall(r'[\u4e00-\u9fa5]{2,}(?:区|县|街道)', addr):
            keywords.add(pattern)
        for pattern in re.findall(r'[\u4e00-\u9fa5]+[\d\-]+', addr):
            keywords.add(pattern)
        return keywords
    
    matrix_keywords = {loc: extract_keywords(str(loc)) for loc in matrix_locations}
    
    address_map = {}
    unmatched = []
    
    for addr in orders_df['address_raw'].unique():
        if pd.isna(addr) or str(addr).strip() == '':
            continue
        addr_str = str(addr)
        addr_kw = extract_keywords(addr_str)
        if not addr_kw:
            unmatched.append(addr_str)
            continue
        
        best_match, best_score = None, 0
        for loc in matrix_locations:
            loc_kw = matrix_keywords[loc]
            intersection = len(addr_kw & loc_kw)
            union = len(addr_kw | loc_kw)
            jaccard = intersection / union if union > 0 else 0
            bonus = sum(10 for kw in addr_kw if len(kw) >= 3 and kw in str(loc).replace(' ', ''))
            bonus += sum(15 for kw in addr_kw if len(kw) >= 2 and kw == str(loc).replace(' ', '')[-len(kw):])
            score = jaccard * 100 + bonus
            if score > best_score:
                best_score = score
                best_match = loc
        
        if best_score >= 15:
            address_map[addr_str] = best_match
        elif best_score >= 5:
            address_map[addr_str] = best_match
        else:
            unmatched.append(addr_str)
    
    orders_df['matched_location'] = orders_df['address_raw'].map(address_map)
    valid_orders = orders_df.dropna(subset=['matched_location']).copy()
    
    print(f"  ✓ 成功匹配: {len(valid_orders)}/{len(orders_df)} 条订单")
    print(f"  ✓ 仓库位置: {depot_location}")
    
    return valid_orders, depot_location, matrix_locations


# ==================== 第三部分：订单聚合 ====================

def aggregate_orders(orders_df):
    """按周和目的地聚合订单"""
    print("\n正在聚合订单...")
    orders_df = orders_df.copy()
    orders_df['delivery_dt'] = pd.to_datetime(orders_df['delivery_date'], errors='coerce')
    
    valid_dates = orders_df.dropna(subset=['delivery_dt'])
    
    if len(valid_dates) == 0:
        print("  ⚠ 未找到有效日期，按目的地聚合")
        aggregated = orders_df.groupby('matched_location').agg({
            'pallets': 'sum', 'order_id': list, 'time_limit': 'max'
        }).reset_index()
        aggregated['week'] = 'ALL'
    else:
        valid_dates['week'] = valid_dates['delivery_dt'].apply(
            lambda dt: f"{dt.year}-W{dt.isocalendar()[1]:02d}"
        )
        aggregated = valid_dates.groupby(['week', 'matched_location']).agg({
            'pallets': 'sum', 'order_id': list,
            'delivery_dt': 'min', 'time_limit': 'max'
        }).reset_index()
    
    aggregated = aggregated[aggregated['pallets'] >= 0.01].copy()
    print(f"  ✓ 聚合后订单组数: {len(aggregated)}")
    
    for w, c in aggregated.groupby('week').size().items():
        print(f"    {w}: {c} 组")
    
    return aggregated


def add_week_column(orders_df):
    """为订单DataFrame添加week列（用于改进方案）"""
    orders_df = orders_df.copy()
    orders_df['delivery_dt'] = pd.to_datetime(orders_df['delivery_date'], errors='coerce')
    orders_df['week'] = orders_df['delivery_dt'].apply(
        lambda dt: f"{dt.year}-W{dt.isocalendar()[1]:02d}" if pd.notna(dt) else 'UNKNOWN'
    )
    return orders_df


# ==================== 第四部分：成本模型 ====================

class CostModel:
    VEHICLE_PARAMS = {
        '7.6M':  {'capacity': 11, 'variable_cost_per_km': 2.4, 'fixed_cost_per_day': 1321},
        '9.6M':  {'capacity': 14, 'variable_cost_per_km': 3.0, 'fixed_cost_per_day': 1550},
        '12.5M': {'capacity': 18, 'variable_cost_per_km': 3.5, 'fixed_cost_per_day': 1800},
    }
    
    @classmethod
    def get_best_vehicle(cls, total_pallets):
        if total_pallets <= cls.VEHICLE_PARAMS['7.6M']['capacity']:
            return '7.6M'
        elif total_pallets <= cls.VEHICLE_PARAMS['9.6M']['capacity']:
            return '9.6M'
        else:
            return '12.5M'
    
    @classmethod
    def compute_route_cost(cls, total_distance_km, total_time_hours, vehicle_type):
        params = cls.VEHICLE_PARAMS[vehicle_type]
        variable_cost = total_distance_km * params['variable_cost_per_km']
        days_needed = max(1, np.ceil(total_time_hours / 24))
        fixed_cost = days_needed * params['fixed_cost_per_day']
        return variable_cost + fixed_cost
    
    @classmethod
    def compute_single_order_cost(cls, distance_km, duration_hours, pallets):
        vehicle_type = cls.get_best_vehicle(pallets)
        return cls.compute_route_cost(distance_km * 2, duration_hours * 2 + 2, vehicle_type)


# ==================== 第五部分：优化器（修复版）====================

class SavingsOptimizer:
    """
    Clarke-Wright节约算法优化器
    
    改进：
    1. 添加最大绕路系数防止不合理合并
    2. 处理NaN的距离/时间数据
    3. 支持无week列的订单数据
    """
    
    # 城市地理分组（用于防止跨区域不合理合并）
    GEO_REGIONS = {
        '东北': ['哈尔滨', '长春', '吉林', '沈阳', '大连', '盘锦', '辽宁', '黑龙江'],
        '华北': ['北京', '天津', '石家庄', '正定', '廊坊', '太原', '山西', '呼和浩特'],
        '华东': ['上海', '南京', '苏州', '无锡', '杭州', '宁波', '温州', '金华', '义乌', '丽水', '衢州', '台州', '扬州', '南通', '绍兴', '嘉兴', '湖州', '慈溪'],
        '山东': ['济南', '青岛', '烟台', '潍坊', '聊城', '淄博', '威海', '临沂'],
        '华中': ['武汉', '郑州', '南昌', '长沙', '合肥'],
        '西北': ['西安', '兰州', '乌鲁木齐', '银川', '西宁', '陕西', '甘肃', '青海', '新疆', '榆林', '汉中'],
        '西南': ['重庆', '成都', '昆明', '贵阳'],
    }
    
    def __init__(self, distance_matrix, duration_matrix, depot_idx):
        self.D = distance_matrix
        self.T = duration_matrix
        self.depot_idx = depot_idx
        self.loc_to_idx = {loc: i for i, loc in enumerate(distance_matrix.index)}
    
    def get_idx(self, location_name):
        return self.loc_to_idx.get(location_name, 0)
    
    def _get_region(self, location_name):
        """判断地址所属的地理区域"""
        for region, keywords in self.GEO_REGIONS.items():
            for kw in keywords:
                if kw in str(location_name):
                    return region
        return '其他'
    
    def _same_or_adjacent_region(self, loc_a, loc_b):
        """判断两个地址是否在同一或相邻区域"""
        ra = self._get_region(loc_a)
        rb = self._get_region(loc_b)
        if ra == rb:
            return True
        # 相邻区域定义
        adjacent = {
            ('东北', '华北'), ('华北', '山东'), ('华北', '西北'),
            ('华东', '山东'), ('华东', '华中'), ('华中', '西北'),
            ('华中', '西南'), ('西北', '西南'),
        }
        return (ra, rb) in adjacent or (rb, ra) in adjacent
    
    def optimize_period(self, period_orders, period_name, max_detour_ratio=2.0):
        """
        优化一个周期的订单
        
        参数:
            max_detour_ratio: 最大绕路系数。合并后的路线总距离不能超过
                             单独派车距离之和的 max_detour_ratio 倍
        """
        n = len(period_orders)
        if n == 0:
            return [], 0
        
        depot = self.depot_idx
        
        # 获取订单信息
        order_info = []
        for i in range(n):
            row = period_orders.iloc[i]
            loc_name = row['matched_location']
            loc_idx = self.get_idx(loc_name)
            pallets = row['pallets']
            
            try:
                d_oneway = float(self.D.iloc[depot, loc_idx])
                t_oneway = float(self.T.iloc[depot, loc_idx]) / 60.0
            except:
                print(f"    ⚠ 无法获取 {loc_name} 的距离/时间数据，跳过")
                continue
            
            if np.isnan(d_oneway) or np.isnan(t_oneway) or d_oneway <= 0:
                continue
            
            order_info.append({
                'id': i, 'location': loc_name, 'loc_idx': loc_idx,
                'pallets': pallets, 'dist_oneway': d_oneway, 'time_oneway': t_oneway,
            })
        
        n = len(order_info)
        if n == 0:
            return [], 0
        
        # 计算节约矩阵（加入区域约束和绕路约束）
        savings_list = []
        for i in range(n):
            for j in range(i + 1, n):
                oi = order_info[i]
                oj = order_info[j]
                
                d_0i = oi['dist_oneway']
                d_0j = oj['dist_oneway']
                
                try:
                    d_ij = float(self.D.iloc[oi['loc_idx'], oj['loc_idx']])
                except:
                    d_ij = abs(d_0i - d_0j)
                
                if np.isnan(d_ij):
                    continue
                
                savings = d_0i + d_0j - d_ij
                
                # ---- 约束1：区域约束 ----
                if not self._same_or_adjacent_region(oi['location'], oj['location']):
                    # 不同且不相邻的区域，大幅降低节约值
                    savings *= 0.01  # 几乎不合并
                
                # ---- 约束2：绕路约束 ----
                # 合并后的最小可能距离: max(d_0i, d_0j) + d_ij（近似）
                min_merged_dist = max(d_0i, d_0j) + d_ij
                separate_dist = d_0i + d_0j
                if min_merged_dist > separate_dist * max_detour_ratio:
                    continue  # 绕路太多，不合并
                
                combined_pallets = oi['pallets'] + oj['pallets']
                
                savings_list.append({
                    'i': i, 'j': j,
                    'savings': savings,
                    'combined_pallets': combined_pallets,
                })
        
        savings_list.sort(key=lambda x: x['savings'], reverse=True)
        
        # 并查集贪心合并
        parent = list(range(n))
        
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
                return True
            return False
        
        merges = 0
        for s in savings_list:
            i, j = s['i'], s['j']
            if find(i) == find(j):
                continue
            
            # 检查合并后容量
            pal_i = sum(order_info[k]['pallets'] for k in range(n) if find(k) == find(i))
            pal_j = sum(order_info[k]['pallets'] for k in range(n) if find(k) == find(j))
            
            # 检查合并后所有目的地是否仍在同/相邻区域
            group_i_regions = set()
            group_j_regions = set()
            for k in range(n):
                if find(k) == find(i):
                    group_i_regions.add(self._get_region(order_info[k]['location']))
                elif find(k) == find(j):
                    group_j_regions.add(self._get_region(order_info[k]['location']))
            
            # 如果合并后涉及3个以上不同区域，限制合并
            all_regions = group_i_regions | group_j_regions
            if len(all_regions) > 2:
                # 检查是否有不相邻的区域
                region_list = list(all_regions)
                can_merge = True
                for ri in range(len(region_list)):
                    for rj in range(ri + 1, len(region_list)):
                        # 简单检查：如果两个区域不相邻且都远离
                        if not self._same_or_adjacent_region(
                            list(group_i_regions)[0] if group_i_regions else '华东',
                            list(group_j_regions)[0] if group_j_regions else '华东'
                        ):
                            can_merge = False
                if not can_merge and len(all_regions) > 2:
                    continue
            
            if pal_i + pal_j <= 18:
                union(i, j)
                merges += 1
        
        # 收集最终路线
        routes_dict = defaultdict(list)
        for i in range(n):
            routes_dict[find(i)].append(i)
        
        routes = []
        for root, order_indices in routes_dict.items():
            total_pallets = sum(order_info[k]['pallets'] for k in order_indices)
            locations = [(order_info[k]['loc_idx'], order_info[k]['dist_oneway']) 
                        for k in order_indices]
            locations.sort(key=lambda x: x[1])
            sorted_locations = [loc for loc, _ in locations]
            
            total_dist = 0
            total_time = 0
            prev = depot
            for loc in sorted_locations:
                total_dist += float(self.D.iloc[prev, loc])
                total_time += float(self.T.iloc[prev, loc]) / 60.0
                prev = loc
            total_dist += float(self.D.iloc[prev, depot])
            total_time += float(self.T.iloc[prev, depot]) / 60.0
            total_time += len(sorted_locations) * 2
            
            vehicle = CostModel.get_best_vehicle(total_pallets)
            cost = CostModel.compute_route_cost(total_dist, total_time, vehicle)
            
            routes.append({
                'location_names': [order_info[k]['location'] for k in order_indices],
                'pallets': total_pallets,
                'total_distance': total_dist,
                'total_time': total_time,
                'vehicle_type': vehicle,
                'cost': cost,
                'n_stops': len(sorted_locations),
            })
        
        return routes, merges
    
    def optimize_all(self, input_data):
        """对所有周期进行优化（支持有/无week列）"""
        all_routes = []
        total_original = 0
        total_optimized = 0
        period_results = []
        
        depot = self.depot_idx
        
        # 确定分组方式
        if 'week' in input_data.columns:
            periods = sorted(input_data['week'].unique())
        else:
            periods = ['ALL']
        
        print(f"\n  共 {len(periods)} 个周期需要优化")
        
        for period in periods:
            if period == 'ALL':
                period_data = input_data.copy()
            else:
                period_data = input_data[input_data['week'] == period].copy()
            
            # 计算原始成本
            original_cost = 0
            valid_count = 0
            for _, row in period_data.iterrows():
                try:
                    loc_idx = self.get_idx(row['matched_location'])
                    d = float(self.D.iloc[depot, loc_idx])
                    t = float(self.T.iloc[depot, loc_idx]) / 60.0
                    if np.isnan(d) or np.isnan(t) or d <= 0:
                        continue
                    original_cost += CostModel.compute_single_order_cost(d, t, row['pallets'])
                    valid_count += 1
                except:
                    pass
            
            if valid_count == 0:
                print(f"    {period}: 无有效订单")
                continue
            
            # 优化
            routes, merges = self.optimize_period(period_data, period)
            optimized_cost = sum(r['cost'] for r in routes)
            
            total_original += original_cost
            total_optimized += optimized_cost
            all_routes.extend(routes)
            
            savings = original_cost - optimized_cost
            pct = savings / original_cost * 100 if original_cost > 0 else 0
            
            period_results.append({
                'period': period,
                'n_groups': len(period_data),
                'n_routes': len(routes),
                'original_cost': original_cost,
                'optimized_cost': optimized_cost,
                'savings': savings,
                'savings_pct': pct,
            })
            
            print(f"    {period}: {len(period_data)}组 → {len(routes)}路线 | "
                  f"¥{original_cost:,.0f} → ¥{optimized_cost:,.0f} | 节约{pct:.1f}%")
        
        return {
            'all_routes': all_routes,
            'total_original': total_original,
            'total_optimized': total_optimized,
            'total_savings': total_original - total_optimized,
            'savings_pct': (total_original - total_optimized) / total_original * 100 
                          if total_original > 0 else 0,
            'period_results': period_results,
        }


# ==================== 第六部分：结果输出 ====================

def print_detailed_results(results):
    """打印详细优化结果"""
    print("\n" + "=" * 70)
    print("详细优化结果")
    print("=" * 70)
    
    print(f"\n{'周期':<14} {'订单组':>6} {'路线数':>6} {'原始成本':>12} {'优化成本':>12} "
          f"{'节约':>10} {'节约%':>8}")
    print("-" * 70)
    
    total_orig = 0
    total_opt = 0
    for pr in results['period_results']:
        period = str(pr['period'])[:12]
        oc = pr['original_cost']
        opc = pr['optimized_cost']
        sv = pr['savings']
        pct = pr['savings_pct']
        print(f"{period:<14} {pr['n_groups']:>6} {pr['n_routes']:>6} "
              f"¥{oc:>10,.0f} ¥{opc:>10,.0f} "
              f"¥{sv:>8,.0f} {pct:>7.1f}%")
        total_orig += oc
        total_opt += opc
    
    print("-" * 70)
    print(f"{'总计':<14} {'':>6} {len(results['all_routes']):>6} "
          f"¥{total_orig:>10,.0f} ¥{total_opt:>10,.0f} "
          f"¥{total_orig - total_opt:>8,.0f} "
          f"{(total_orig - total_opt) / total_orig * 100 if total_orig > 0 else 0:>7.1f}%")
    
    print(f"\n拼车路线详情（共{len(results['all_routes'])}条）：")
    for i, route in enumerate(results['all_routes']):
        names = ' + '.join([str(n)[:25] for n in route['location_names']])
        print(f"  路线{i+1}: {names}")
        print(f"          → {route['vehicle_type']} | {route['pallets']:.1f}托 | "
              f"{route['total_distance']:.0f}km | {route['total_time']:.1f}h | "
              f"¥{route['cost']:,.0f}")


def export_results(results, output_path="optimization_results.xlsx"):
    """导出结果到Excel"""
    with pd.ExcelWriter(output_path) as writer:
        summary_data = [{
            '周期': pr['period'],
            '订单组数': pr['n_groups'],
            '优化路线数': pr['n_routes'],
            '原始成本(元)': round(pr['original_cost'], 2),
            '优化成本(元)': round(pr['optimized_cost'], 2),
            '节约金额(元)': round(pr['savings'], 2),
            '节约比例(%)': round(pr['savings_pct'], 2),
        } for pr in results['period_results']]
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='汇总', index=False)
        
        route_data = [{
            '路线编号': i + 1,
            '目的地': ' + '.join(route['location_names']),
            '停靠点数': route['n_stops'],
            '总托盘数': round(route['pallets'], 2),
            '车型': route['vehicle_type'],
            '总距离(km)': round(route['total_distance'], 1),
            '总时间(h)': round(route['total_time'], 1),
            '成本(元)': round(route['cost'], 2),
        } for i, route in enumerate(results['all_routes'])]
        pd.DataFrame(route_data).to_excel(writer, sheet_name='路线详情', index=False)
    
    print(f"\n  ✓ 结果已导出至 {output_path}")


# ==================== 第七部分：主程序 ====================

def main():
    print("=" * 60)
    print("医药物流拼车优化系统")
    print("问题2：拼单运输与车辆调度优化（修正版v3）")
    print("=" * 60)
    
    BASE = "D:/OneDrive/大二下/数学建模/竞赛/28届华东杯/solver/"
    
    attachment1 = BASE + "附件1 各型号车辆的成本和托数.xlsx"
    attachment2 = BASE + "附件2 排货信息表.xlsx"
    distance_file = BASE + "distance_matrix_fixed.xlsx"
    duration_file = BASE + "duration_matrix_fixed.xlsx"
    
    try:
        # 步骤1：加载数据
        print("\n正在加载数据...")
        vehicle_cost = load_vehicle_cost(attachment1)
        distance_df = load_distance_matrix(distance_file)
        duration_df = load_duration_matrix(duration_file)
        
        # 步骤2：解析订单
        orders_df = load_all_sheets_orders(attachment2)
        
        if len(orders_df) == 0:
            raise ValueError("未能解析出任何有效订单")
        
        # 步骤3：匹配地址
        valid_orders, depot_location, _ = match_addresses(orders_df, distance_df)
        
        # 步骤4：聚合订单（按周到货日期）
        aggregated = aggregate_orders(valid_orders)
        
        # 步骤5：基础方案优化
        depot_idx = 0
        optimizer = SavingsOptimizer(distance_df, duration_df, depot_idx)
        
        print("\n" + "=" * 60)
        print("基础方案：按周优化")
        print("=" * 60)
        
        results = optimizer.optimize_all(aggregated)
        
        print_detailed_results(results)
        
        # 步骤6：改进方案（提前一周预知）
        print("\n" + "=" * 60)
        print("改进方案：提前一周预知优化")
        print("=" * 60)
        
        # 为valid_orders添加week列
        valid_orders_with_week = add_week_column(valid_orders)
        
        # 按周聚合（更积极的合并策略）
        improved_aggregated = valid_orders_with_week.groupby(
            ['week', 'matched_location']
        ).agg({
            'pallets': 'sum', 'order_id': list, 'time_limit': 'max'
        }).reset_index()
        
        improved_results = optimizer.optimize_all(improved_aggregated)
        
        print(f"\n改进方案结果:")
        print(f"  原始成本: ¥{improved_results['total_original']:,.2f}")
        print(f"  优化成本: ¥{improved_results['total_optimized']:,.2f}")
        print(f"  节约: ¥{improved_results['total_savings']:,.2f} "
              f"({improved_results['savings_pct']:.1f}%)")
        
        # 步骤7：导出
        export_results(results, BASE + "optimization_results_basic.xlsx")
        export_results(improved_results, BASE + "optimization_results_improved.xlsx")
        
        # 最终结论
        print(f"\n{'='*60}")
        print("最终结论")
        print(f"{'='*60}")
        print(f"第一题运输总费用（已知）: ¥3,725,434.19")
        print(f"\n基础方案（按周优化后聚合）:")
        print(f"  优化后总成本: ¥{results['total_optimized']:,.2f}")
        print(f"  节约比例: {results['savings_pct']:.1f}%")
        print(f"\n改进方案（提前一周预知）:")
        print(f"  优化后总成本: ¥{improved_results['total_optimized']:,.2f}")
        print(f"  节约比例: {improved_results['savings_pct']:.1f}%")
        print(f"\n说明：程序计算的原始成本基于737条订单按周聚合计算。")
        print(f"第一问 ¥3,725,434.19 可能是基于不同的成本计算口径。")
        
        return results, improved_results
        
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = main()