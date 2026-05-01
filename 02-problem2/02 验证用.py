"""
医药物流拼单运输与车辆调度优化 - ALNS求解器（基于真实距离/时间矩阵）
问题2：带装卸货时间窗(9:00-17:00) + 多车型(7.6M/9.6M) + 拼单优化

数据来源：
  - distance_matrix.xlsx：城市间距离（km），对称矩阵
  - duration_matrix.xlsx：城市间行驶时间（分钟），对称矩阵
  - 附件2：排货信息表（订单数据）

使用方法：
  1. 将 distance_matrix.xlsx 和 duration_matrix.xlsx 放在同目录下
  2. 从附件2提取订单数据（可保存为CSV或直接在代码中配置）
  3. 运行：python med_logistics_optimizer.py
"""

import numpy as np
import pandas as pd
import math
import random
import copy
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set

# ============================================================================
# 第一部分：全局参数与常量
# ============================================================================

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

# 装卸货参数
SERVICE_TIME = 2.0          # 每次装卸货时间（小时）
WORK_START = 9.0            # 工作日开始时间
WORK_END = 17.0             # 工作日结束时间
WORK_LATEST_START = 15.0    # 最晚开始装卸时间（保证17:00前完成2h）

# ALNS参数
MAX_ITERATIONS = 8000       # 最大迭代次数
SEGMENT_SIZE = 100          # 每段迭代次数
INIT_TEMP_RATIO = 0.05      # 初始温度比例
COOLING_RATE = 0.997        # 降温速率
WEIGHT_UPDATE_RATE = 0.7    # 权重更新学习率

# 算子得分
SCORE_NEW_BEST = 30
SCORE_BETTER = 10
SCORE_ACCEPTED = 5
SCORE_REJECTED = 1

# 破坏算子参数
MIN_REMOVAL_RATIO = 0.10
MAX_REMOVAL_RATIO = 0.40
SHAW_REMOVAL_SIZE = 5

# ============================================================================
# 第二部分：车辆类型定义
# ============================================================================

@dataclass
class VehicleType:
    """冷藏车型参数（来自附件1）"""
    name: str
    capacity: int           # 可放托盘数
    var_cost_per_km: float  # 每公里变动成本（油耗+路桥费）
    fix_cost_per_day: float # 每日固定成本（人工+保险+折旧+维保等）


VEHICLE_TYPES = [
    VehicleType("7.6M", capacity=11, var_cost_per_km=2.4, fix_cost_per_day=1236.62),
    VehicleType("9.6M", capacity=14, var_cost_per_km=3.0, fix_cost_per_day=1276.59),
]


# ============================================================================
# 第三部分：真实距离/时间矩阵加载
# ============================================================================

class RealDistanceMatrix:
    """
    从Excel文件加载真实距离矩阵和时间矩阵
    distance_matrix.xlsx: 单位 km
    duration_matrix.xlsx: 单位 分钟
    """

    def __init__(self, distance_file: str, duration_file: str):
        print(f"  加载距离矩阵: {distance_file}")
        self.df_dist = pd.read_excel(distance_file, index_col=0)
        print(f"  加载时间矩阵: {duration_file}")
        self.df_time = pd.read_excel(duration_file, index_col=0)

        # 地址列表（矩阵的行/列标签）
        self.addresses = list(self.df_dist.index)
        self.n = len(self.addresses)
        self.addr_to_idx = {addr: i for i, addr in enumerate(self.addresses)}

        # 转换为numpy数组加速查询
        self.dist_array = self.df_dist.values.astype(float)    # km
        self.time_array = self.df_time.values.astype(float) / 60.0  # 转换为小时

        # 处理可能的NaN（府村路那一行全空 → 用0填充）
        self.dist_array = np.nan_to_num(self.dist_array, nan=0.0)
        self.time_array = np.nan_to_num(self.time_array, nan=0.0)

        print(f"  矩阵维度: {self.n} × {self.n}")
        print(f"  南通(起点)索引: 0")

    def get_distance_km(self, addr_i: str, addr_j: str) -> float:
        """查询两个地址之间的实际距离（km）"""
        i = self._resolve(addr_i)
        j = self._resolve(addr_j)
        return self.dist_array[i][j]

    def get_time_hours(self, addr_i: str, addr_j: str) -> float:
        """查询两个地址之间的行驶时间（小时）"""
        i = self._resolve(addr_i)
        j = self._resolve(addr_j)
        return self.time_array[i][j]

    def resolve_address(self, query_addr: str) -> str:
        """
        将订单中的收货地址匹配到矩阵中的标准地址。
        使用最长公共子串匹配策略。
        """
        # 先精确匹配
        for addr in self.addresses:
            if addr == query_addr or query_addr == addr:
                return addr

        # 再用包含匹配：如果查询地址包含在矩阵地址中，或反之
        best_addr = self.addresses[0]  # 默认南通
        best_len = 0

        for addr in self.addresses:
            # 提取关键地名进行匹配
            # 策略：看查询地址中有多少字符与矩阵地址重合
            common = 0
            for ch in query_addr:
                if ch in addr:
                    common += 1
            if common > best_len and addr != "南通市崇川区":
                best_len = common
                best_addr = addr

        # 再尝试关键词匹配
        keywords = ["太原", "杭州", "沈阳", "吉林", "长春", "天津", "济南", "北京",
                     "上海", "苏州", "无锡", "扬州", "南京", "宁波", "金华", "义乌",
                     "温州", "衢州", "丽水", "慈溪", "青岛", "潍坊", "烟台", "郑州",
                     "南昌", "武汉", "廊坊", "正定", "大连", "盘锦", "哈尔滨",
                     "呼和浩特", "西安", "兰州", "西宁", "银川", "重庆", "乌鲁木齐",
                     "萧山", "临海", "温岭", "汉中", "榆林", "聊城",
                     "龙盛街", "双塔寺", "五龙口", "白杨街道", "兴华南街", "新生街",
                     "工农大路", "空港物流", "北辰区", "美里路", "罗而村", "马连道",
                     "金豫路", "藏龙岛", "广平大街", "107国道", "雪莲街", "机场北街",
                     "土主镇", "盛乐园区", "长春南路", "西彩路", "双峪路", "机场路",
                     "罗平道", "看丹乡", "桥南区块", "健康东街", "广水路", "开封路",
                     "经北三路", "经南五路", "港务大道", "火炬大街", "全兴路",
                     "中长街", "超强街", "越达路", "火炬路", "珠海路", "祝科街",
                     "康宁路", "绥德路", "复兴街", "大众街", "运河北路", "金山路",
                     "香山路", "金园路", "西津西路", "白堤路", "南莲路", "创力大厦",
                     "红垦农场", "建章路", "天水北路", "康乐路", "花马东街", "河韵路",
                     "中粮路", "太平南路", "将军大道", "黑庄户", "益盛路", "安通九道街",
                     "安道街", "环城东路", "春晖路", "松北大道", "富源路", "经二路",
                     "西山西街", "开源路", "浦东北路", "殷华街", "滨海十九路",
                     "潘桥街道", "汇丰南路", "科技路", "商都路", "金岱工业园",
                     "第九大街", "货站街", "客车有限公司", "北皂河村", "康定街",
                     "凤城七路", "工艺路", "工业二路", "文昌南路", "超群街",
                     "开发区路", "府村路", "族昌路", "浦川路", "银岭路", "虎滩路",
                     "瑞泰路", "罗幕村", "辛寨子镇", "北展街", "丰产路西段",
                     "傍海南路", "玉屏西大街", "星驰路"]
        for kw in keywords:
            if kw in query_addr:
                for addr in self.addresses:
                    if kw in addr and addr != "南通市崇川区":
                        return addr
        return best_addr

    def _resolve(self, addr: str) -> int:
        return self.addr_to_idx.get(addr, 0)

    def get_origin_idx(self) -> int:
        return 0

    def get_origin_addr(self) -> str:
        return self.addresses[0]


