# Infinigen Indoor 可运动电梯架构

## 结论与边界

当前实现采用“原生房间/楼梯生成 + 自定义电梯资产 + 导出后 USD Physics overlay”的分层方案。它没有假设 Infinigen 原生会导出一个可运行的电梯，也没有把 Blender 关键帧当作 Isaac Sim 物理控制。四层只是第一个验收配置；楼层、核心、停靠站、资产和 manifest 都由列表驱动，没有四层硬编码。

端到端数据流如下：

```text
RoomConstants + BuildingLevels
  -> 随机 FloorPlanSolver 或固定 PredefinedFloorPlanSolver
  -> 楼梯核心 + ElevatorRoom/ElevatorLobby + 专用落地门洞
  -> 连续井道开口 + 隐藏净空代理
  -> Blender 静态姿态或预计算关键帧资产
  -> elevator_manifest.json
  -> 静态建筑 USD（排除 Blender 电梯资产）
  -> 独立 elevator_articulation.usda/usdc
  -> scene_with_elevators.usda 组合层
```

这里有两种“运动”含义：

- `animated` Blender 模式生成一条确定的、带门联锁的关键帧轨迹，用于生成阶段检查与渲染。
- USD overlay 生成可由 Isaac Sim 设置 drive target 的升降轿厢和滑动门关节，是仿真运行时控制的基础。仓库现已包含不依赖 `pxr` 的互锁目标规划器 `elevator_runtime.py` 和离线写入 CLI `control_elevator_usd.py`；它们能生成或写入安全目标快照，但不是读取 PhysX 实际状态的 Isaac 调度器、按钮事件系统或机器人乘梯状态机。

## 任意 N 层与物理楼层信息

楼层数据定义在 `infinigen/core/constraints/constraint_language/levels.py`：

- `LevelSpec(index, elevation, height, level_id)` 把内部索引、物理 Z、高度和用户可见 ID 分开。
- `BuildingLevels` 要求内部索引为从最低层开始的连续非负整数，物理 `elevation` 严格递增，`level_id` 唯一。
- `BuildingLevels.uniform()` 是现有均匀层高场景的默认构造。`LevelSpec.elevation` 是原生房间壳的楼层基准；场景电梯的 finished-floor `stop_z` 使用 `elevation + wall_thickness / 2`，与原生房间 support surface 对齐，不能把两者混为同一个 Z。
- 地下层仍使用非负房间索引，例如 `B1` 可以是 `LevelSpec(0, -3.5, 3.2, "B1")`，而不是在房间名里使用负数。

`RoomConstants` 在 `infinigen/core/constraints/constraint_language/constants.py` 中持有 `building_levels`。没有显式配置时，它根据 `n_stories` 和原来的 `wall_height` 构造均匀楼层，因此旧调用方式不变。`BlueprintSolidifier` 从对应 `LevelSpec` 读取房间壳的 `elevation` 和 `height`，电梯停靠 Z 也来自同一份数据，避免再用“层号乘固定层高”推断电梯站点。

语义层面，`infinigen/core/tags.py` 新增可扩展的 `FloorIndex(index)`。每层始终带自己的 `FloorIndex`；`GroundFloor`、`SecondFloor`、`ThirdFloor` 只作为前三个相对地面层的兼容标签保留，没有继续增加 `FourthFloor` 一类枚举。`BuildingLevels` 的单元测试覆盖 1、3、4、8、16 层以及非均匀标高和地下层 ID。

因此，“任意 N 层”在楼层模型、房间循环、核心注册表、电梯资产、manifest 和 USD 关节计划中成立。当前原生楼梯几何仍使用 `j * constants.wall_height` 和单一 `constants.wall_height`，所以完整的非均匀层高/地下层楼梯场景还不是已闭环能力；默认均匀层高的任意 N 层路径不受这一限制。

## 原生楼梯保持不变

电梯不是楼梯的替代品。现有楼梯链仍由以下代码负责：

1. `ContourFactory.add_staircase()` 在所有楼层共享一个楼梯占位多边形。
2. `SegmentMaker` 把每层的 `StaircaseRoom` 分配给覆盖该占位区域的分段。
3. 默认路径中的 `FloorPlanMoves.move_staircase()` 对各层楼梯占位进行对齐移动。
4. `room_stairs()`（`infinigen/core/constraints/example_solver/room/decorate.py`）计算相邻两层楼梯房的交集，为每一对相邻楼层选择真实楼梯资产，并对上下两个房间壳做布尔开孔和护栏。

