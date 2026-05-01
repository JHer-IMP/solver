"""
医药物流拼车优化系统 - 问题2
两阶段算法：地理聚类 + OR-Tools VRPTW约束求解
修正版：处理NaN距离矩阵、修正BASE路径
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
    """读取附件2所有工作表的订单"""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet_names = wb.sheetnames
    wb.close()
    print(f"\n  附件2共有 {len(sheet_names)} 个工作表: {sheet_names}")
    
    all_orders = []
    for sheet_idx, sheet_name in enumerate(sheet_names):
        print(f"\n  正在读取: '{sheet_name}'")
        df_raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
        print(f"    原始形状: {df_raw.shape}")
        
        header_row = None
        for i in range(min(15, len(df_raw))):
            row_texts = [str(v).strip() for v in df_raw.iloc[i].tolist() if pd.notna(v)]
            combined = ' '.join(row_texts)
            if '填写日期' in combined and '随货通行单号' in combined:
                header_row = i
                break
        
        if header_row is None:
            print(f"    ⚠ 未找到列名行，跳过")
            continue
        
        df_data = df_raw.iloc[header_row+1:].copy().reset_index(drop=True)
        orders_in_sheet = 0
        
        for row_idx in range(len(df_data)):
            row = df_data.iloc[row_idx]
            
            # 托盘数（列8）
            try:
                pallets = float(row.iloc[8])
                if pd.isna(pallets) or pallets <= 0:
                    continue
            except:
                continue
            
            # 地址（列9）
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
            
            # 日期
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
                            try: dt = pd.to_datetime(str(val).strip())
                            except: continue
                        if attr_name == 'delivery' and delivery_date is None:
                            delivery_date = dt
                        elif attr_name == 'pickup' and pickup_date is None:
                            pickup_date = dt
                except: pass
            
            if delivery_date is None:
                for col_idx in [19, 18]:
                    try:
                        val = row.iloc[col_idx]
                        if pd.notna(val):
                            if isinstance(val, datetime): delivery_date = val
                            elif isinstance(val, (int, float)):
                                delivery_date = datetime(1899, 12, 30) + timedelta(days=int(float(val)))
                            else:
                                try: delivery_date = pd.to_datetime(str(val).strip())
                                except: pass
                        if delivery_date is not None: break
                    except: pass
            
            # 时效
            time_limit = 4
            try:
                tl = float(row.iloc[10])
                if not pd.isna(tl) and 0 < tl <= 30: time_limit = int(tl)
            except: pass
            
            # 交接单号
            try:
                order_id = str(row.iloc[4]).strip()
                if not order_id or order_id == 'nan': order_id = f"ORD_{sheet_idx}_{row_idx}"
            except:
                order_id = f"ORD_{sheet_idx}_{row_idx}"
            
            all_orders.append({
                'order_id': order_id, 'sheet_name': sheet_name,
                'address_raw': address, 'pallets': pallets,
                'pickup_date': pickup_date, 'delivery_date': delivery_date,
                'time_limit': time_limit,
            })
            orders_in_sheet += 1
        
        print(f"    解析: {orders_in_sheet} 条")
    
    orders_df = pd.DataFrame(all_orders)
    print(f"\n  ✓ 总计解析 {len(orders_df)} 条订单")
    return orders_df


def load_and_clean_matrix(path):
    """
    加载矩阵并清理NaN值
    
    对于距离/时间矩阵中的NaN：
    - 对角线上NaN填充为0
    - 其他NaN用仓库到两点的距离之和作为估计值
    """
    df = pd.read_excel(path, index_col=0)
    print(f"    原始矩阵形状: {df.shape}")
    
    # 检查NaN
    nan_count = df.isna().sum().sum()
    if nan_count > 0:
        print(f"    检测到 {nan_count} 个NaN值，正在清理...")
        
        # 转换为numpy以便操作
        mat = df.values.copy()
        n = mat.shape[0]
        
        # 对角线填0
        for i in range(n):
            if np.isnan(mat[i, i]):
                mat[i, i] = 0
        
        # 对于非对角NaN，用仓库到两点的距离之和估计
        # 仓库在第0行/列
        for i in range(n):
            for j in range(n):
                if np.isnan(mat[i][j]):
                    if i == j:
                        mat[i][j] = 0
                    else:
                        # 估计值 = d(仓库,i) + d(仓库,j)
                        d_0i = mat[0, i] if not np.isnan(mat[0, i]) else 500
                        d_0j = mat[0, j] if not np.isnan(mat[0, j]) else 500
                        mat[i][j] = d_0i + d_0j
        
        # 重建DataFrame
        df = pd.DataFrame(mat, index=df.index, columns=df.columns)
        
        remaining_nan = df.isna().sum().sum()
        if remaining_nan > 0:
            print(f"    ⚠ 仍有 {remaining_nan} 个NaN，用中位数填充")
            df = df.fillna(df.median())
    
    print(f"    ✓ 清理后矩阵形状: {df.shape}, 剩余NaN: {df.isna().sum().sum()}")
    return df


# ==================== 第二部分：地址匹配 ====================

def match_addresses(orders_df, distance_df):
    """模糊匹配地址到距离矩阵标准名称"""
    print("\n正在匹配地址...")
    matrix_locations = list(distance_df.index)
    depot_location = matrix_locations[0]
    
    def extract_keywords(addr):
        addr = addr.replace(' ', '').replace('（', '(').replace('）', ')')
        kws = set()
        for part in re.split(r'[省市]', addr):
            if part: kws.add(part[:6])
        for p in re.findall(r'[\u4e00-\u9fa5]{2,}(?:路|街|道|镇|园|村|门)', addr):
            kws.add(p)
        for p in re.findall(r'[\u4e00-\u9fa5]{2,}(?:区|县|街道)', addr):
            kws.add(p)
        return kws
    
    matrix_kw = {loc: extract_keywords(str(loc)) for loc in matrix_locations}
    addr_map = {}
    unmatched = []
    
    for addr in orders_df['address_raw'].unique():
        if pd.isna(addr) or str(addr).strip() == '': continue
        addr_str = str(addr)
        addr_kw = extract_keywords(addr_str)
        if not addr_kw:
            unmatched.append(addr_str)
            continue
        
        best_match, best_score = None, 0
        for loc in matrix_locations:
            loc_kw = matrix_kw[loc]
            inter = len(addr_kw & loc_kw)
            union = len(addr_kw | loc_kw)
            jac = inter / union if union > 0 else 0
            bonus = sum(10 for k in addr_kw if len(k) >= 3 and k in str(loc).replace(' ', ''))
            bonus += sum(15 for k in addr_kw if len(k) >= 2 and k == str(loc).replace(' ', '')[-len(k):])
            score = jac * 100 + bonus
            if score > best_score:
                best_score = score
                best_match = loc
        
        if best_score >= 10:
            addr_map[addr_str] = best_match
        else:
            unmatched.append(addr_str)
    
    orders_df['matched_location'] = orders_df['address_raw'].map(addr_map)
    valid = orders_df.dropna(subset=['matched_location']).copy()
    print(f"  ✓ 匹配: {len(valid)}/{len(orders_df)}")
    
    if len(unmatched) > 0:
        print(f"  ⚠ 未匹配 {len(unmatched)} 个地址")
    
    return valid, depot_location


# ==================== 第三部分：阶段1 — 地理聚类（修复NaN）====================

def geographic_clustering(distance_df, depot_idx, n_clusters=None):
    """
    基于距离矩阵对目的地进行层次聚类
    
    修复：彻底处理NaN值
    """
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.preprocessing import StandardScaler
    from sklearn.manifold import MDS
    
    n = len(distance_df)
    locations = list(distance_df.index)
    
    # 获取距离数组（已确保无NaN）
    dist_array = distance_df.values.copy()
    
    # 双重确认无NaN
    if np.any(np.isnan(dist_array)):
        print("  ⚠ 距离矩阵仍有NaN，强制填充...")
        col_medians = np.nanmedian(dist_array, axis=0)
        for i in range(dist_array.shape[0]):
            for j in range(dist_array.shape[1]):
                if np.isnan(dist_array[i, j]):
                    dist_array[i, j] = col_medians[j] if not np.isnan(col_medians[j]) else 500
        dist_array[np.isnan(dist_array)] = 500
    
    # 确保对称
    dist_array = (dist_array + dist_array.T) / 2
    np.fill_diagonal(dist_array, 0)
    
    # ---- 构建特征矩阵 ----
    # 特征1：到仓库的距离
    dist_to_depot = dist_array[depot_idx, :].reshape(-1, 1)
    
    # 特征2-3：MDS降维
    mds = MDS(n_components=2, dissimilarity='precomputed', random_state=42,
              n_init=5, max_iter=300, normalized_stress='auto')
    try:
        coords = mds.fit_transform(dist_array)
    except Exception as e:
        print(f"  ⚠ MDS失败({e})，使用备用降维方案")
        # 备用方案：使用SVD
        from sklearn.decomposition import TruncatedSVD
        svd = TruncatedSVD(n_components=2, random_state=42)
        coords = svd.fit_transform(dist_array)
    
    # 检查coords是否有NaN
    if np.any(np.isnan(coords)):
        coords = np.nan_to_num(coords, nan=0.0)
    
    # 合并特征
    features = np.hstack([dist_to_depot, coords])
    
    # 最终NaN检查
    if np.any(np.isnan(features)):
        features = np.nan_to_num(features, nan=0.0)
    
    # 标准化
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)
    
    # ---- 自动确定最优簇数 ----
    if n_clusters is None:
        from sklearn.metrics import silhouette_score
        best_k, best_score = 2, -1
        max_k = min(15, max(3, n // 5))
        for k in range(2, max_k + 1):
            try:
                cluster = AgglomerativeClustering(n_clusters=k, linkage='ward')
                labels = cluster.fit_predict(features_scaled)
                if len(set(labels)) < 2: continue
                score = silhouette_score(features_scaled, labels, 
                                        sample_size=min(500, n))
                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception as e:
                continue
        n_clusters = best_k if best_score > -1 else 6
        print(f"  自动确定簇数: {n_clusters} (轮廓系数={best_score:.3f})")
    
    # ---- 最终聚类 ----
    try:
        cluster = AgglomerativeClustering(n_clusters=n_clusters, linkage='ward')
        labels = cluster.fit_predict(features_scaled)
    except Exception as e:
        print(f"  ⚠ AgglomerativeClustering失败({e})，使用KMeans")
        from sklearn.cluster import KMeans
        cluster = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = cluster.fit_predict(features_scaled)
    
    # ---- 找出每个簇的代表性地点 ----
    cluster_centers = {}
    for c in range(n_clusters):
        mask = labels == c
        cluster_locs = [locations[i] for i in range(n) if mask[i]]
        if len(cluster_locs) == 0:
            cluster_centers[c] = locations[0]
            continue
        best_loc = None
        best_dist = float('inf')
        for loc in cluster_locs:
            idx = distance_df.index.get_loc(loc)
            d = dist_array[depot_idx, idx]
            if d < best_dist:
                best_dist = d
                best_loc = loc
        cluster_centers[c] = best_loc
    
    # ---- 按距离仓库远近排序 ----
    cluster_order = sorted(range(n_clusters),
                          key=lambda c: dist_array[depot_idx, 
                                          distance_df.index.get_loc(cluster_centers[c])])
    old_to_new = {old: new for new, old in enumerate(cluster_order)}
    labels = np.array([old_to_new[l] for l in labels])
    cluster_centers = {new: cluster_centers[old] for new, old in enumerate(cluster_order)}
    
    print(f"\n  ✓ 聚类完成: {n_clusters} 个地理簇")
    for c in range(n_clusters):
        count = np.sum(labels == c)
        members = [locations[i] for i in range(n) if labels[i] == c][:5]
        avg_dist = np.mean([dist_array[depot_idx, distance_df.index.get_loc(l)] 
                           for l in members])
        print(f"    簇{c} ({count}地点, 平均距{avg_dist:.0f}km): {[m[:20] for m in members]}")
    
    return labels, cluster_centers, n_clusters, dist_array


# ==================== 第四部分：成本模型 ====================

class CostModel:
    VEHICLE_PARAMS = {
        '7.6M':  {'capacity': 11, 'var_cost_km': 2.4, 'fixed_cost_day': 1321},
        '9.6M':  {'capacity': 14, 'var_cost_km': 3.0, 'fixed_cost_day': 1550},
        '12.5M': {'capacity': 18, 'var_cost_km': 3.5, 'fixed_cost_day': 1800},
    }
    
    @classmethod
    def get_vehicle(cls, pallets):
        for vt in ['7.6M', '9.6M', '12.5M']:
            if pallets <= cls.VEHICLE_PARAMS[vt]['capacity']:
                return vt
        return '12.5M'
    
    @classmethod
    def compute_cost(cls, distance_km, time_hours, vehicle_type):
        p = cls.VEHICLE_PARAMS[vehicle_type]
        var_cost = distance_km * p['var_cost_km']
        days = max(1, np.ceil(time_hours / 24))
        fixed_cost = days * p['fixed_cost_day']
        return var_cost + fixed_cost
    
    @classmethod
    def single_order_cost(cls, distance_km, time_hours, pallets):
        vt = cls.get_vehicle(pallets)
        return cls.compute_cost(distance_km * 2, time_hours * 2 + 2, vt)


# ==================== 第五部分：阶段2求解器 ====================

def solve_cluster_vrp(cluster_orders, distance_df, duration_df, 
                      depot_idx, time_limit=15):
    """
    求解单个簇单周的VRP
    
    优先使用OR-Tools，不可用时回退贪心算法
    """
    n_orders = len(cluster_orders)
    if n_orders == 0:
        return [], 0
    
    depot = depot_idx
    
    # 获取每个订单的信息
    orders = []
    for i in range(n_orders):
        row = cluster_orders.iloc[i]
        loc = row['matched_location']
        try:
            idx = distance_df.index.get_loc(loc)
        except:
            continue
        d = distance_df.iloc[depot, idx]
        t = duration_df.iloc[depot, idx] / 60.0
        if pd.isna(d) or pd.isna(t) or d <= 0:
            continue
        orders.append({
            'idx': i, 'location': loc, 'pallets': row['pallets'],
            'dist': d, 'time': t, 'loc_idx': idx
        })
    
    if len(orders) == 0:
        return [], 0
    
    n = len(orders)
    
    # 尝试OR-Tools
    routes = None
    try:
        routes = _solve_ortools(orders, distance_df, duration_df, depot, time_limit)
    except Exception as e:
        pass
    
    # 回退贪心
    if routes is None:
        routes = _solve_greedy(orders, distance_df, duration_df, depot)
    
    return routes, sum(r['cost'] for r in routes)


def _solve_ortools(orders, distance_df, duration_df, depot, time_limit):
    """OR-Tools求解"""
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp
    
    n = len(orders)
    n_nodes = 1 + n
    
    # 构建距离和时间矩阵
    dist_mat = np.zeros((n_nodes, n_nodes))
    time_mat = np.zeros((n_nodes, n_nodes))
    
    for j, o in enumerate(orders):
        d = distance_df.iloc[depot, o['loc_idx']]
        t = duration_df.iloc[depot, o['loc_idx']]
        dist_mat[0, j+1] = d if not pd.isna(d) else 500
        dist_mat[j+1, 0] = d if not pd.isna(d) else 500
        time_mat[0, j+1] = t if not pd.isna(t) else 300
        time_mat[j+1, 0] = t if not pd.isna(t) else 300
    
    for i, oi in enumerate(orders):
        for j, oj in enumerate(orders):
            if i >= j: continue
            try:
                d_ij = distance_df.iloc[oi['loc_idx'], oj['loc_idx']]
                t_ij = duration_df.iloc[oi['loc_idx'], oj['loc_idx']]
                dist_mat[i+1, j+1] = d_ij if not pd.isna(d_ij) else oi['dist'] + oj['dist']
                dist_mat[j+1, i+1] = dist_mat[i+1, j+1]
                time_mat[i+1, j+1] = t_ij if not pd.isna(t_ij) else oi['time']*60 + oj['time']*60
                time_mat[j+1, i+1] = time_mat[i+1, j+1]
            except:
                dist_mat[i+1, j+1] = oi['dist'] + oj['dist']
                dist_mat[j+1, i+1] = dist_mat[i+1, j+1]
                time_mat[i+1, j+1] = (oi['time'] + oj['time']) * 60
                time_mat[j+1, i+1] = time_mat[i+1, j+1]
    
    demands = [0] + [int(max(1, np.ceil(o['pallets']))) for o in orders]
    total_demand = sum(demands)
    num_vehicles = max(1, min(n, int(np.ceil(total_demand / 14 * 1.3))))
    
    manager = pywrapcp.RoutingIndexManager(n_nodes, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    
    def dist_cb(from_idx, to_idx):
        return int(dist_mat[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)] * 1000)
    
    dist_idx = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(dist_idx)
    
    def demand_cb(from_idx):
        return demands[manager.IndexToNode(from_idx)]
    
    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [18]*num_vehicles, True, 'Capacity')
    
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = time_limit
    search_params.log_search = False
    
    solution = routing.SolveWithParameters(search_params)
    
    if solution is None:
        return None
    
    routes = []
    for v in range(num_vehicles):
        idx = routing.Start(v)
        route_nodes = []
        route_dist_m = 0
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node > 0:
                route_nodes.append(node - 1)
            prev = idx
            idx = solution.Value(routing.NextVar(idx))
            route_dist_m += routing.GetArcCostForVehicle(prev, idx, v)
        
        if route_nodes:
            route_dist_km = route_dist_m / 1000.0
            route_time_h = 0
            prev_node = 0
            for ni in route_nodes:
                route_time_h += time_mat[prev_node, ni+1] / 60.0 + 2
                prev_node = ni + 1
            route_time_h += time_mat[prev_node, 0] / 60.0
            
            pallets = sum(orders[i]['pallets'] for i in route_nodes)
            vehicle = CostModel.get_vehicle(pallets)
            cost = CostModel.compute_cost(route_dist_km, route_time_h, vehicle)
            
            routes.append({
                'location_names': [orders[i]['location'] for i in route_nodes],
                'pallets': pallets, 'total_distance': route_dist_km,
                'total_time': route_time_h, 'vehicle_type': vehicle,
                'cost': cost, 'n_stops': len(route_nodes),
            })
    
    return routes if routes else None


def _solve_greedy(orders, distance_df, duration_df, depot):
    """贪心算法回退方案"""
    orders_sorted = sorted(orders, key=lambda x: x['dist'])
    
    routes = []
    cur_orders, cur_pallets = [], 0
    
    for o in orders_sorted:
        if cur_pallets + o['pallets'] <= 18:
            cur_orders.append(o)
            cur_pallets += o['pallets']
        else:
            if cur_orders:
                routes.append(_build_route(cur_orders, distance_df, duration_df, depot))
            cur_orders, cur_pallets = [o], o['pallets']
    
    if cur_orders:
        routes.append(_build_route(cur_orders, distance_df, duration_df, depot))
    
    return routes


def _build_route(orders_in_route, distance_df, duration_df, depot):
    """构建路线详情"""
    sorted_orders = sorted(orders_in_route, key=lambda x: x['dist'])
    
    total_d, total_t = 0, 0
    prev = depot
    for o in sorted_orders:
        total_d += distance_df.iloc[prev, o['loc_idx']]
        total_t += duration_df.iloc[prev, o['loc_idx']] / 60.0
        prev = o['loc_idx']
    total_d += distance_df.iloc[prev, depot]
    total_t += duration_df.iloc[prev, depot] / 60.0
    total_t += len(sorted_orders) * 2
    
    pallets = sum(o['pallets'] for o in sorted_orders)
    vehicle = CostModel.get_vehicle(pallets)
    cost = CostModel.compute_cost(total_d, total_t, vehicle)
    
    return {
        'location_names': [o['location'] for o in sorted_orders],
        'pallets': pallets, 'total_distance': total_d,
        'total_time': total_t, 'vehicle_type': vehicle,
        'cost': cost, 'n_stops': len(sorted_orders),
    }


# ==================== 第六部分：主优化流程 ====================

def two_phase_optimization(valid_orders, distance_df, duration_df, depot_idx):
    """两阶段优化主流程"""
    
    # ---- 阶段1：地理聚类 ----
    print(f"\n{'='*60}")
    print("阶段1：地理聚类")
    print(f"{'='*60}")
    
    labels, cluster_centers, n_clusters, dist_array = geographic_clustering(
        distance_df, depot_idx, n_clusters=None
    )
    
    all_locations = list(distance_df.index)
    location_to_cluster = {loc: labels[i] for i, loc in enumerate(all_locations)}
    
    # 为订单分配簇
    valid_orders = valid_orders.copy()
    valid_orders['cluster'] = valid_orders['matched_location'].map(location_to_cluster)
    valid_orders['cluster'] = valid_orders['cluster'].fillna(0).astype(int)
    
    for c in range(n_clusters):
        count = len(valid_orders[valid_orders['cluster'] == c])
        n_dest = valid_orders[valid_orders['cluster'] == c]['matched_location'].nunique()
        print(f"  簇{c}: {count}条订单, {n_dest}个目的地")
    
    # 添加周列
    valid_orders['delivery_dt'] = pd.to_datetime(valid_orders['delivery_date'], errors='coerce')
    valid_orders['week'] = valid_orders['delivery_dt'].apply(
        lambda dt: f"{dt.year}-W{dt.isocalendar()[1]:02d}" if pd.notna(dt) else 'UNKNOWN'
    )
    
    # ---- 阶段2：簇内VRPTW求解 ----
    print(f"\n{'='*60}")
    print("阶段2：簇内VRPTW求解")
    print(f"{'='*60}")
    
    all_routes = []
    total_original = 0
    total_optimized = 0
    cluster_results = []
    
    for c in range(n_clusters):
        cluster_data = valid_orders[valid_orders['cluster'] == c]
        
        for week in sorted(cluster_data['week'].unique()):
            week_data = cluster_data[cluster_data['week'] == week]
            if len(week_data) == 0: continue
            
            # 按目的地聚合
            agg = week_data.groupby('matched_location').agg({
                'pallets': 'sum', 'time_limit': 'max'
            }).reset_index()
            agg = agg[agg['pallets'] >= 0.01]
            
            if len(agg) == 0: continue
            
            # 原始成本
            original_cost = 0
            for _, row in agg.iterrows():
                try:
                    idx = distance_df.index.get_loc(row['matched_location'])
                    d = distance_df.iloc[depot_idx, idx]
                    t = duration_df.iloc[depot_idx, idx] / 60.0
                    if not pd.isna(d) and not pd.isna(t) and d > 0:
                        original_cost += CostModel.single_order_cost(d, t, row['pallets'])
                except:
                    pass
            
            if original_cost == 0: continue
            
            # 求解
            routes, opt_cost = solve_cluster_vrp(agg, distance_df, duration_df, depot_idx)
            
            total_original += original_cost
            total_optimized += opt_cost
            all_routes.extend(routes)
            
            savings = original_cost - opt_cost
            pct = savings / original_cost * 100 if original_cost > 0 else 0
            
            cluster_results.append({
                'cluster': c, 'week': week,
                'n_groups': len(agg), 'n_routes': len(routes),
                'original_cost': original_cost, 'optimized_cost': opt_cost,
                'savings': savings, 'savings_pct': pct,
            })
            
            if len(routes) > 0 and pct > 0.5:
                marker = "***" if pct > 20 else ("**" if pct > 10 else "")
                print(f"  簇{c} {week}: {len(agg)}组→{len(routes)}路线 "
                      f"¥{original_cost:,.0f}→¥{opt_cost:,.0f} "
                      f"节约{pct:.1f}% {marker}")
    
    return {
        'all_routes': all_routes,
        'total_original': total_original,
        'total_optimized': total_optimized,
        'total_savings': total_original - total_optimized,
        'savings_pct': (total_original - total_optimized) / total_original * 100 
                      if total_original > 0 else 0,
        'cluster_results': cluster_results,
        'n_clusters': n_clusters,
    }


# ==================== 第七部分：C-W Baseline ====================

def baseline_cw_optimization(valid_orders, distance_df, duration_df, depot_idx):
    """对比Baseline：改进C-W节约算法"""
    print(f"\n{'='*60}")
    print("对比Baseline：改进C-W节约算法")
    print(f"{'='*60}")
    
    GEO_REGIONS = {
        '东北': ['哈尔滨', '长春', '吉林', '沈阳', '大连', '盘锦', '辽宁'],
        '华北': ['北京', '天津', '石家庄', '正定', '廊坊', '太原', '山西', '呼和浩特'],
        '华东': ['上海', '南京', '苏州', '无锡', '杭州', '宁波', '温州', '金华', 
                '义乌', '丽水', '衢州', '台州', '扬州', '南通', '绍兴', '嘉兴', '慈溪'],
        '山东': ['济南', '青岛', '烟台', '潍坊', '聊城', '淄博'],
        '华中': ['武汉', '郑州', '南昌', '长沙'],
        '西北': ['西安', '兰州', '乌鲁木齐', '银川', '西宁', '陕西', '甘肃', '青海', '新疆', '榆林', '汉中'],
        '西南': ['重庆', '成都', '昆明'],
    }
    
    def get_region(loc):
        for region, kws in GEO_REGIONS.items():
            for kw in kws:
                if kw in str(loc): return region
        return '其他'
    
    def same_or_adjacent(a, b):
        ra, rb = get_region(a), get_region(b)
        if ra == rb: return True
        adj = {('东北','华北'),('华北','山东'),('华北','西北'),
               ('华东','山东'),('华东','华中'),('华中','西北'),('华中','西南')}
        return (ra, rb) in adj or (rb, ra) in adj
    
    valid_orders = valid_orders.copy()
    valid_orders['delivery_dt'] = pd.to_datetime(valid_orders['delivery_date'], errors='coerce')
    valid_orders['week'] = valid_orders['delivery_dt'].apply(
        lambda dt: f"{dt.year}-W{dt.isocalendar()[1]:02d}" if pd.notna(dt) else 'UNKNOWN'
    )
    
    agg = valid_orders.groupby(['week', 'matched_location']).agg({
        'pallets': 'sum', 'time_limit': 'max'
    }).reset_index()
    
    total_original = 0
    total_optimized = 0
    
    for week in sorted(agg['week'].unique()):
        week_data = agg[agg['week'] == week].copy()
        
        orig = 0
        order_info = []
        for i, (_, row) in enumerate(week_data.iterrows()):
            try:
                idx = distance_df.index.get_loc(row['matched_location'])
                d = distance_df.iloc[depot_idx, idx]
                t = duration_df.iloc[depot_idx, idx] / 60.0
                if pd.isna(d) or pd.isna(t) or d <= 0: continue
                orig += CostModel.single_order_cost(d, t, row['pallets'])
                order_info.append({
                    'id': i, 'location': row['matched_location'],
                    'loc_idx': idx, 'pallets': row['pallets'],
                    'dist': d, 'time': t,
                })
            except: pass
        
        if orig == 0: continue
        
        n = len(order_info)
        savings_list = []
        for i in range(n):
            for j in range(i+1, n):
                oi, oj = order_info[i], order_info[j]
                try:
                    d_ij = distance_df.iloc[oi['loc_idx'], oj['loc_idx']]
                    if pd.isna(d_ij): d_ij = oi['dist'] + oj['dist']
                except:
                    d_ij = oi['dist'] + oj['dist']
                s = oi['dist'] + oj['dist'] - d_ij
                if not same_or_adjacent(oi['location'], oj['location']):
                    s *= 0.01
                savings_list.append({'i': i, 'j': j, 'savings': s,
                                     'combined': oi['pallets'] + oj['pallets']})
        
        savings_list.sort(key=lambda x: x['savings'], reverse=True)
        
        parent = list(range(n))
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(x, y):
            px, py = find(x), find(y)
            if px != py: parent[px] = py; return True
            return False
        
        for s in savings_list:
            i, j = s['i'], s['j']
            if find(i) == find(j): continue
            pi = sum(order_info[k]['pallets'] for k in range(n) if find(k) == find(i))
            pj = sum(order_info[k]['pallets'] for k in range(n) if find(k) == find(j))
            if pi + pj <= 18:
                union(i, j)
        
        routes_dict = defaultdict(list)
        for i in range(n):
            routes_dict[find(i)].append(i)
        
        opt = 0
        for root, indices in routes_dict.items():
            locs = [(order_info[k]['loc_idx'], order_info[k]['dist']) for k in indices]
            locs.sort(key=lambda x: x[1])
            
            total_d, total_t = 0, 0
            prev = depot_idx
            for loc, _ in locs:
                total_d += distance_df.iloc[prev, loc]
                total_t += duration_df.iloc[prev, loc] / 60.0
                prev = loc
            total_d += distance_df.iloc[prev, depot_idx]
            total_t += duration_df.iloc[prev, depot_idx] / 60.0
            total_t += len(locs) * 2
            
            pallets = sum(order_info[k]['pallets'] for k in indices)
            vehicle = CostModel.get_vehicle(pallets)
            opt += CostModel.compute_cost(total_d, total_t, vehicle)
        
        total_original += orig
        total_optimized += opt
        print(f"  {week}: {n}组→{len(routes_dict)}路线 ¥{orig:,.0f}→¥{opt:,.0f} "
              f"节约{(orig-opt)/orig*100:.1f}%")
    
    return {
        'total_original': total_original,
        'total_optimized': total_optimized,
        'total_savings': total_original - total_optimized,
        'savings_pct': (total_original - total_optimized) / total_original * 100 
                      if total_original > 0 else 0,
    }


# ==================== 第八部分：结果输出 ====================

def print_summary(results, method_name):
    print(f"\n{'='*70}")
    print(f"{method_name} - 结果汇总")
    print(f"{'='*70}")
    print(f"  原始总成本:  ¥{results['total_original']:,.2f}")
    print(f"  优化总成本:  ¥{results['total_optimized']:,.2f}")
    print(f"  节约金额:    ¥{results['total_savings']:,.2f}")
    print(f"  节约比例:    {results['savings_pct']:.1f}%")

    if 'all_routes' in results:
        print(f"  路线总数:    {len(results['all_routes'])}")
        # 车型统计
        vtypes = defaultdict(int)
        for r in results['all_routes']:
            vtypes[r['vehicle_type']] += 1
        print(f"  车型分布:    {dict(vtypes)}")


def export_results(results, method_name, output_path):
    with pd.ExcelWriter(output_path) as writer:
        if 'cluster_results' in results:
            pd.DataFrame(results['cluster_results']).to_excel(
                writer, sheet_name='簇周详情', index=False
            )
        
        if 'all_routes' in results:
            route_data = [{
                '路线编号': i + 1,
                '目的地': ' + '.join(r['location_names']),
                '停靠点数': r['n_stops'],
                '总托盘数': round(r['pallets'], 2),
                '车型': r['vehicle_type'],
                '总距离(km)': round(r['total_distance'], 1),
                '总时间(h)': round(r['total_time'], 1),
                '成本(元)': round(r['cost'], 2),
            } for i, r in enumerate(results['all_routes'])]
            pd.DataFrame(route_data).to_excel(writer, sheet_name='路线详情', index=False)
    
    print(f"  ✓ 结果已导出至 {output_path}")


def visualize_comparison(two_phase_results, cw_results, output_path="comparison.png"):
    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        matplotlib.rcParams['axes.unicode_minus'] = False
        
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        
        methods = ['两阶段法\n(聚类+OR-Tools)', '改进C-W算法\n(Baseline)']
        orig_costs = [two_phase_results['total_original'], cw_results['total_original']]
        opt_costs = [two_phase_results['total_optimized'], cw_results['total_optimized']]
        
        x = np.arange(len(methods))
        width = 0.3
        axes[0].bar(x - width/2, [c/10000 for c in orig_costs], width,
                    label='原始成本', color='#E74C3C', alpha=0.8)
        axes[0].bar(x + width/2, [c/10000 for c in opt_costs], width,
                    label='优化成本', color='#2ECC71', alpha=0.8)
        axes[0].set_ylabel('成本 (万元)')
        axes[0].set_title('成本对比')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(methods)
        axes[0].legend()
        
        savings = [two_phase_results['savings_pct'], cw_results['savings_pct']]
        axes[1].bar(methods, savings, color=['#3498DB', '#F39C12'])
        axes[1].set_ylabel('节约比例 (%)')
        axes[1].set_title('节约比例对比')
        for i, v in enumerate(savings):
            axes[1].text(i, v + 1, f'{v:.1f}%', ha='center', fontsize=12, fontweight='bold')
        
        n_routes = [len(two_phase_results.get('all_routes', [])), 
                    len(cw_results.get('all_routes', []))]
        axes[2].bar(methods, n_routes, color=['#9B59B6', '#1ABC9C'])
        axes[2].set_ylabel('路线数')
        axes[2].set_title('路线数对比')
        for i, v in enumerate(n_routes):
            if v > 0:
                axes[2].text(i, v + 1, str(v), ha='center', fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"\n  ✓ 对比图已保存至 {output_path}")
        plt.show()
    except Exception as e:
        print(f"  可视化失败: {e}")


# ==================== 第九部分：主程序 ====================

def main():
    print("=" * 70)
    print("医药物流拼车优化系统 - 问题2")
    print("两阶段算法：地理聚类 + OR-Tools VRPTW（修复版）")
    print("=" * 70)
    
    # 修正后的BASE路径
    BASE = "D:/OneDrive/大二下/数学建模/竞赛/28届华东杯/solver/"
    
    attachment2 = BASE + "附件2 排货信息表.xlsx"
    distance_file = BASE + "distance_matrix_fixed.xlsx"
    duration_file = BASE + "duration_matrix_fixed.xlsx"
    
    try:
        # 步骤1：加载数据
        print("\n正在加载数据...")
        orders_df = load_all_sheets_orders(attachment2)
        
        print("\n正在加载距离/时间矩阵...")
        distance_df = load_and_clean_matrix(distance_file)
        duration_df = load_and_clean_matrix(duration_file)
        
        # 步骤2：匹配地址
        valid_orders, depot_location = match_addresses(orders_df, distance_df)
        
        if len(valid_orders) == 0:
            raise ValueError("没有匹配到任何订单")
        
        depot_idx = 0
        
        # 步骤3：两阶段优化
        two_phase_results = two_phase_optimization(
            valid_orders, distance_df, duration_df, depot_idx
        )
        
        # 步骤4：Baseline对比
        cw_results = baseline_cw_optimization(
            valid_orders, distance_df, duration_df, depot_idx
        )
        
        # 步骤5：输出
        print_summary(two_phase_results, "两阶段法（聚类+OR-Tools）")
        print_summary(cw_results, "改进C-W算法（Baseline）")
        
        # 步骤6：最终结论
        print(f"\n{'='*70}")
        print("最终结论")
        print(f"{'='*70}")
        print(f"第一题运输总费用（已知）: ¥3,725,434.19")
        print(f"\n方案对比：")
        print(f"  两阶段法（聚类+OR-Tools）: ¥{two_phase_results['total_optimized']:,.2f} "
              f"(节约{two_phase_results['savings_pct']:.1f}%)")
        print(f"  改进C-W算法（Baseline）:    ¥{cw_results['total_optimized']:,.2f} "
              f"(节约{cw_results['savings_pct']:.1f}%)")
        
        # 步骤7：导出
        export_results(two_phase_results, "两阶段法",
                      BASE + "two_phase_results.xlsx")
        export_results(cw_results, "改进C-W",
                      BASE + "cw_baseline_results.xlsx")
        
        # 步骤8：可视化
        visualize_comparison(two_phase_results, cw_results,
                           BASE + "method_comparison.png")
        
        return two_phase_results, cw_results
        
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = main()
    
    if result is not None:
        two_phase, cw = result
        print(f"\n程序运行完成。")
        print(f"两阶段法总节约: ¥{two_phase['total_savings']:,.2f} ({two_phase['savings_pct']:.1f}%)")
        print(f"C-W基线总节约: ¥{cw['total_savings']:,.2f} ({cw['savings_pct']:.1f}%)")