# ============================================================================
# 第四部分：订单数据类
# ============================================================================

@dataclass
class Order:
    """订单信息"""
    order_id: str
    address: str           # 原始收货地址（附件2中的地址）
    standard_addr: str     # 匹配后的标准矩阵地址
    pallets: float
    earliest_arrival: float
    latest_arrival: float

    # 以下由求解器注入
    dm: 'RealDistanceMatrix' = None

    @property
    def dist_from_origin(self) -> float:
        if self.dm is None:
            return 0.0
        return self.dm.get_distance_km(self.dm.get_origin_addr(), self.standard_addr)

    @property
    def time_from_origin(self) -> float:
        if self.dm is None:
            return 0.0
        return self.dm.get_time_hours(self.dm.get_origin_addr(), self.standard_addr)


@dataclass
class Route:
    """一条配送路线"""
    orders: List[Order] = field(default_factory=list)
    vehicle_type: VehicleType = None
    departure_time: float = 0.0

    @property
    def total_pallets(self) -> float:
        return sum(o.pallets for o in self.orders)

    def copy(self) -> 'Route':
        return Route(
            orders=list(self.orders),
            vehicle_type=self.vehicle_type,
            departure_time=self.departure_time,
        )


@dataclass
class Solution:
    """完整解"""
    routes: List[Route] = field(default_factory=list)

    @property
    def num_vehicles(self) -> int:
        return len(self.routes)

    @property
    def total_cost(self) -> float:
        return sum(self._route_cost(r) for r in self.routes)

    def _route_cost(self, route: Route) -> float:
        if not route.orders or route.vehicle_type is None:
            return 0.0
        dm = route.orders[0].dm
        total_dist = 0.0
        current = dm.get_origin_addr()
        for o in route.orders:
            total_dist += dm.get_distance_km(current, o.standard_addr)
            current = o.standard_addr
        total_dist += dm.get_distance_km(current, dm.get_origin_addr())
        var_cost = total_dist * route.vehicle_type.var_cost_per_km
        days = self._calc_route_days(route)
        fix_cost = days * route.vehicle_type.fix_cost_per_day
        return var_cost + fix_cost

    def _calc_route_days(self, route: Route) -> int:
        if not route.orders:
            return 0
        dm = route.orders[0].dm
        t = route.departure_time
        hour = t % 24
        if hour > WORK_LATEST_START:
            t = math.ceil(t / 24) * 24 + WORK_START
        elif hour < WORK_START:
            t = math.floor(t / 24) * 24 + WORK_START
        t += SERVICE_TIME
        current = dm.get_origin_addr()
        for o in route.orders:
            t += dm.get_time_hours(current, o.standard_addr)
            hour = t % 24
            if hour > WORK_LATEST_START:
                t = math.ceil(t / 24) * 24 + WORK_START
            elif hour < WORK_START:
                t = math.floor(t / 24) * 24 + WORK_START
            t += SERVICE_TIME
            current = o.standard_addr
        t += dm.get_time_hours(current, dm.get_origin_addr())
        return max(1, math.ceil((t - route.departure_time) / 24))

    def copy(self) -> 'Solution':
        return Solution(routes=[r.copy() for r in self.routes])


# ============================================================================
# 第五部分：路线可行性检查
# ============================================================================