活动路径是 `room_stairs()`，不是 `BlueprintSolidifier.make_staircase_cutters()`。开启电梯后，楼梯占位也会作为一个预放置的 `VerticalCoreSpec` 进入统一核心注册表；房间退火不再移动任何核心房间或占位。若最终真实楼梯无法放下，电梯配置下会抛出错误，而不是静默输出一个只有电梯、没有楼梯的建筑。

电梯随机路径为原生楼梯增加了两个有界的可行性保护，不改变楼梯资产类型：`elevator_staircase_core_width/depth` 把楼梯核心扩大到可配置的最小尺寸，`elevator.gin` 默认为 `8 m × 8 m`；`_place_elevator_staircase_stack()` 再按楼层顺序增量放置每段楼梯，检查与前一段的穿透，失败时只做有界重启。这避免了旧的全层递归组合搜索及 Python 递归深度问题。

## `VerticalCoreRegistry`：楼梯与电梯共用的结构契约

`infinigen/core/constraints/example_solver/room/vertical_core.py` 把原来的单一楼梯占位扩展为通用竖向核心：

- `VerticalCoreSpec` 描述核心 ID、房间语义、占位语义、实例编号、宽深、贯穿层 `span_levels`、停靠层 `served_levels`、大厅类型、门宽、净距及覆盖率阈值。
- `VerticalCorePlacement` 保存所有贯穿楼层共享的 XY 多边形和统一门向 `-y/+x/+y/-x`，并由此得到大厅保留区。
- `VerticalCoreRegistry` 提供按 ID、楼层和房间键查询，验证核心在各层轮廓内且不同核心满足间距，并可输出不含 Shapely 对象的 JSON 数据。

放置器在所有 `span_levels` 轮廓的交集上按网格生成候选，可旋转长方形核心，并以本地 `numpy.random.Generator` 和 `SeedSequence` 选择稳定候选。它不会消耗 Infinigen 旧求解器的全局 NumPy 随机流。楼梯先作为 `preplaced` 核心加入，之后再依次放置 `elevator_0`、`elevator_1` 等电梯，所以楼梯和电梯之间也执行间距检查。

`span_levels` 与 `served_levels` 是两个独立概念。电梯房可以在每层连续贯穿，而仅在指定停靠层生成 `ElevatorLobby` 和落地门。当前候选放置实现仍要求“井道 + 大厅方向区域”位于所有贯穿层公共轮廓内，即对不停靠层也较保守；这是安全侧约束，不是最宽松的快速电梯布置算法。

## 随机房间求解路径

随机路径由 `FloorPlanSolver`、`GraphMaker`、`SegmentMaker` 和 `FloorPlanMoves` 协作完成：

1. `GraphMaker.add_vertical_core_nodes()` 在旧随机房间图求解完成后，以确定性步骤为每台电梯每层注入一个 `ElevatorRoom`。
2. 在停靠层，再注入一个 `ElevatorLobby`，拓扑为“公共房间—大厅—井道”。公共房间优先选择 `Hallway`、`LivingRoom`、`DiningRoom`；不停靠层只有井道房，不生成大厅和门。
3. `FloorPlanSolver._build_vertical_cores()` 把楼梯和所有电梯放进同一个 `VerticalCoreRegistry`。楼梯占位先扩展到配置的最小核心，电梯核心贯穿 `range(n_stories)`，停靠层来自 `RoomConstants.elevator_served_levels`。
4. `SegmentMaker.build_segments(vertical_cores=...)` 分别计算每个核心房间和大厅的候选分段，不允许不同核心错误共享同一个候选集合；每层还创建对应的 `Staircase` 或 `ElevatorShaft` 占位对象。
5. `FloorPlanMoves` 保护注册表中的核心房间与占位键，拒绝对它们进行挤出、交换或邻居连带修改。`ContourFactory.decorate()` 同样跳过电梯核心和大厅的轮廓变形。
6. 如果在 `elevator_placement_attempts` 次楼梯位置重试后仍无法同时放下核心，求解直接失败，不会降级成“缺少电梯”的场景。

