# Infinigen Indoor 电梯测试报告

日期：2026-07-10

## 结论

当前证据支持以下结论：

- 主电梯聚焦批次为 `88 passed, 2 skipped`；隔离 OpenUSD
  25.5.1 环境的 `pxr` 批次为 `14 passed`；广泛
  constraints/gins/export 回归为 `120 passed, 1 skipped`。
- 固定四层 static、固定八层 static 和随机四层 static 都为
  `19/19 PASS`；固定四层 animated 为 `20/20 PASS`。
- 随机四层 seed token `302` 已使用可配置最小 `8 m × 8 m`
  楼梯核心和逐层增量 staircase stack 完成 coarse，不再是旧报告中
  `KeyError: 12` 的失败状态。
- 默认禁用路径的 canonical A/B 为 `PASS`：`MaskTag.json` 和
  `solve_state.json` 相同，数值最大差为 0。
- 真实 Infinigen 四层静态建筑 USD 已导出并与独立
  articulation 组合。独立 articulation 合规检查为 0 errors/0
  failed checks；完整 wrapper 可打开，但不声称它的
  ComplianceChecker 为 0/0，因为 base 建筑材质检查受当前环境
  影响。
- F2 离线开门 target 已通过 `pxr` 重开核对：门的非零开门
  target 只属于两扇轿门和两扇 F2 层门，其他层门保持关闭。
- Isaac Sim GUI、Timeline、Play 和 PhysX 实际往返运动仍为
  `NOT RUN`。因此本报告不能作为“电梯已在 Isaac 中物理运行”
  或真实安全认证的证据。

## 状态定义

| 状态 | 含义 |
|---|---|
| `PASS` | 命令或等价自动测试已实际执行并满足断言 |
| `FAIL` | 命令已实际执行并以确定错误结束 |
| `SKIP` | 测试被环境条件明确跳过，不计为 PASS |
| `NOT RUN` | 没有端到端执行证据；不能写成 PASS 或 FAIL |

## 最终测试矩阵

| 层级 | 场景 | 结果 | 关键证据 | 该结果不证明什么 |
|---|---|---:|---|---|
| 主聚焦测试 | 电梯模型、Blender、manifest、runtime、工具 | `88 passed, 2 skipped` | 当前主环境聚焦批次 | skip 不是 PASS，也不证明 PhysX 运动 |
| OpenUSD 测试 | 真实 `pxr` schema、author、runtime、compliance | `14 passed` | OpenUSD 25.5.1 隔离环境 | 不运行 Physics step |
| 广泛回归 | constraints、gin、export 及关联路径 | `120 passed, 1 skipped` | 广泛回归批次 | 不是所有 seed/config 的穷尽证明 |
| 默认禁用 A/B | baseline repeat 对 candidate final | `PASS` | 2 个 JSON 同名匹配，无缺失/多余，数值最大差 0 | 只证明该 canonical seed/config |
| 固定四层 static | aligned fixed coarse | `19/19 PASS` | validator 0 failed、0 global errors | 不证明 Isaac 运动 |
| 固定八层 static | fixed8 coarse、seed token `303` | `19/19 PASS` | 总用时约 `1:50`，7 段原生楼梯 | 不证明随机八层 |
| 随机四层 static | random floor plan、seed token `302`、core8 | `19/19 PASS` | 总用时约 `7:40`，3 段原生楼梯 | 不证明所有随机 seed 都可解 |
| 固定四层 animated | 整楼动画 coarse | `20/20 PASS` | frame `1..543`，轿厢/门/状态曲线验收通过 | 是离线关键帧，不是物理反馈 |
| Blender 动画 USD | 动画 `.blend` 的 USD 导出 | `PASS` | 65 elevator-named prims、12 animated xforms、time `1..543` | 不是 articulation，不执行 PhysX |
| 渲染输出 | F1 开门帧 | `PASS` | PNG 已写出 | 不等于系统性视觉质量评审 |
| 真实建筑 USD | 固定四层 static export + articulation wrapper | `PASS` | 导出时删除 60 个 role object，wrapper 可打开 | 不声称完整 wrapper compliance 0/0 |
| 独立 articulation | 四层单梯 | `PASS` | 1 root、12 rigid、11 prismatic、1 fixed、11 drive；compliance 0/0 | 不证明 PhysX 稳定 |
| F2 离线控制 | 真实 wrapper 上写入对层开门 target | `PASS` | 只有轿门 + F2 层门获得开门 target | 写 target 不等于门真实开合 |
| Isaac GUI/timeline | 打开 wrapper、Play、观察 articulation | `NOT RUN` | 无 Isaac 运行记录 | 无法声称 Isaac 兼容性已验收 |
| Isaac PhysX 闭环 | 往返、门反馈、故障/超时 | `NOT RUN` | 无实测 position/velocity timeline | 无法声称真实运动互锁已闭环 |