def check_route_feasibility(route: Route) -> Tuple[bool, float, List[float]]:
    """
    检查路线可行性（使用真实矩阵时间）
    返回: (是否可行, 总成本, [开始卸货时间列表])
    """
    if not route.orders or route.vehicle_type is None:
        return False, float('inf'), []
    dm = route.orders[0].dm

    t = route.departure_time
    hour = t % 24
    if hour > WORK_LATEST_START:
        t = math.ceil(t / 24) * 24 + WORK_START
    elif hour < WORK_START:
        t = math.floor(t / 24) * 24 + WORK_START
    t += SERVICE_TIME

    current = dm.get_origin_addr()
    total_dist = 0.0
    arrival_times = []

    for o in route.orders:
        travel_time = dm.get_time_hours(current, o.standard_addr)
        total_dist += dm.get_distance_km(current, o.standard_addr)
        t += travel_time

        hour = t % 24
        if hour > WORK_LATEST_START:
            t = math.ceil(t / 24) * 24 + WORK_START
        elif hour < WORK_START:
            t = math.floor(t / 24) * 24 + WORK_START

        t_start = t
        t += SERVICE_TIME

        if t > o.latest_arrival:
            return False, float('inf'), []

        arrival_times.append(t_start)
        current = o.standard_addr

    total_dist += dm.get_distance_km(current, dm.get_origin_addr())

    var_cost = total_dist * route.vehicle_type.var_cost_per_km
    days = max(1, math.ceil((t - route.departure_time) / 24))
    fix_cost = days * route.vehicle_type.fix_cost_per_day

    return True, var_cost + fix_cost, arrival_times


def check_feasibility_simple(route: Route) -> bool:
    ok, _, _ = check_route_feasibility(route)
    return ok


# ============================================================================
# 第六部分：初始解构造 - 改进Clarke-Wright节约算法
# ============================================================================

def construct_initial_solution(orders: List[Order]) -> Solution:
    dm = orders[0].dm
    origin = dm.get_origin_addr()

    # 分离正常订单（≤14托）和超大订单（>14托）
    normal_orders = []
    oversized_orders = []
    for o in orders:
        if o.pallets <= VEHICLE_TYPES[1].capacity:  # ≤14托
            normal_orders.append(o)
        else:
            oversized_orders.append(o)

    n = len(normal_orders)
    if n == 0:
        # 全是大订单，各自独立成路
        all_routes = []
        for o in oversized_orders:
            # 拆分超大订单（每车最多14托）
            remaining = o.pallets
            while remaining > 0:
                batch = min(remaining, VEHICLE_TYPES[1].capacity)
                sub_order = Order(o.order_id, o.address, o.standard_addr,
                                  batch, o.earliest_arrival, o.latest_arrival, dm=dm)
                all_routes.append(Route(orders=[sub_order],
                                        vehicle_type=VEHICLE_TYPES[1],
                                        departure_time=0.0))
                remaining -= batch
        return Solution(routes=all_routes)

    # 步骤1：每个正常订单独立成路
    routes = []
    for o in normal_orders:
        vt = VEHICLE_TYPES[0] if o.pallets <= VEHICLE_TYPES[0].capacity else VEHICLE_TYPES[1]
        r = Route(orders=[o], vehicle_type=vt, departure_time=0.0)
        routes.append(r)

    # 步骤2：计算节约值（仅正常订单之间）
    savings = []
    for i in range(n):
        for j in range(i + 1, n):
            oi, oj = normal_orders[i], normal_orders[j]
            d_save = (dm.get_distance_km(origin, oi.standard_addr) +
                      dm.get_distance_km(origin, oj.standard_addr) -
                      dm.get_distance_km(oi.standard_addr, oj.standard_addr))
            time_ok = abs(oi.latest_arrival - oj.latest_arrival) < 72
            if d_save > 0 and time_ok:
                savings.append((d_save, i, j))

    savings.sort(key=lambda x: x[0], reverse=True)

    # 步骤3：合并路线
    active_routes = list(range(len(routes)))
    route_of_order = list(range(n))

    for _, i, j in savings:
        ra = route_of_order[i]
        rb = route_of_order[j]
        if ra == rb:
            continue

        ri = active_routes[ra]
        rj = active_routes[rb]
        route_i = routes[ri]
        route_j = routes[rj]

        if route_i is None or route_j is None:
            continue

        merged_pallets = route_i.total_pallets + route_j.total_pallets
        best_vt = None
        for vt in VEHICLE_TYPES:
            if merged_pallets <= vt.capacity:
                best_vt = vt
                break
        if best_vt is None:
            continue

        best_cost = float('inf')
        best_route = None
        for orders_seq in [route_i.orders + route_j.orders,
                            route_j.orders + route_i.orders]:
            temp = Route(orders=list(orders_seq), vehicle_type=best_vt,
                         departure_time=0.0)
            ok, cost, _ = check_route_feasibility(temp)
            if ok and cost < best_cost:
                best_cost = cost
                best_route = temp

        if best_route is not None:
            routes[ri] = best_route
            routes[rj] = None
            for k in range(n):
                if route_of_order[k] == rb:
                    route_of_order[k] = ra
                elif route_of_order[k] > rb:
                    route_of_order[k] -= 1
            active_routes.pop(rb)

    # 过滤掉已合并的路线
    routes = [r for r in routes if r is not None]

    # 步骤4：优化车型
    for r in routes:
        best_cost = float('inf')
        best_vt = r.vehicle_type
        for vt in VEHICLE_TYPES:
            if r.total_pallets <= vt.capacity:
                temp = Route(orders=list(r.orders), vehicle_type=vt,
                             departure_time=0.0)
                ok, cost, _ = check_route_feasibility(temp)
                if ok and cost < best_cost:
                    best_cost = cost
                    best_vt = vt
        r.vehicle_type = best_vt

    # 步骤5：处理超大订单（拆分后独立成路）
    for o in oversized_orders:
        remaining = o.pallets
        while remaining > 0:
            batch = min(remaining, VEHICLE_TYPES[1].capacity)
            sub_order = Order(o.order_id, o.address, o.standard_addr,
                              batch, o.earliest_arrival, o.latest_arrival, dm=dm)
            routes.append(Route(orders=[sub_order],
                                vehicle_type=VEHICLE_TYPES[1],
                                departure_time=0.0))
            remaining -= batch

    return Solution(routes=routes)