`GraphMaker._typical_area()` 还给 `ElevatorRoom` 和 `ElevatorLobby` 提供与配置尺寸对应的面积估计，避免把它们交给普通住宅房型面积表。

## 固定房间求解路径

`infinigen_examples/configs_indoor/floor_plans/elevator.py` 提供确定性调试蓝图。`make_elevator_floor_plan(n_stories)` 为每层生成对齐的井道、大厅、楼梯房、起居室、走廊和卧室，并返回 schema v2 数据；每个门、入口、开口、室内窗和外窗记录都带显式 `level`。

`PredefinedBlueprintSolidifier` 在 `infinigen/core/constraints/example_solver/room/predefined.py` 中按当前层过滤房间和 portal，防止多层使用相同 XY 时，某层门洞误切其它楼层。带 `semantic: "elevator_landing"` 的记录走专用电梯门洞函数，普通门仍走旧门洞路径。

固定蓝图当前有两个明确边界：

- `make_elevator_floor_plan()` 只实现一台电梯；随机核心规划器才支持 `n_elevators > 1`。
- `PredefinedFloorPlanSolver` 不附加 `VerticalCoreRegistry`。后续场景集成会从各层对齐的 `ElevatorRoom` 多边形计算井道，并用大厅相对井道的质心方向推断门向，因此固定路径不会写 `vertical_core_manifest.json`。

`fixed_four_story_elevator()` 是四层验收入口，`fixed_eight_story_elevator()` 和相关测试证明固定蓝图本身不是四层硬编码。

## 电梯房、大厅和专用门洞

`BlueprintSolidifier.convert_solver_state()` 对 `ElevatorRoom` 和 `ElevatorLobby` 添加 `NoChildren`，同时把电梯房标为 `VerticalCore`。住宅房型约束和家具域也在 `infinigen_examples/constraints/home.py` 中排除了电梯房和大厅。这使当前大厅保持无家具的安全区域，而井道不会被当作可布置房间。

`BlueprintSolidifier.make_interior_cutters()` 对包含 `ElevatorRoom` 的共享边进行特殊处理：只有另一侧是 `ElevatorLobby` 时才生成门洞，其它井道边保持封闭。`make_elevator_door_cutter()`：

- 检查共享边长度能容纳配置门宽；
- 在共享边中心生成配置宽高的滑动门开口；
- 使用稳定名称 `elevator-landing-door_<level>/<index>`；
- 写入 `elevator_landing_door`、`elevator_id` 和 `floor_index` 自定义属性；
- 在 `State` 中添加 `Door`、`ElevatorDoor`、`ElevatorLandingDoor` 和对应楼层标签。

`generate_indoors.py` 的普通 `populate_doors()` 域显式排除 `ElevatorLandingDoor`，因此不会在同一开口上再生成一扇随机铰链门。真正的双开滑门面板由电梯资产生成。

## 连续井道与净空

房间求解结束后，`infinigen/core/constraints/example_solver/room/elevator.py` 执行两个结构步骤。

`install_elevator_clearance_proxies()` 在普通家具求解之前运行：

- 每台电梯创建一个从最低层标高到最高层顶面的隐藏井道代理；
- 每个落地门创建一个沿大厅方向延伸的隐藏净空盒，其横向范围包含门宽和核心净距；
- 代理带 `ElevatorClearance`、`NoChildren`，加入 `State.trimesh_scene` 参与碰撞排斥，但不渲染，也不进入相机预处理的普通非房间对象集合。

`open_elevator_room_shells()` 在房门/窗完成后、`split_rooms()` 之前运行。它要求每台电梯恰好存在 `0..n_stories-1` 的完整井道房组，但不再删除整个随机 `ElevatorRoom` 的地板/天花。实现会从注册核心 footprint 内缩专用井道墙厚，构造一个略超出整栋高度的精确 box cutter，并对每层井道房执行 boolean difference。这样即使随机分配的井道房大于核心，占用核心以外的可用房间面积仍保留，同时 car sweep 内不会残留 support/ceiling 面；pit 和顶盖由专用电梯资产提供。

随后才执行原生 `room_stairs()`。踢脚线阶段排除 `ElevatorRoom`，避免在井道内重新生成跨越开口的装饰几何。