## 自动化与默认禁用 A/B

最终自动化记录是：

```text
main focused:              88 passed, 2 skipped
OpenUSD/pxr:               14 passed
broad constraints/export: 120 passed, 1 skipped
```

skip 不计为 PASS。OpenUSD 实体 schema 与 compliance 不依赖主 conda
中是否安装 `pxr`，已在隔离目录中单独执行：

```text
OpenUSD 25.5.1
PYTHONPATH=/tmp/infinigen_usd_core_25_5_1
```

默认禁用等价性对比使用：

```bash
python scripts/compare_indoor_outputs.py \
  /tmp/infinigen_ab_baseline_single_repeat/coarse \
  /tmp/infinigen_ab_candidate_single_final/coarse
```

实际摘要：

```text
matched_json_file_count: 2
missing_files: 0
extra_files: 0
SAME MaskTag.json numeric_max_abs_diff=0
SAME solve_state.json numeric_max_abs_diff=n/a
numeric_max_abs_diff: 0
FINAL: PASS
```

这证明当前 canonical A/B 的默认关闭路径未改变 coarse JSON
结果；不应把单个 seed/config 的对比扩大为全部输入的形式证明。

## coarse 场景证据

### 固定四层 static

```text
/tmp/infinigen_elevator_fixed_302_aligned/coarse/
```

`elevator_validation.json` 摘要：

```text
status=PASS
passed_check_count=19
failed_check_count=0
global_error_count=0
manifest_elevator_count=1
scene_elevator_root_count=1
```

19 项包括 `native_landing_opening_alignment`、`native_shaft_void`、
finished-floor stop、shaft bounds、资产 role/path、门板索引、MaskTag 和
电梯语义。

### 固定八层 static

```text
/tmp/infinigen_elevator_fixed8_seed303/coarse/
```

该运行以 seed token `303` 完成，总用时约 `1:50`；验收摘要为
`19/19 PASS`、0 failed、0 global errors，并生成了连接 8 层的 7 段
原生楼梯。该结果把“固定蓝图不是四层硬编码”从单测证据提升到
真实 coarse 证据。

### 随机四层 static

```text
/tmp/infinigen_elevator_random4_seed302_core8/coarse/
```

该运行使用 seed token `302`、可配置最小 `8 m × 8 m` 楼梯核心
和增量 staircase stack 放置，总用时约 `7:40`。输出包含
`vertical_core_manifest.json`，验收为 `19/19 PASS`、0 failed、0 global
errors，并生成 3 段原生楼梯。

旧路径 `/tmp/infinigen_elevator_random4_seed302_smoke/run.log` 中的
`KeyError: 12` 是已被最终成功运行取代的历史调试证据，不再代表当前
状态。

### 固定四层 animated

```text
/tmp/infinigen_elevator_fixed4_animated_final/coarse/
```

验收为 `20/20 PASS`、0 failed、0 global errors。除 static 检查外，
动画检查还确认：