# ============================================================================
# 第七部分：局部搜索算子
# ============================================================================

def local_search_2opt(route: Route) -> Route:
    if len(route.orders) < 3:
        return route
    best = route.copy()
    ok, best_cost, _ = check_route_feasibility(best)
    if not ok:
        return route
    improved = True
    while improved:
        improved = False
        n = len(best.orders)
        for i in range(n - 1):
            for j in range(i + 2, n + 1):
                new_orders = (best.orders[:i] +
                              list(reversed(best.orders[i:j])) +
                              best.orders[j:])
                temp = Route(orders=new_orders, vehicle_type=best.vehicle_type,
                             departure_time=best.departure_time)
                ok2, cost, _ = check_route_feasibility(temp)
                if ok2 and cost < best_cost - 0.01:
                    best = temp
                    best_cost = cost
                    improved = True
                    break
            if improved:
                break
    return best


def local_search_relocate(solution: Solution) -> Solution:
    best = solution.copy()
    best_cost = best.total_cost
    improved = True
    while improved:
        improved = False
        for ri, route_i in enumerate(best.routes):
            for oi_idx, oi in enumerate(route_i.orders):
                for rj, route_j in enumerate(best.routes):
                    if ri == rj:
                        continue
                    for pos in range(len(route_j.orders) + 1):
                        new_i_orders = [o for k, o in enumerate(route_i.orders) if k != oi_idx]
                        new_j_orders = route_j.orders[:pos] + [oi] + route_j.orders[pos:]

                        if len(new_i_orders) == 0:
                            continue
                        total_i = sum(o.pallets for o in new_i_orders)
                        total_j = sum(o.pallets for o in new_j_orders)

                        vt_i, vt_j = route_i.vehicle_type, route_j.vehicle_type
                        if total_i > vt_i.capacity or total_j > vt_j.capacity:
                            continue

                        temp_i = Route(orders=new_i_orders, vehicle_type=vt_i,
                                       departure_time=route_i.departure_time)
                        temp_j = Route(orders=new_j_orders, vehicle_type=vt_j,
                                       departure_time=route_j.departure_time)
                        ok_i, _, _ = check_route_feasibility(temp_i)
                        ok_j, _, _ = check_route_feasibility(temp_j)
                        if ok_i and ok_j:
                            new_routes = list(best.routes)
                            new_routes[ri] = temp_i
                            new_routes[rj] = temp_j
                            new_sol = Solution(routes=new_routes)
                            new_cost = new_sol.total_cost
                            if new_cost < best_cost - 0.01:
                                best = new_sol
                                best_cost = new_cost
                                improved = True
                                break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
    return best


def optimize_vehicle_types(solution: Solution) -> Solution:
    for r in solution.routes:
        best_cost = float('inf')
        best_vt = r.vehicle_type
        for vt in VEHICLE_TYPES:
            if r.total_pallets <= vt.capacity:
                temp = Route(orders=list(r.orders), vehicle_type=vt,
                             departure_time=r.departure_time)
                ok, cost, _ = check_route_feasibility(temp)
                if ok and cost < best_cost:
                    best_cost = cost
                    best_vt = vt
        r.vehicle_type = best_vt
    return solution


def full_local_search(solution: Solution) -> Solution:
    s = solution.copy()
    s = optimize_vehicle_types(s)
    for i, r in enumerate(s.routes):
        s.routes[i] = local_search_2opt(r)
    s = local_search_relocate(s)
    s = optimize_vehicle_types(s)
    return s


# ============================================================================
# 第八部分：ALNS破坏算子
# ============================================================================

def _remove_orders(solution: Solution, removed: List[Order]) -> Solution:
    removed_ids = set(id(o) for o in removed)
    new_routes = []
    for r in solution.routes:
        remaining = [o for o in r.orders if id(o) not in removed_ids]
        if len(remaining) > 0:
            new_routes.append(Route(orders=remaining, vehicle_type=r.vehicle_type,
                                    departure_time=r.departure_time))
    return Solution(routes=new_routes)


def destroy_random(solution: Solution, random_state: random.Random
                   ) -> Tuple[Solution, List[Order]]:
    all_orders = [o for r in solution.routes for o in r.orders]
    n = len(all_orders)
    if n == 0:
        return solution, []
    ratio = random_state.uniform(MIN_REMOVAL_RATIO, MAX_REMOVAL_RATIO)
    n_remove = max(1, int(n * ratio))
    removed = random_state.sample(all_orders, n_remove)
    return _remove_orders(solution, removed), removed


def destroy_worst(solution: Solution, random_state: random.Random
                  ) -> Tuple[Solution, List[Order]]:
    all_orders_with_cost = []
    for r in solution.routes:
        for i, o in enumerate(r.orders):
            remaining = [x for j, x in enumerate(r.orders) if j != i]
            if len(remaining) == 0:
                saving = float('inf')
            else:
                temp = Route(orders=remaining, vehicle_type=r.vehicle_type,
                             departure_time=r.departure_time)
                ok, new_cost, _ = check_route_feasibility(temp)
                saving = (solution._route_cost(r) - new_cost) if ok else float('inf')
            all_orders_with_cost.append((o, saving))

    all_orders_with_cost.sort(key=lambda x: x[1], reverse=True)
    n = len(all_orders_with_cost)
    n_remove = max(1, int(n * random_state.uniform(MIN_REMOVAL_RATIO, MAX_REMOVAL_RATIO)))
    removed = [x[0] for x in all_orders_with_cost[:n_remove]]
    return _remove_orders(solution, removed), removed