## Blender 电梯资产层级

纯 Python 规格与控制器在 `infinigen/assets/objects/elements/elevators/model.py`，Blender 构建器在同目录的 `blender.py`。`build_elevator_asset()` 创建稳定的 EMPTY/primitive 层级：

```text
ElevatorSystem_<index>                 role=system
├── Shaft                              role=shaft
│   ├── Structure                      左/右/后墙、底板、顶板
│   └── Landings
│       └── Landing.<index>.<level_id>
│           ├── Frame + Threshold
│           ├── Door
│           │   ├── Panel.Left
│           │   └── Panel.Right
│           └── CallStation
└── Car                                Z 方向运动节点
    ├── Cabin                          地板、顶板、三面墙、ControlPanel
    └── Door
        ├── Panel.Left
        └── Panel.Right
```

每个节点都有稳定的 `elevator_role` 和相对层级标识 `elevator_node_path`。根节点还保存 schema 版本、seed、坐标约定、停靠层、停靠 Z、模式和当前控制状态。视觉随机性只改变颜色和呼梯面板左右位置，不改变净空尺寸。

`ElevatorSpec` 检查：停靠 Z 严格递增、层 ID 唯一、轿厢加运行间隙能放进井道、门能放进轿厢/井道、门高低于轿厢，以及相邻站距足以容纳轿厢和门框。井道底和顶由最低/最高停靠 Z 加 pit/overhead 得到。

场景集成的 `build_scene_elevators()` 使用核心多边形尺寸、门向、`BuildingLevels` 和 `RoomConstants` 的轿厢/门尺寸构造资产。停靠点取原生 finished floor，即 `LevelSpec.elevation + wall_thickness / 2`。井道底/顶则以整栋最低基准和最高层顶面计算，因此 express 服务表可以省略物理底层、顶层，井道仍贯穿完整 `span_levels`。静态模式在可服务层中选择一个由 scene seed 确定的初始层；动画模式默认从最低服务层开始，依次访问其余服务层，也可用 compose override 指定初始层和 route。

## 状态机、门联锁与加速度

`ElevatorController` 是不依赖 Blender/NumPy 的单轿厢确定性控制器，状态为：

```text
IDLE_CLOSED -> MOVING -> LEVELING -> OPENING
      ^                                  |
      +--------- CLOSING <- OPEN_DWELL <-+

任意安全状态 --trigger_fault()--> FAULT
```

请求按 FIFO 顺序服务。当前层请求直接进入开门流程；运行和 leveling 时所有轿门、层门必须关闭；只有与轿厢对齐的当前层层门能和轿门以相同开度联动。`FAULT` 会将速度置零，且只有在轿厢对层、所有门关闭时才能 reset。

运动曲线不是匀速瞬移。`_build_motion_profile()` 根据距离、`travel_speed` 和 `travel_acceleration` 生成三角形或梯形速度曲线：短行程加速后立即减速，长行程加速到限速、匀速、再减速。`step(dt)` 对曲线积分并限制峰值速度，随后执行可配置 leveling、开门、停留和关门时间。

`build_animation_plan()` 按固定采样周期生成联锁安全的 snapshot。Blender 动画把轿厢 Z 和所有门板 X 写成线性关键帧，把 phase、当前层、目标层、速度和门开度元数据写成常量插值关键帧。它是一条预计算 route，不是交互式仿真控制器。

## 语义与可验证元数据

`infinigen/core/tags.py` 中的电梯语义包括：

| 类别 | 语义/标识 | 当前用途 |
| --- | --- | --- |
| 房间 | `ElevatorRoom`, `ElevatorLobby` | 井道房、大厅拓扑和家具排除 |
| 核心 | `VerticalCore`, `ElevatorShaft` | 连续核心房与占位/资产结构 |
| 运动体 | `ElevatorCar` | 轿厢网格 |
| 门 | `ElevatorDoor`, `ElevatorLandingDoor`, `ElevatorCarDoor` | 专用 cutter、落地门和轿门 |
| 安全空间 | `ElevatorClearance` | 隐藏碰撞净空代理 |
| 控制 | `ElevatorControlPanel` | 当前用于轿厢控制面板网格；呼梯站另由 `elevator_role=landing_call_station` 识别 |