- frame range 为 `1..543`，时长约 22.58 s；
- car Z、所有门板 X 和 root 控制状态都有必需曲线；
- 轿厢运动时所有门关闭，只有对层门与轿门联动。

已写出的渲染图：

```text
/tmp/infinigen_elevator_fixed4_animated_final/render/elevator_F1_open_balanced.png
```

同目录仍保留原始曝光版 `elevator_F1_open.png`。这些 PNG 证明渲染
产物存在；它们不替代多视角视觉评审。

## 真实建筑 USD、articulation 与离线控制

证据根目录：

```text
/tmp/infinigen_elevator_export_real/
```

主要文件：

```text
export_scene.blend/export_scene.usda
articulation/elevator_plan.json
articulation/elevator_articulation.usda
articulation/scene_with_elevators.usda
articulation/scene_F2_open.usda
blender_animated_nodes.usda
export_logs.log
```

### 静态建筑导出

`export_logs.log` 明确记录：

```text
Excluded 60 elevator-role objects from static export
```

`--exclude_elevators` 的当前语义不是隐藏对象。exporter 打开源
`.blend` 后，从内存副本删除所有带 `elevator_role` 的对象，
再执行会重置可见性的烘焙/导出。源 `.blend` 没有被保存覆盖。

### 独立 articulation 与 wrapper

对独立 articulation 和完整 wrapper 重开后得到：

```text
ArticulationRoot:     1
RigidBody links:     12
PrismaticJoint DOF:  11
FixedJoint:           1
linear drives:       11
```

`elevator_articulation.usda` 的 ComplianceChecker 为 0 errors/0 failed
checks。`scene_with_elevators.usda` 同时 sublayer 真实 Infinigen 建筑和
电梯层，可由 OpenUSD 25.5.1 打开并看到上述 articulation。

这里必须保留合规性边界：完整 wrapper 中 base 建筑的材质检查受
当前 OpenUSD 环境影响，因此只记录“wrapper 可打开且 articulation
结构可见”，不记录“完整 wrapper ComplianceChecker 0/0”。

### F2 开门 target

`scene_F2_open.usda` 由 `pxr` 重开后，`CabinLift` 位于 F2 相对
target。门的非零 target 只有：

```text
CabinDoorLeft
CabinDoorRight
LandingDoor_Stop_02_F2_Left
LandingDoor_Stop_02_F2_Right
```

F0、F1、F3 层门保持 target 0。这证明离线快照遵守“只开当前层
层门”的互锁；`car_position` 是已知对层输入，不是 Isaac 实测反馈。

### Blender 动画 USD

`blender_animated_nodes.usda` 的导出验收为：

```text
elevator-named prims: 65
animated xforms:      12
time range:           1..543
```

这是对 Blender 关键帧数据能够进入 USD 的证据。它不含独立
Physics articulation，也不表示 PhysX 已计算出真实运动。

## 仍然未完成的验收和已知限制

以下端到端项目仍为 `NOT RUN`：

- 在目标 Isaac Sim 版本 GUI 打开完整 wrapper；
- 创建/确认 PhysicsScene 后点击 Play；
- 读取实际 articulation joint position/velocity；
- 完成底层到顶层再返回；
- 用物理反馈验证门真实关闭后才启动、对层停稳后才开门；
- 验证 timeout、fault、timeline reset 和恢复流程；
- 验证机器人/navmesh/ROS 跨层导航；
- 生成并验收恢复普通家具、灯光和相机的完整高内容场景。

非均匀楼层的 elevator stop 和房间壳已使用 `BuildingLevels`，但原生
`room_stairs()` 仍使用单一 `wall_height`。因此“非均匀层高 + 原生楼梯”
仍是明确限制，不应因为均匀四/八层场景通过就宣称完成。

只有完成 Isaac 实际 position/velocity 反馈与往返运动项后，才可以把
状态从“OpenUSD 离线控制 PASS”提升为“Isaac PhysX 运行时 PASS”。