def destroy_shaw(solution: Solution, random_state: random.Random
                 ) -> Tuple[Solution, List[Order]]:
    dm = solution.routes[0].orders[0].dm if solution.routes else None
    if dm is None:
        return solution, []

    all_orders = [o for r in solution.routes for o in r.orders]
    if len(all_orders) <= SHAW_REMOVAL_SIZE:
        return destroy_random(solution, random_state)

    seed = random_state.choice(all_orders)
    similarities = []
    for o in all_orders:
        if o is seed:
            continue
        time_sim = abs(o.latest_arrival - seed.latest_arrival) / max(
            abs(x.latest_arrival - seed.latest_arrival) for x in all_orders) if all_orders else 1
        dist_sim = dm.get_distance_km(o.standard_addr, seed.standard_addr) / max(
            dm.get_distance_km(x.standard_addr, seed.standard_addr) for x in all_orders) if all_orders else 1
        similarities.append((o, 0.4 * time_sim + 0.4 * dist_sim + 0.2 * (o.standard_addr != seed.standard_addr)))

    similarities.sort(key=lambda x: x[1])
    n_remove = min(SHAW_REMOVAL_SIZE, len(similarities))
    removed = [seed] + [x[0] for x in similarities[:n_remove - 1]]
    return _remove_orders(solution, removed), removed


def destroy_route(solution: Solution, random_state: random.Random
                  ) -> Tuple[Solution, List[Order]]:
    if len(solution.routes) == 0:
        return solution, []
    ri = random_state.randint(0, len(solution.routes) - 1)
    removed = list(solution.routes[ri].orders)
    new_routes = [r for i, r in enumerate(solution.routes) if i != ri]
    return Solution(routes=new_routes), removed


def destroy_time_based(solution: Solution, random_state: random.Random
                       ) -> Tuple[Solution, List[Order]]:
    all_orders = [o for r in solution.routes for o in r.orders]
    if len(all_orders) <= 1:
        return solution, []
    seed = random_state.choice(all_orders)
    time_diffs = [(o, abs(o.latest_arrival - seed.latest_arrival)) for o in all_orders if o is not seed]
    time_diffs.sort(key=lambda x: x[1])
    ratio = random_state.uniform(MIN_REMOVAL_RATIO, MAX_REMOVAL_RATIO)
    n_remove = max(1, int(len(all_orders) * ratio))
    removed = [seed] + [x[0] for x in time_diffs[:n_remove - 1]]
    return _remove_orders(solution, removed), removed


# ============================================================================
# 第九部分：ALNS修复算子
# ============================================================================

def _find_best_insertion(order: Order, sol: Solution
                         ) -> Optional[Tuple[int, int, VehicleType, float]]:
    best_cost = float('inf')
    best = None
    for ri, route in enumerate(sol.routes):
        for pos in range(len(route.orders) + 1):
            new_orders = route.orders[:pos] + [order] + route.orders[pos:]
            total_p = sum(o.pallets for o in new_orders)
            for vt in VEHICLE_TYPES:
                if total_p <= vt.capacity:
                    temp = Route(orders=new_orders, vehicle_type=vt,
                                 departure_time=route.departure_time)
                    ok, cost, _ = check_route_feasibility(temp)
                    if ok and cost < best_cost:
                        best_cost = cost
                        best = (ri, pos, vt, cost)
    return best


def _find_all_insertions(order: Order, sol: Solution
                         ) -> List[Tuple[int, int, VehicleType, float]]:
    results = []
    for ri, route in enumerate(sol.routes):
        for pos in range(len(route.orders) + 1):
            new_orders = route.orders[:pos] + [order] + route.orders[pos:]
            total_p = sum(o.pallets for o in new_orders)
            for vt in VEHICLE_TYPES:
                if total_p <= vt.capacity:
                    temp = Route(orders=new_orders, vehicle_type=vt,
                                 departure_time=route.departure_time)
                    ok, cost, _ = check_route_feasibility(temp)
                    if ok:
                        results.append((ri, pos, vt, cost))
    results.sort(key=lambda x: x[3])
    return results


def repair_greedy(partial_solution: Solution, removed: List[Order],
                  random_state: random.Random) -> Solution:
    sol = partial_solution.copy()
    remaining = list(removed)
    random_state.shuffle(remaining)
    for o in remaining:
        best = _find_best_insertion(o, sol)
        if best is not None:
            ri, pos, vt, _ = best
            sol.routes[ri].orders.insert(pos, o)
            sol.routes[ri].vehicle_type = vt
        else:
            vt = VEHICLE_TYPES[0] if o.pallets <= VEHICLE_TYPES[0].capacity else VEHICLE_TYPES[1]
            sol.routes.append(Route(orders=[o], vehicle_type=vt, departure_time=0.0))
    return sol


