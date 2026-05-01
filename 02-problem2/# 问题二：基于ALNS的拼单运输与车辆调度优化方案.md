## 🤖 Assistant

# 问题二：基于ALNS的拼单运输与车辆调度优化方案

---

## 第一部分：数学建模

### 1. 问题描述与参数定义

#### 1.1 集合定义

| 符号 | 含义 |
|------|------|
| $\mathcal{N} = \{1, 2, \ldots, n\}$ | 所有订单的集合 |
| $\mathcal{K}$ | 可用车辆集合（车辆数量可视为无限，按需调用） |
| $\mathcal{V} = \{1, 2\}$ | 车辆类型：1=7.6M冷藏车(11托)，2=9.6M冷藏车(14托) |
| $\mathcal{D}$ | 所有目的地城市的集合 |
| $0$ | 南通仓库（发车起点与终点） |

#### 1.2 订单参数

对于每个订单 $i \in \mathcal{N}$：

| 符号 | 含义 | 来源 |
|------|------|------|
| $q_i$ | 托盘需求量 | 附件2托盘数列求和 |
| $[E_i - \tau_i, \, E_i]$ | 到货时间窗（硬约束） | $E_i$=预计到货日期，$\tau_i$=运输时效 |
| $city_i$ | 目的地城市 | 附件2收货方地址 |
| $t_{0,i}$ | 从南通到订单i目的地的行驶时间(h) | 基于距离和平均车速估算 |
| $service\_time = 2$ | 每次装卸货服务时间(小时) | 题目给定 |

#### 1.3 车辆参数

对于车辆类型 $v \in \mathcal{V}$：

| 符号 | 7.6M (v=1) | 9.6M (v=2) | 含义 |
|------|-----------|-----------|------|
| $Q_v$ | 11 | 14 | 最大装载托盘数 |
| $c_v^{var}$ | 2.4 | 3.0 | 每公里变动成本(元/km) |
| $c_v^{fix}$ | 1,236.62 | 1,276.59 | 每日固定成本(元/天) |

#### 1.4 装卸货时间窗

- 装卸货必须在 **9:00–17:00**（即每日的第9小时到第17小时，以0点为基准）
- 每次装卸货需 **2小时**，因此一个完整操作窗口需在客户处占用 $[9, 15]$ 时间段开始，至 $[11, 17]$ 结束
- 如果到达时间晚于15:00，则当天无法完成2小时的装卸，需等待至次日9:00

---

### 2. 决策变量

| 变量 | 类型 | 含义 |
|------|------|------|
| $x_{ijk}$ | $\{0,1\}$ | 车辆 $k$ 是否从节点 $i$ 行驶到节点 $j$ |
| $y_{ik}$ | $\{0,1\}$ | 订单 $i$ 是否由车辆 $k$ 配送 |
| $z_{kv}$ | $\{0,1\}$ | 车辆 $k$ 是否为类型 $v$ |
| $t_i^{arr}$ | $\mathbb{R}^+$ | 车辆到达订单 $i$ 目的地的时间（按小时计算的绝对时间） |
| $t_i^{start}$ | $\mathbb{R}^+$ | 开始为订单 $i$ 卸货的时间 |
| $t_0^{dep,k}$ | $\mathbb{R}^+$ | 车辆 $k$ 从南通仓库出发的时间 |
| $t_0^{ret,k}$ | $\mathbb{R}^+$ | 车辆 $k$ 返回南通仓库的时间 |

---

### 3. 目标函数

$$\min \; Z = \sum_{k \in \mathcal{K}} \left[ \sum_{v \in \mathcal{V}} z_{kv} \cdot c_v^{var} \cdot \sum_{i \in \mathcal{N} \cup \{0\}} \sum_{j \in \mathcal{N} \cup \{0\}} d_{ij} \cdot x_{ijk} \; + \; c_v^{fix} \cdot \left\lceil\frac{t_0^{ret,k} - t_0^{dep,k}}{24}\right\rceil \right]$$

其中：
- 第一项：**变动成本** = 车型对应每公里成本 × 总行驶距离
- 第二项：**固定成本** = 车型对应每日固定成本 × 车辆使用天数（向上取整）

---

### 4. 约束条件

#### （1）每个订单必须被配送

$$\sum_{k \in \mathcal{K}} y_{ik} = 1, \quad \forall i \in \mathcal{N}$$

#### （2）车辆容量约束

$$\sum_{i \in \mathcal{N}} q_i \cdot y_{ik} \leq \sum_{v \in \mathcal{V}} Q_v \cdot z_{kv}, \quad \forall k \in \mathcal{K}$$

#### （3）每车只能选一种车型

$$\sum_{v \in \mathcal{V}} z_{kv} = 1, \quad \forall k \in \mathcal{K}$$