`_tag_asset_mesh()` 给所有电梯网格写入 `Visible`、`Interior` 以及 `SupportSurface`/`Ceiling`/`Wall` 面语义，并根据 `elevator_role` 添加上述对象语义。`infinigen/tools/validate_elevator_scene.py` 可以只读打开 `.blend`，核对 manifest 与根节点 ID/位置、稳定层级路径、停靠标高、井道上下界、静态/动画曲线、门板数量、`MaskTag` 以及必需电梯标签，输出 JSON PASS/FAIL 报告；它不会修改或保存场景。

## Manifest

`build_scene_elevators()` 在场景输出目录写入经过重新解析验证的 `elevator_manifest.json`。schema 由 `infinigen/core/sim/elevator_manifest.py` 定义，主要字段为：

- 场景级：`schema_version=1`、`meters_per_unit`、`up_axis=Z`、`scene_id`、`seed`；
- 电梯级：稳定 ID、世界 `origin_xy`、门向对应的 yaw、井道内尺寸和 Z 上下界；
- 轿厢级：内部尺寸、壁/底厚、质量、门宽高厚、门行程和门板质量；
- 停靠层：`floor_id` 与绝对 finished-car-floor `stop_z`；
- 控制级：轿厢和门的 drive stiffness、damping、max force。

验证器拒绝未知字段、非 Z-up、重复电梯 ID/楼层 ID、不可区分的站点 Z、越过井道的轿厢以及放不进井道的轿厢/门。`write_manifest()` 使用临时文件后原子替换。随机路径存在注册表时还会额外写 `vertical_core_manifest.json`，记录核心 footprint、贯穿/停靠层、门向和净距。

`infinigen/tools/export.py` 会把这两个 manifest 复制到导出目录。`--exclude_elevators` 打开 `.blend` 后，会从当前内存副本删除所有带 `elevator_role` 的电梯对象，然后再执行烘焙/导出；它不依赖会被导出烘焙阶段重置的隐藏标志，也不保存回源 `.blend`。这条路径供“静态建筑 + 独立 articulation”工作流使用，避免 Blender 预览资产和 USD 物理资产重叠。

## USD Physics overlay

`infinigen/core/sim/elevator_usd.py` 先从 manifest 生成不依赖 `pxr` 的 `ElevatorUSDPlan`，再选择性地写 OpenUSD。每台电梯包含：

- 一个固定到 world 的 `Base` 刚体；
- 一个通过 Z 轴 prismatic joint 连接 Base 的 `Cabin`；
- 两个通过 X 轴 prismatic joint 连接 Cabin 的轿门叶；
- 每个服务层各两个通过 X 轴 prismatic joint 连接 Base 的层门叶；
- 每个运动 link 的简单 box visual 和匹配 collision proxy；
- 所有关节的 `UsdPhysics.DriveAPI(..., "linear")`，不会误用 angular drive。

若服务站数为 `S`，每台电梯的自由度为 `1 + 2 + 2S = 3 + 2S`。升降 joint 的 drive target 是相对最低服务站的位移；plan JSON 同时保留 `floor:<id>` 的命名目标。左右门目标分别为负/正门行程。

`infinigen/tools/build_elevator_usd.py` 支持两条实际路径：

- `--plan-only`：只验证 manifest 并写 `elevator_plan.json`，不需要 `pxr`；
- 完整模式：写独立 `elevator_articulation.usda/usdc`，再写 `scene_with_elevators.usda`，后者以相对路径 sublayer 静态建筑 USD 和电梯层，不改写原建筑文件。

OpenUSD 绑定是延迟导入的；实际 USD authoring 需要在 Isaac Sim/Omniverse Python 或其它有 `pxr` 的环境执行。`elevator_runtime.py` 会从 manifest/plan 生成覆盖全部关节的目标快照：移动目标强制所有门关闭；开门目标要求调用方提供已对层的实测 `CabinLift` 位置，并只打开轿门和该层层门。它还可对 `pxr.Usd.Stage` 预检关节全集、轴、limits、body 绑定、单位和 linear drive 后写 target。generic `pxr` 不会执行物理或提供实际 position/velocity，因此呼梯队列、等待门真实关严、Physics step、超时/故障和导航更新仍必须由 Isaac 闭环控制器完成。