def repair_regret_k(partial_solution: Solution, removed: List[Order],
                    k: int, random_state: random.Random) -> Solution:
    sol = partial_solution.copy()
    remaining = set(id(o) for o in removed)
    order_map = {id(o): o for o in removed}

    while remaining:
        best_regret = -1
        best_oid = None
        best_action = None

        for oid in list(remaining):
            o = order_map[oid]
            insertions = _find_all_insertions(o, sol)
            if len(insertions) == 0:
                vt = VEHICLE_TYPES[0] if o.pallets <= VEHICLE_TYPES[0].capacity else VEHICLE_TYPES[1]
                regret = float('inf')
                if regret > best_regret:
                    best_regret = regret
                    best_oid = oid
                    best_action = ('new', vt)
            elif len(insertions) == 1:
                if 10 > best_regret:
                    best_regret = 10
                    best_oid = oid
                    best_action = ('insert', insertions[0])
            else:
                costs = [ins[3] for ins in insertions[:k + 1]]
                regret = sum(costs[1:k + 1]) - k * costs[0] if len(costs) >= k + 1 else 10
                if regret > best_regret:
                    best_regret = regret
                    best_oid = oid
                    best_action = ('insert', insertions[0])

        if best_oid is None:
            break
        remaining.remove(best_oid)
        if best_action[0] == 'new':
            sol.routes.append(Route(orders=[order_map[best_oid]], vehicle_type=best_action[1],
                                    departure_time=0.0))
        else:
            ri, pos, vt, _ = best_action[1]
            sol.routes[ri].orders.insert(pos, order_map[best_oid])
            sol.routes[ri].vehicle_type = vt
    return sol


def repair_regret2(partial_solution: Solution, removed: List[Order],
                   random_state: random.Random) -> Solution:
    return repair_regret_k(partial_solution, removed, 2, random_state)


def repair_regret3(partial_solution: Solution, removed: List[Order],
                   random_state: random.Random) -> Solution:
    return repair_regret_k(partial_solution, removed, 3, random_state)


# ============================================================================
# 第十部分：ALNS主框架
# ============================================================================

class ALNS:
    def __init__(self, random_seed: int = 42):
        self.random_state = random.Random(random_seed)
        self.destroy_ops = [
            ("Random", destroy_random),
            ("Worst", destroy_worst),
            ("Shaw", destroy_shaw),
            ("Route", destroy_route),
            ("Time", destroy_time_based),
        ]
        self.repair_ops = [
            ("Greedy", repair_greedy),
            ("Regret-2", repair_regret2),
            ("Regret-3", repair_regret3),
        ]
        self.d_weights = [1.0] * len(self.destroy_ops)
        self.r_weights = [1.0] * len(self.repair_ops)
        self.d_scores = [0.0] * len(self.destroy_ops)
        self.r_scores = [0.0] * len(self.repair_ops)
        self.d_counts = [0] * len(self.destroy_ops)
        self.r_counts = [0] * len(self.repair_ops)

    def _select(self, weights: List[float]) -> int:
        total = sum(weights)
        r = self.random_state.uniform(0, total)
        cumsum = 0
        for i, w in enumerate(weights):
            cumsum += w
            if r <= cumsum:
                return i
        return len(weights) - 1

    def _update_weights(self):
        for i in range(len(self.destroy_ops)):
            if self.d_counts[i] > 0:
                self.d_weights[i] = ((1 - WEIGHT_UPDATE_RATE) * self.d_weights[i] +
                                     WEIGHT_UPDATE_RATE * self.d_scores[i] / self.d_counts[i])
        for i in range(len(self.repair_ops)):
            if self.r_counts[i] > 0:
                self.r_weights[i] = ((1 - WEIGHT_UPDATE_RATE) * self.r_weights[i] +
                                     WEIGHT_UPDATE_RATE * self.r_scores[i] / self.r_counts[i])
        self.d_scores = [0.0] * len(self.destroy_ops)
        self.r_scores = [0.0] * len(self.repair_ops)
        self.d_counts = [0] * len(self.destroy_ops)
        self.r_counts = [0] * len(self.repair_ops)

    def solve(self, initial_solution: Solution,
              max_iterations: int = MAX_ITERATIONS,
              verbose: bool = True) -> Tuple[Solution, List[float]]:

        current = initial_solution.copy()
        current = full_local_search(current)
        best = current.copy()
        best_cost = best.total_cost
        current_cost = best_cost

        T = max(1.0, best_cost * INIT_TEMP_RATIO)
        cost_history = [best_cost]
        best_iter = 0

        if verbose:
            print(f"  初始解: {best.num_vehicles}辆车, 总成本={best_cost:,.2f}元")
            print(f"  初始温度 T={T:.2f}")

        for iteration in range(max_iterations):
            di = self._select(self.d_weights)
            ri = self._select(self.r_weights)
            d_name, d_op = self.destroy_ops[di]
            r_name, r_op = self.repair_ops[ri]

            partial, removed = d_op(current, self.random_state)
            if len(removed) == 0:
                continue

            candidate = r_op(partial, removed, self.random_state)
            candidate = full_local_search(candidate)
            candidate_cost = candidate.total_cost

            self.d_counts[di] += 1
            self.r_counts[ri] += 1

            if candidate_cost < best_cost:
                best = candidate.copy()
                best_cost = candidate_cost
                current = candidate.copy()
                current_cost = candidate_cost
                best_iter = iteration
                self.d_scores[di] += SCORE_NEW_BEST
                self.r_scores[ri] += SCORE_NEW_BEST
            elif candidate_cost < current_cost:
                current = candidate.copy()
                current_cost = candidate_cost
                self.d_scores[di] += SCORE_BETTER
                self.r_scores[ri] += SCORE_BETTER
            else:
                delta = candidate_cost - current_cost
                prob = math.exp(-delta / T) if T > 0 else 0
                if self.random_state.random() < prob:
                    current = candidate.copy()
                    current_cost = candidate_cost
                    self.d_scores[di] += SCORE_ACCEPTED
                    self.r_scores[ri] += SCORE_ACCEPTED
                else:
                    self.d_scores[di] += SCORE_REJECTED
                    self.r_scores[ri] += SCORE_REJECTED

            cost_history.append(best_cost)
            T *= COOLING_RATE

            if (iteration + 1) % SEGMENT_SIZE == 0:
                self._update_weights()

            if verbose and (iteration + 1) % 1000 == 0:
                print(f"  Iter {iteration+1}/{max_iterations}: "
                      f"当前={current_cost:,.0f}, 最优={best_cost:,.0f}, T={T:.1f}")

        if verbose:
            print(f"\n  优化完成! 最优解在迭代{best_iter}发现")
            improvement = (cost_history[0] - best_cost) / cost_history[0] * 100
            print(f"  最优: {best.num_vehicles}辆车, 总成本={best_cost:,.2f}元")
            print(f"  相比初始解节约: {improvement:.1f}%")

        return best, cost_history