#### （4）流量守恒

$$\sum_{j \in \mathcal{N} \cup \{0\}} x_{ijk} = y_{ik}, \quad \forall i \in \mathcal{N}, \forall k \in \mathcal{K}$$

$$\sum_{i \in \mathcal{N} \cup \{0\}} x_{ijk} = y_{jk}, \quad \forall j \in \mathcal{N}, \forall k \in \mathcal{K}$$

$$\sum_{j \in \mathcal{N}} x_{0jk} = 1, \quad \forall k \in \mathcal{K} \text{ 被使用}$$

$$\sum_{i \in \mathcal{N}} x_{i0k} = 1, \quad \forall k \in \mathcal{K} \text{ 被使用}$$

#### （5）到货时间窗约束（硬约束）

$$E_i - \tau_i \leq t_i^{start} + 2 \leq E_i, \quad \forall i \in \mathcal{N}$$

这里 $t_i^{start} + 2$ 是卸货完成时间，必须在预计到货日期 $E_i$ 当天或之前，且不早于最早可到货时间。

#### （6）装卸货工作时间窗约束（核心约束）

对于订单 $i$，其卸货必须在9:00–17:00进行：

$$9 \leq (t_i^{start} \bmod 24) \leq 15$$

即开始卸货的时钟时间必须在 $[9, 15]$ 之间（保证在17:00前完成2小时卸货）。如果到达时间晚于15:00，需等待到下一日9:00。

$$\text{若 } (t_i^{arr} \bmod 24) > 15, \text{则 } t_i^{start} = \left\lceil \frac{t_i^{arr}}{24} \right\rceil \times 24 + 9$$

$$\text{若 } (t_i^{arr} \bmod 24) < 9, \text{则 } t_i^{start} = \left\lfloor \frac{t_i^{arr}}{24} \right\rfloor \times 24 + 9$$

$$\text{否则 } t_i^{start} = t_i^{arr}$$

#### （7）时间连续性约束

$$t_j^{arr} \geq t_i^{start} + 2 + t_{ij} - M(1 - x_{ijk}), \quad \forall i,j \in \mathcal{N}, \forall k$$

其中 $t_{ij}$ 是从城市 $city_i$ 到 $city_j$ 的行驶时间。

#### （8）仓库出发时间约束（装货时间）

车辆在南通仓库出发前需要2小时装货（同样限制在9:00–17:00）：

$$9 \leq (t_0^{dep,k} \bmod 24) \leq 15$$

---

### 5. 问题分解策略

由于订单分布时间段较长（两个多月），直接求解全局最优极为困难。我们采用**滚动时间窗分解**：

1. 将所有订单按 $E_i - \tau_i$（最早可发货日）排序
2. 以 **周** 为单位划分求解窗口
3. 每周的订单构成一个子问题（约10-30个订单）
4. 车辆在完成当周任务后可滚动到下一周

这样每个子问题的规模在ALNS可高效求解的范围内。

---

## 第二部分：ALNS算法设计

### 1. 解的表示

一个完整的解 $\mathcal{S}$ 表示为一组路径的集合：

$$\mathcal{S} = \{R_1, R_2, \ldots, R_m\}$$

每条路径 $R_k$ 包含：
- 车辆类型 $v_k \in \{1,2\}$
- **有序的订单序列** $\pi_k = [i_1, i_2, \ldots, i_{n_k}]$（配送顺序）
- 发车时间 $t_0^{dep,k}$

例如：
```
R1: [7.6M] 南通 → 订单3(上海) → 订单7(苏州) → 订单12(无锡) → 南通
R2: [9.6M] 南通 → 订单5(北京) → 订单18(天津) → 南通
```

### 2. 初始解构造：改进节约里程法

#### 步骤一：计算节约值

对任意两个订单 $i, j$，若合并到同一辆车可节约的成本为：

$$s_{ij} = c_v^{var} \cdot (d_{0i} + d_{0j} - d_{ij}) + c_v^{fix} \cdot \Delta T_{saved}$$

其中 $\Delta T_{saved}$ 为合并后节约的车辆使用天数。

还需检查 **时间窗兼容性**：

$$\text{compatible}(i,j) = 
\begin{cases} 
1, & \text{如果可以在满足所有时间窗约束下按顺序配送 } i \rightarrow j \\
0, & \text{否则}
\end{cases}$$

#### 步骤二：构造路线

```
1. 每个订单初始为独立路线（直达往返）
2. 按节约值 s_{ij} 降序排列所有订单对
3. 依次合并兼容的路线，直到无法继续节约
4. 对每条路线选择成本最低的可行车型
```

### 3. ALNS主框架