当前已用真实 Infinigen 四层静态建筑完成这条组合路径：独立电梯层含 1 个 articulation root、12 个 rigid link、11 个 prismatic joint、1 个 fixed joint 和 11 个 linear drive；独立 articulation 的 ComplianceChecker 为 0 errors/0 failed checks，组合 wrapper 可由 `pxr` 打开。完整 wrapper 包含 Blender 导出的建筑材质，其 ComplianceChecker 结果受当前 OpenUSD 材质检查环境影响，因而不记为 0/0。F2 离线开门层经重开核对，只打开两扇轿门和两扇 F2 层门；这仍是 target authoring，不是 PhysX 运动证据。

## 配置入口

电梯默认不启用。现有 gin 文件职责如下：

| 配置 | 作用 |
| --- | --- |
| `infinigen_examples/configs_indoor/elevator.gin` | 通用 opt-in；不固定楼层数，配置一台全停靠电梯、尺寸、净空和运动时间 |
| `infinigen_examples/configs_indoor/four_story_elevator.gin` | 四层、固定外轮廓、静态电梯验收配置 |
| `infinigen_examples/configs_indoor/four_story_elevator_animated.gin` | 在四层配置上启用预计算动画 route |
| `infinigen_examples/configs_indoor/four_story_elevator_fixed.gin` | 在四层配置上改用确定性固定蓝图 |
| `infinigen_examples/configs_indoor/eight_story_elevator_fixed.gin` | 复用通用 N 层蓝图的八层结构验收配置 |

`RoomConstants` 还支持 `n_elevators`、服务层子集、井道/轿厢/门尺寸、核心间距、大厅深度、核心覆盖阈值和放置重试次数。`compose_indoors` override 支持模式、初始层、动画 route/FPS、轿厢速度/加速度、开关门时间、停留时间以及静态门是否打开。

## 默认禁用质量门

`RoomConstants.elevator_enabled` 的默认值是 `False`，这是当前实现必须保留的质量门，而不是临时配置习惯。关闭时：

- `GraphMaker.add_vertical_core_nodes()` 原样返回旧房间图；
- `FloorPlanSolver._build_vertical_cores()` 返回 `None`，继续调用原来的单楼梯 `SegmentMaker.build_segments(pholder)`；
- `FloorPlanMoves` 不建立核心保护集合；
- `generate_indoors.py` 不运行净空、井道开壳或电梯资产阶段；
- 普通楼梯、房门、家具和导出路径仍走原逻辑。

已有自动化覆盖分别位于：

- `tests/solver/test_building_levels.py`：任意楼层标签、实际标高、地下层和旧 `RoomConstants` 随机序列；
- `tests/constraints/test_vertical_core.py`：16 层、快速停靠、多核心确定性、间距、候选归属和禁用图路径；
- `tests/constraints/test_predefined_elevator_floor_plan.py`：4/8 层固定蓝图、逐层 tile、核心对齐和 portal level；
- `tests/assets/test_elevator_model.py`：规格校验、FIFO、门联锁、故障、确定性轨迹和加速度/限速；
- `tests/assets/test_elevator_blender.py`：静态/动画层级、门联动、关键帧和元数据；
- `tests/sim/test_elevator_manifest.py`、`test_elevator_usd.py`：manifest、关节计划、CLI plan-only 和非破坏 wrapper；
- `tests/sim/test_elevator_usd_pxr.py`：仅在安装 `pxr` 时检查实际 USD schema、linear drive、articulation root 和合规性；
- `tests/sim/test_elevator_runtime.py`：完整目标快照、非法开门拒绝、多梯隔离、plan 一致性、安全副本/显式 in-place 和真实 `pxr` Stage 写入；
- `tests/tools/test_validate_elevator_scene.py`：场景验证器的 PASS/FAIL 行为。