# ============================================================================
# 第十一部分：订单数据解析
# ============================================================================

def parse_order_data(dm: RealDistanceMatrix) -> List[Order]:
    """
    从附件2提取订单数据。
    按照「运输交接单号」聚合为独立的配送订单。
    """
    # 示例数据（从附件2手动提取的核心订单，含托盘数和时间窗）
    raw_orders = [
        # (交接单号, 托盘数汇总, 地址原始文本, 预计到货日期, 运输时效天数)
        ("20180903-19", 11.16, "山西综改示范区太原唐槐园区龙盛街", "2018/9/6", 2),
        ("20180903-18", 16.67, "太原市双塔寺街1", "2018/9/6", 2),
        ("20180903-22", 2.89, "太原市五龙口南街东华苑桐荫A段", "2018/9/7", 3),
        ("20180903-24", 18.75, "杭州市经济技术开发区白杨街道1大街32", "2018/9/5", 1),
        ("201809-15-GY", 8.22, "沈阳市铁西区兴华南街5", "2018/9/14", 3),
        ("201809-14-GY", 2.22, "吉林市船营区新生街7", "2018/9/15", 4),
        ("201809-13-GY", 1.07, "长春市工农大路153", "2018/9/16", 5),
        ("20180911-17-GY", 33.34, "天津市空港物流加工区东八道5", "2018/9/14", 2),
        ("20180911-15-GY", 11.11, "天津滨海新区空港物流加工区环河南路8场院内6幢北楼二层、南楼一层", "2018/9/14", 2),
        ("20180911-16-GY", 11.16, "天津市北辰区科技园区泾河道", "2018/9/14", 2),
        ("20180912-05-GY", 12.74, "济南市槐荫区美里路108", "2018/9/14", 1),
        ("20180912-06-GY", 12.41, "济南市市中区党家街道办事处罗而村东北150米处", "2018/9/14", 1),
        ("20180912-07-GY", 14.02, "北京市西城区广外马连道东街1", "2018/9/15", 2),
        ("20180912-04-GY", 3.33, "金豫路82", "2018/9/14", 1),
        ("20180912-10-GY", 4.81, "武汉市江夏区经济开发区藏龙岛科技园凤凰大道1", "2018/9/15", 2),
        ("20180912-08-GY", 8.50, "北京市大兴区大兴经济开发区广平大街", "2018/9/15", 2),
        ("20180912-09-GY", 16.66, "正定县107国道东侧", "2018/9/15", 2),
        ("20180917-01-GY", 6.09, "沈阳市苏家屯区雪莲街158-", "2018/9/20", 2),
        ("20180917-03-GY", 6.11, "北京市顺义区机场北街1院6幢", "2018/9/20", 2),
        ("20180917-04-GY", 11.48, "重庆市沙坪坝区土主镇远怀路重庆医药现代物流综合基地", "2018/9/20", 2),
        ("20180917-05-GY", 2.78, "呼和浩特市和林县盛乐园区盛乐北六街", "2018/9/20", 2),
        ("20180917-06-GY", 5.60, "乌鲁木齐市高新技术开发区长春南路119", "2018/9/23", 5),
        ("20180917-06-GY-B", 36.90, "乌鲁木齐市高新区西彩路58", "2018/9/22", 4),
        ("20180917-08-GY", 13.89, "北京市石景山区双峪路4", "2018/9/20", 2),
        ("20181008-01-GY", 9.69, "烟台市芝罘区机场路32", "2018/10/9", 1),
        ("20181008-02-GY", 11.11, "天津市南开区罗平道1", "2018/10/10", 2),
        ("20181008-03-GY", 11.54, "山西综改示范区太原唐槐园区龙盛街", "2018/10/10", 2),
        ("20181008-04-GY", 14.44, "北京市丰台区看丹乡杨树庄看杨路10", "2018/10/10", 2),
        ("20181010-02-GY", 18.88, "杭州市经济技术开发区白杨街道1大街32", "2018/10/12", 1),
        ("20181010-03-GY", 6.67, "萧山区萧山经济技术开发区桥南区块春水路", "2018/10/12", 1),
        ("20181010-01-GY", 8.53, "潍坊市健康东街甲19", "2018/10/12", 1),
        ("20181011-01-GY", 17.29, "太原市双塔寺街1", "2018/10/14", 2),
        ("20181011-02-GY", 11.40, "天津滨海新区空港物流加工区环河南路8场院内6幢北楼二层、南楼一层", "2018/10/14", 2),
        ("20181011-03-GY", 16.96, "天津市北辰区科技园区泾河道", "2018/10/14", 2),
        ("20181011-04-GY", 33.33, "天津市空港物流加工区东八道5", "2018/10/14", 2),
        ("20181012-01-GY", 12.36, "济南市槐荫区美里路108", "2018/10/14", 1),
        ("20181012-02-GY", 7.26, "青岛市李沧区广水路61一楼、二楼、四楼", "2018/10/14", 1),
        ("20181012-03-GY", 10.80, "青岛市市北区开封路8楼1、2层", "2018/10/14", 1),
        ("20181012-04-GY", 13.88, "北京市石景山区双峪路4", "2018/10/15", 2),
        ("20181012-05-GY", 14.69, "北京市大兴区大兴经济开发区广平大街", "2018/10/15", 2),
        ("20181012-06-GY", 4.33, "郑州市经济技术开发区经北三路10", "2018/10/14", 1),
        ("20181012-07-GY", 17.28, "郑州市经济技术开发区经南五路18", "2018/10/14", 1),
        ("20181012-08-GY", 29.16, "西安国际港务区港务大道8", "2018/10/15", 2),
        ("20181012-09-GY", 8.74, "沈阳市苏家屯区雪莲街158-", "2018/10/16", 3),
        ("20181012-10-GY", 2.50, "南昌市高新开发区火炬大街62", "2018/10/14", 1),
    ]

    orders = []
    base_hour = _date_to_hours("2018/9/1")

    for (oid, pallets, addr, arrival_str, transit_days) in raw_orders:
        std_addr = dm.resolve_address(addr)
        latest = _date_to_hours(arrival_str) - base_hour
        earliest = latest - transit_days * 24
        orders.append(Order(
            order_id=oid, address=addr, standard_addr=std_addr,
            pallets=pallets, earliest_arrival=earliest, latest_arrival=latest,
            dm=dm
        ))

    return orders