```
输入: 初始解 S_init, 最大迭代次数 N_max
输出: 最优解 S_best

1. S ← S_init, S_best ← S_init
2. 初始化破坏算子权重 w^- = [1, 1, ..., 1]
3. 初始化修复算子权重 w^+ = [1, 1, ..., 1]
4. 温度 T ← T_init

5. For iter = 1 to N_max:
   a. 根据权重轮盘赌选择一个破坏算子 d 和一个修复算子 r
   b. S' ← r(d(S))   // 先破坏再修复
   c. 对 S' 进行局部搜索精炼 (2-opt + relocate)
   d. 如果 f(S') < f(S):
        S ← S'
        更新算子得分 score[d] += σ1, score[r] += σ1
        如果 f(S') < f(S_best): S_best ← S'
   e. 否则:
        以概率 p = exp(-(f(S') - f(S)) / T) 接受 S'
        如果接受: S ← S', 更新得分 += σ2
        否则: 更新得分 += σ3
   f. 每 N_seg 次迭代后更新权重并重置得分
   g. T ← α · T  (降温)

6. 返回 S_best
```

### 4. 破坏算子设计（5种）

| 算子名称 | 描述 | 移除比例 |
|---------|------|---------|
| **Random Removal** | 随机移除 $\rho$ 比例的订单 | $\rho \sim U(0.1, 0.4)$ |
| **Worst Removal** | 移除成本节约最大的订单（从当前路线移除后成本下降最多），倾向于拆分低效路线 | $\rho$ |
| **Shaw Removal** | 移除最"相似"的一组订单（同城市 + 同时段），促进重新组合 | $n_{shaw}$ 个 |
| **Route Removal** | 随机移除整条路线（清空一条低效路径） | 1条路线 |
| **Time-based Removal** | 移除到达时间窗最接近的一组订单（便于时间优化） | $\rho$ |

**Shaw Removal 的相似度定义：**

$$relatedness(i,j) = \alpha \cdot \frac{|E_i - E_j|}{\max\_diff} + \beta \cdot \frac{dist(city_i, city_j)}{\max\_dist} + \gamma \cdot \mathbf{1}[city_i \neq city_j]$$

### 5. 修复算子设计（3种）

| 算子名称 | 描述 |
|---------|------|
| **Greedy Insertion** | 每次以最小成本增量插入一个被移除的订单，在所有可行位置中选择成本最低的 |
| **Regret-2 Insertion** | 考虑"后悔值"：订单插入最佳位置与次佳位置的成本差，优先插入后悔值最大的订单 |
| **Regret-3 Insertion** | 同上，考虑最佳、次佳、第三佳位置的后悔值 |

**Regret-k 插入公式：**

$$regret\_k(i) = \sum_{j=2}^{k} (\Delta f_{i}^{(j)} - \Delta f_{i}^{(1)})$$

其中 $\Delta f_i^{(j)}$ 是订单 $i$ 插入到第 $j$ 优位置时的成本增量。优先插入后悔值最大的订单。

### 6. 局部搜索算子

在每次破坏-修复后，对解进行局部搜索精炼：

| 算子 | 操作 |
|------|------|
| **2-opt** | 对每条路径内部进行2-opt交换消除交叉 |
| **Or-opt** | 将1-3个连续订单移动到同路径的其他位置 |
| **Relocate** | 将一个订单从当前路径移动到另一条路径 |
| **Exchange** | 交换两条路径中的两个订单 |
| **Vehicle-type change** | 尝试将路径的车型从7.6M改为9.6M或反之（检查容量+成本） |

### 7. 自适应权重更新

每 $N_{seg} = 100$ 次迭代更新一次算子权重：

$$w_d^{new} = (1 - \lambda) \cdot w_d^{old} + \lambda \cdot \frac{score_d}{\sum score}$$

其中 $\lambda = 0.7$ 为学习率，得分规则：

| 得分类型 | 条件 | 分值 |
|---------|------|------|
| $\sigma_1$ | 发现新的全局最优解 | 30 |
| $\sigma_2$ | 接受了一个改进解 | 10 |
| $\sigma_3$ | 接受了一个劣解（通过SA准则） | 5 |

### 8. 接受准则与冷却策略

采用模拟退火接受准则：