当前自动化证据分三组：主电梯聚焦批次 `88 passed, 2 skipped`，隔离 OpenUSD 25.5.1 环境的 `pxr` 批次 `14 passed`，广泛 constraints/gins/export 回归 `120 passed, 1 skipped`。端到端 coarse 验收包括：固定四层 static `19/19 PASS`；固定八层 static `19/19 PASS`，产生 7 段原生楼梯；随机四层 seed token `302` + `8 m × 8 m` 楼梯核心 `19/19 PASS`，产生 3 段原生楼梯；固定四层 animated `20/20 PASS`。动画 `.blend` 还导出了保留 time samples 的 Blender USD，证据为 65 个 elevator-named prim、12 个 animated xform 和 time range `1..543`。这些结果证明场景结构、语义和离线动画数据成立；不证明 Isaac 中已发生物理运动。完整证据矩阵见 `docs/ELEVATOR_TEST_REPORT.md`。

默认禁用 A/B 也已使用 `scripts/compare_indoor_outputs.py` 在 baseline repeat 与 final candidate 之间完成 canonical 对比：`MaskTag.json` 和 `solve_state.json` 相同，数值最大差为 0，结果 `FINAL: PASS`。因此“电梯默认关闭”的兼容路径有实际等价性证据；它不代表所有 seed/config 的穷尽证明。

## 当前限制

- 四层不是系统上限：固定八层 static 已经整楼通过。但目前只有随机四层的整楼 PASS 证据；随机 N 层越高，可同时容纳楼梯、井道和大厅的公共轮廓越难找到，求解仍可能按设计硬失败。
- 完整非均匀层高已经进入房间壳和电梯 stop Z，但原生 `room_stairs()` 尚未改为逐层读取 `LevelSpec`，所以这类场景的楼梯位置/高度不能视为完成。
- 固定 smoke 蓝图只支持一台井道，且蓝图拓扑仍为每层大厅/门洞；多电梯和 express 大厅拓扑由随机核心路径实现。底层 `served_levels`、资产、manifest、USD plan/runtime 本身接受任意有序有效子集。
- 随机路径中的多台电梯目前共用同一组尺寸和 `elevator_served_levels`，还不能为每台电梯分别配置载客/消防/货梯停靠表。
- 场景开壳要求电梯房贯穿每一个内部楼层索引；局部井道、错层井道、双面开门和每层不同门向尚不支持。
- 启用的移动电梯至少需要两个服务站；`RoomConstants` 已在配置阶段检查数量、排序、唯一性和楼层范围。服务表不必包含建筑物理端点：shaft boolean 和核心仍贯穿所有 `span_levels`，资产 pit/overhead 会把井道边界扩展到整栋底/顶，只有被服务层生成 landing/lobby/层门 DOF。
- 大厅当前标记 `NoChildren` 并从家具域排除，安全但视觉上会偏空；净空代理是轴对齐 box，不是对客流或门机运动的精确扫掠体。
- Blender 资产是稳定的 primitive 骨架，适合语义、尺寸和运动验证，不是写实工业电梯模型。
- Blender `animated` 模式是离线关键帧，不响应运行时请求。纯 Python `ElevatorController` 也不会自动出现在导出的 Isaac 场景中。
- USD overlay 用 box 近似重新构造轿厢和门，并提供相互独立的 drives；现有 runtime 层保证所生成目标的“移动时全门关、对层后只开当前层门”不变量，但 Isaac 侧仍需用实际 position/velocity 反馈完成调度、等待、传感器、故障恢复和机器人上下轿厢。
- 自动生成的 manifest 当前采用 `meters_per_unit=1.0`、Z-up；代码不会从一个已导出的、可能使用不同单位的 USD stage 反向校准该值。
- 当前没有 navmesh 动态连接、ROS/SLAM 接口、载重/乘员模型、门夹检测或真实电梯安全认证逻辑。
- `validate_elevator_scene.py` 验证 Blender 资产与 manifest，不验证机器人可达性、真实物理稳定性或完整房间家具质量；OpenUSD schema 测试也不替代 Isaac Sim 实机步进测试。

在这些边界内，这套结构已经给出了可生成、可导出并可写入运动 target 的多层电梯方案：固定四/八层、随机四层和固定四层动画都已有整楼证据，真实静态建筑也已与 articulation 组合。原生房间与楼梯负责建筑质量，自定义核心保证空间连续，Blender 资产负责可视化和离线动画，manifest 作为唯一仿真契约，独立 USD overlay 负责关节与 drive target。真实 Isaac/PhysX 运动闭环仍需在目标仿真环境中完成验收。