def _date_to_hours(date_str: str) -> float:
    parts = date_str.strip().split("/")
    month, day = int(parts[1]), int(parts[2])
    return (month - 9) * 30 * 24 + (day - 1) * 24


# ============================================================================
# 第十二部分：结果输出
# ============================================================================

def print_solution(solution: Solution, dm: RealDistanceMatrix):
    print("\n" + "=" * 80)
    print("最优拼单配送方案")
    print("=" * 80)

    for i, route in enumerate(solution.routes):
        vt = route.vehicle_type
        print(f"\n路线 {i+1}: {vt.name} (容量{vt.capacity}托, "
              f"装载{route.total_pallets:.1f}托, 利用率{route.total_pallets/vt.capacity*100:.0f}%)")

        ok, cost, arrivals = check_route_feasibility(route)
        print(f"  成本: {cost:,.2f}元")

        current = dm.get_origin_addr()
        total_dist = 0.0
        for j, o in enumerate(route.orders):
            d = dm.get_distance_km(current, o.standard_addr)
            total_dist += d
            arr = arrivals[j] if j < len(arrivals) else 0
            day, hour = int(arr // 24), arr % 24
            print(f"    → {o.standard_addr[:30]}: {o.pallets:.1f}托, "
                  f"{d:.0f}km, D+{day} {hour:.0f}:00, [{o.order_id}]")
            current = o.standard_addr
        d_back = dm.get_distance_km(current, dm.get_origin_addr())
        total_dist += d_back
        print(f"    → 返回南通: {d_back:.0f}km | 总里程: {total_dist:.0f}km")

    print(f"\n总计: {solution.num_vehicles}辆车, 总成本={solution.total_cost:,.2f}元")
    print("=" * 80)


def compare_with_baseline(opt_solution: Solution, baseline: float):
    opt = opt_solution.total_cost
    saving = baseline - opt
    pct = saving / baseline * 100
    print(f"\n┌──────────────────────────────────────┐")
    print(f"│ 原方案(问题1估算): {baseline:>12,.0f} 元        │")
    print(f"│ 拼单优化方案:      {opt:>12,.0f} 元        │")
    print(f"│ 节约金额:          {saving:>12,.0f} 元        │")
    print(f"│ 节约比例:          {pct:>11.1f}%           │")
    print(f"│ 优化后车辆数:      {opt_solution.num_vehicles:>11} 辆          │")
    print(f"└──────────────────────────────────────┘")


# ============================================================================
# 主程序
# ============================================================================

def main():
    print("=" * 80)
    print("医药物流拼单运输优化 - ALNS求解器（真实距离矩阵版）")
    print("问题2：装卸货时间窗(9-17h) + 多车型 + 拼单优化")
    print("=" * 80)

    # 1. 加载距离/时间矩阵
    print("\n[1] 加载距离和时间矩阵...")
    dm = RealDistanceMatrix("distance_matrix.xlsx", "duration_matrix.xlsx")

    # 2. 解析订单数据
    print("\n[2] 解析订单数据...")
    orders = parse_order_data(dm)
    print(f"  共加载 {len(orders)} 个配送订单")
    for o in orders[:5]:
        print(f"    {o.order_id}: {o.pallets:.1f}托 → {o.standard_addr[:40]} "
              f"[{o.earliest_arrival:.0f}h, {o.latest_arrival:.0f}h]")
    if len(orders) > 5:
        print(f"    ... 共{len(orders)}个订单")

    # 3. 构造初始解
    print("\n[3] 构造初始解 (Clarke-Wright + 真实矩阵)...")
    t0 = time.time()
    initial = construct_initial_solution(orders)
    print(f"  初始解: {initial.num_vehicles}辆车, 成本={initial.total_cost:,.2f}元")

    # 4. ALNS优化
    print(f"\n[4] ALNS优化 (最多{MAX_ITERATIONS}次迭代)...")
    alns = ALNS(random_seed=RANDOM_SEED)
    best, history = alns.solve(initial, max_iterations=MAX_ITERATIONS, verbose=True)

    elapsed = time.time() - t0
    print(f"\n  求解耗时: {elapsed:.1f}秒")

    # 5. 输出
    print_solution(best, dm)

    # 6. 对比基准（问题1≈208.5万元）
    compare_with_baseline(best, 2084646.0)

    return best, history


if __name__ == "__main__":
    best_solution, history = main()