$$P_{accept} = \exp\left(-\frac{f(S') - f(S)}{T}\right)$$

- 初始温度 $T_0$ 设定为初始解成本的5%
- 冷却速率 $\alpha = 0.997$
- 每1000次迭代降温一次

### 9. 终止条件

- 最大迭代次数：$N_{max} = 25,000$
- 或连续5,000次迭代未改进最优解

---

## 第三部分：约束可行性检查（核心）

在修复算子和局部搜索中，最关键的组件是**路径可行性检查**。给定一条路径 $\pi = [i_1, i_2, \ldots, i_m]$ 和出发时间 $t_0^{dep}$：

```python
def check_feasibility(route, departure_time, vehicle_type):
    """
    检查一条路径是否满足所有约束
    返回: (feasible, total_cost, arrival_times)
    """
    t = departure_time  # 从南通出发的时间（绝对小时）
    total_distance = 0
    
    # 仓库装货（2小时，必须在9:00-17:00）
    if not (9 <= t % 24 <= 15):
        return (False, inf, None)
    t += 2  # 装货完成
    
    current_location = "南通"
    
    for order in route:
        # 行驶到下一个目的地
        travel_time = get_travel_time(current_location, order.city)
        total_distance += get_distance(current_location, order.city)
        t += travel_time
        
        # 检查并调整至装卸货窗口
        hour_of_day = t % 24
        if hour_of_day > 15:  # 当天来不及卸货，等到明天
            t = ceil(t / 24) * 24 + 9
        elif hour_of_day < 9:  # 太早到达，等待到9点
            t = floor(t / 24) * 24 + 9
        
        # 卸货2小时
        t_start = t
        t += 2
        
        # 检查到货时间窗：完成卸货时间 <= E_i
        if t > order.E_i:  # 超过预计到货日期
            return (False, inf, None)
        
        current_location = order.city
    
    # 返回南通
    travel_time = get_travel_time(current_location, "南通")
    total_distance += get_distance(current_location, "南通")
    t += travel_time
    
    # 计算成本
    var_cost = total_distance * vehicle_type.var_cost_per_km
    days_used = ceil((t - departure_time) / 24)
    fix_cost = days_used * vehicle_type.fix_cost_per_day
    total_cost = var_cost + fix_cost
    
    return (True, total_cost, arrival_info)
```

---

## 第四部分：预期优化效果

### 4.1 拼单优化空间分析

从附件2数据中可以识别以下优化机会：

**场景一：同城同日多订单合并**

以9月3日太原为例：
- 订单20180903-19（7.00+4.11+0.05=11.16托）→ 太原唐槐园区
- 订单20180903-18（11.22+0.01+5.44=16.67托）→ 太原双塔寺街

现状：使用2辆7.6M车
优化：使用2辆9.6M车（14托+14托），或2辆7.6M车拼车（若11.16+5.45≈16.61托可用1辆9.6M+1辆7.6M）

**场景二：同方向顺路拼载**

以华北方向为例，北京-天津-廊坊-正定这些城市在一条运输走廊上。一辆车可以沿途卸货：
```
南通 → 正定 → 天津 → 北京 → 廊坊 → 南通
```

这比4辆车独立往返节约大量里程。

### 4.2 预期成本节约

| 优化方向 | 预期节约 |
|---------|---------|
| 同城同日合并 | 10-15% |
| 同方向顺路拼载 | 15-25% |
| 车型优化选择 | 5-10% |
| 发车时间优化（减少等待） | 3-5% |
| **综合预期** | **25-40%** |

即在问题1的208.5万元基础上，优化后预期降至 **125-156万元**。

---

## 第五部分：算法实现伪代码

```
Algorithm: ALNS for Medical Cold-chain VRP with Consolidation

1. 数据预处理:
   - 提取所有订单（按运输交接单号聚合）
   - 计算城市间距离矩阵和行驶时间矩阵
   - 确定每个订单的时间窗 [E_i - τ_i, E_i]

2. 构造初始解:
   S ← Clarke-Wright_Savings_With_TimeWindows()
   S ← Local_Search(S)

3. ALNS主循环:
   S_best ← S
   初始化算子权重
   
   For seg = 1 to N_segments:
      For iter = 1 to segment_size:
         d ← Select_Destroy_Operator()
         r ← Select_Repair_Operator()
         S' ← r(d(S))
         S' ← Local_Search(S')
         
         If Accept(S', S, T):
            S ← S'
            Update_Scores(d, r, S')
            If f(S') < f(S_best):
               S_best ← S'
      
      更新算子权重
      T ← α × T

4. 输出 S_best
```

---

## 总结

本方案的核心要点：

1. **数学建模**：建立了带装卸货时间窗的多车型VRP精确模型，目标函数综合考虑变动成本（距离）和固定成本（天数），约束条件完整覆盖容量、时间窗、流量守恒。

2. **ALNS算法**：采用5种破坏算子（Random/Worst/Shaw/Route/Time-based）和3种修复算子（Greedy/Regret-2/Regret-3），配合自适应权重调整和模拟退火接受准则，在全局搜索与局部精炼之间取得平衡。

3. **可行性检查**：装卸货时间窗（9:00-17:00，2小时）的处理是核心难点，通过时间离散化和等待策略实现了高效检查。

4. **预期效果**：相比问题1的直发模式，拼单优化预计可节约25-40%的运输成本。
