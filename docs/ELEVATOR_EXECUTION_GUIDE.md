# Infinigen 四层与任意 N 层可运动电梯执行指南

本文对应 2026-07-10 当前工作区中的实现，覆盖室内楼层生成、Blender
电梯资产、manifest、独立 USD Physics articulation，以及交给 Isaac Sim
前的验证步骤。

## 1. 当前状态与边界

本文使用以下状态标记：

- `PASS`：命令或等价测试已经在当前工作区实际执行成功。
- `FAIL`：命令已经执行并以明确错误结束；这不同于尚未运行。
- `NOT RUN`：入口和参数已经与当前代码核对，但没有该端到端运行证据。

当前验证状态：

| 项目 | 状态 | 说明 |
|---|---|---|
| 电梯主聚焦批次 | `PASS` | `88 passed, 2 skipped`；skip 不计为 PASS |
| OpenUSD/`pxr` 批次 | `PASS` | OpenUSD 25.5.1 隔离环境中 `14 passed` |
| 广泛 constraints/gins/export 回归 | `PASS` | `120 passed, 1 skipped` |
| 默认禁用 canonical A/B | `PASS` | baseline repeat 对 candidate final；`MaskTag.json`/`solve_state.json` 相同，数值最大差 0 |
| 固定四层 aligned coarse + `.blend` 验收 | `PASS` | 真实完整 indoor 输出存在；只读验证为 `19/19 PASS`、0 global errors |
| 固定八层 + 原生楼梯 coarse | `PASS` | `19/19 PASS`；总用时约 `1:50`，7 段楼梯 |
| 随机四层 + 原生楼梯 coarse | `PASS` | seed token `302`、最小 `8 m × 8 m` 楼梯核心；`19/19 PASS`，总用时约 `7:40`，3 段楼梯 |
| 固定四层 animated coarse | `PASS` | `20/20 PASS`；Blender USD 保留 65 个 elevator-named prim、12 个 animated xform、time `1..543` |
| `--plan-only` | `PASS` | 已对实际四层 manifest 输出单梯 11-DOF plan |
| 真实 Infinigen 建筑 USD + articulation wrapper | `PASS` | 真实静态建筑已导出与组合；wrapper 可打开，独立 articulation compliance 0/0 |
| 真实 wrapper F2 离线开门 | `PASS` | 只有轿门和 F2 层门获得开门 target |
| Isaac Sim GUI/timeline/PhysX 运动 | `NOT RUN` | 没有真实 Isaac 导入、Play、position/velocity 反馈或往返运行证据 |

重要边界：

- Blender 的 `animated` 模式是安全状态机生成的关键帧预览。
- 独立 USD 是真正的刚体、PrismaticJoint 和 linear Drive articulation。
- `elevator_runtime.py` 和 `control_elevator_usd.py` 已能生成/写入完整互锁 target 快照；移动目标关闭所有门，开门目标要求调用方提供实测对层位置，并只打开当前层。generic `pxr` 不会 step PhysX，因此调用方仍须等待门/轿厢实际位置和速度、处理超时与调度。
- 当前没有 ROS/Nav2 或跨层导航接入。
- 普通 whole-scene USD 导出本身不会把 Blender 电梯自动变成 articulation；必须执行本文的独立 USD 步骤。
- 恢复普通家具、灯光和相机的完整高内容场景仍为 `NOT RUN`。

## 2. 环境

### 2.1 Host conda 环境

状态：`PASS`。

```bash
cd /home/ubuntu22/infinigen
source /home/ubuntu22/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
python -c "import bpy; print(bpy.app.version_string)"
```

预期 Blender Python 版本为 `4.2.0`。当前代码会拒绝其他 Blender 版本。

### 2.2 Docker 环境

以下是仓库约定的容器入口。状态：`NOT RUN`（本轮使用的是 host
conda 环境）。

```bash
docker exec -it infinigen bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
cd /opt/infinigen
```

下文命令均假设当前目录是仓库根目录。Host 和容器路径不要混用。

### 2.3 检查 OpenUSD

状态：`PASS`。当前 Infinigen conda 环境预期输出 `pxr unavailable`。

```bash
python - <<'PY'
try:
    from pxr import Usd
except ImportError:
    print("pxr unavailable; use --plan-only or a separate OpenUSD/Isaac Python")
else:
    print("OpenUSD", Usd.GetVersion())
PY
```

## 3. 三种楼层生成入口

### 3.1 固定四层

配置 `four_story_elevator_fixed.gin` 使用确定性的四层宏观平面图，每层包含：

- 一个相同 XY 的电梯井；
- 一个电梯厅和专用层门；
- 一个相同 XY 的原生楼梯房；
- 普通 Infinigen 房间壳体。

固定平面图目前只支持一个电梯井。以下是轻内容 smoke 命令；电梯和楼梯仍然使用正式几何逻辑，`disable/no_objects` 只关闭普通家具对象。

状态：`PASS`。seed token `302` 的 aligned 运行已保存完整 coarse 输出到
`/tmp/infinigen_elevator_fixed_302_aligned/coarse`；其中 `scene.blend`、
`MaskTag.json`、manifest 和 `solve_state.json` 均存在，只读场景验证为
`19/19 PASS`。这是结构/语义验收，不是 Isaac 物理运动验收。

```bash
SCENE=outputs/elevator_fixed4/coarse
python -m infinigen_examples.generate_indoors \
  --seed 302 \
  --task coarse \
  --output_folder "$SCENE" \
  -g four_story_elevator_fixed.gin disable/no_objects.gin \
  -p compose_indoors.terrain_enabled=False \
     compose_indoors.sky_lighting_enabled=False \
     compose_indoors.animate_cameras_enabled=False \
     compose_indoors.pose_cameras_enabled=False \
     compose_indoors.room_pillars_enabled=False
```

移除 `disable/no_objects.gin` 和按需禁用的 stage override，即可恢复普通家具、灯光和相机流程。该高内容命令状态为 `NOT RUN`，预计明显更慢。

注意：Infinigen 的 `--seed` 首先按十六进制解析。因此命令行 token `302`
对应整数 `0x302 == 770`，生成日志和 `elevator_manifest.json` 中会记录
`770`。复现实验时应保存原始 seed token，同时检查 manifest 中的最终整数。

### 3.2 随机四层

`four_story_elevator.gin` 固定四层和公共外轮廓，但房间图、分段与 vertical
core 候选仍走随机求解路径。

状态：`PASS`。seed token `302` 的最终 random-core8 运行已完成，
证据目录为 `/tmp/infinigen_elevator_random4_seed302_core8/coarse`。只读场景
验收为 `19/19 PASS`、0 failed、0 global errors；总用时约 `7:40`，
并生成了 3 段原生楼梯和 `vertical_core_manifest.json`。

```bash
SCENE=/tmp/infinigen_elevator_random4_seed302_core8/coarse
python -m infinigen_examples.generate_indoors \
  --seed 302 \
  --task coarse \
  --output_folder "$SCENE" \
  -g four_story_elevator.gin disable/no_objects.gin \
  -p compose_indoors.terrain_enabled=False \
     compose_indoors.animate_cameras_enabled=False \
     compose_indoors.pose_cameras_enabled=False
```

当 `elevator_enabled=True` 时，随机路径使用
`elevator_staircase_core_width/depth` 保证楼梯核心的可配置最小尺寸；
`elevator.gin` 当前两者均为 `8.0`。原生楼梯资产按楼层顺序增量放置，
只与前一段做穿透检查，失败后进行有界重启，不再走旧的全层递归
组合搜索。旧 `KeyError: 12` smoke 只是历史调试记录，不再代表当前
随机四层状态。

随机路径支持 `RoomConstants.n_elevators > 1`；固定蓝图不支持。

### 3.3 任意均匀 N 层

通用入口是 `elevator.gin` 加 `RoomConstants.n_stories=N`。建议在首次 smoke
时显式使用公共固定外轮廓，以提高 vertical core 在所有楼层拥有公共 XY
足迹的概率。

下面以已完成的固定 8 层为例。状态：`PASS`。证据目录为
`/tmp/infinigen_elevator_fixed8_seed303/coarse`，验收为 `19/19 PASS`，
总用时约 `1:50`，生成 7 段原生楼梯。

```bash
SCENE=/tmp/infinigen_elevator_fixed8_seed303/coarse
python -m infinigen_examples.generate_indoors \
  --seed 303 \
  --task coarse \
  --output_folder "$SCENE" \
  -g eight_story_elevator_fixed.gin disable/no_objects.gin \
  -p compose_indoors.terrain_enabled=False \
     compose_indoors.animate_cameras_enabled=False \
     compose_indoors.pose_cameras_enabled=False
```

固定八层的 PASS 证明列表驱动的楼层/资产/manifest 路径不是四层
硬编码。它不等于随机八层或多梯整楼已验收。

两个随机电梯的配置模板如下；它不是本轮端到端 PASS 证据。

```bash
SCENE=outputs/elevator_random8_two_cars/coarse
python -m infinigen_examples.generate_indoors \
  --seed 305 \
  --task coarse \
  --output_folder "$SCENE" \
  -g elevator.gin disable/no_objects.gin \
  -p RoomConstants.n_stories=8 \
     RoomConstants.n_elevators=2 \
     RoomConstants.fixed_contour=True \
     compose_indoors.terrain_enabled=False \
     compose_indoors.animate_cameras_enabled=False \
     compose_indoors.pose_cameras_enabled=False
```

只服务部分楼层的 express elevator 使用内部楼层 index。端点不是强制项；例如
8 层建筑可以只服务 1、3、6 层：

```bash
-p "RoomConstants.elevator_served_levels=[1,3,6]"
```

`RoomConstants` 和资产构建代码支持这种不含端点的服务表；现有 express-core
单测也覆盖了 `span_levels`/`served_levels` 分离。包含端点省略配置的完整 coarse
命令仍为 `NOT RUN`。电梯井仍贯穿所有楼层，但只有被服务层
生成 lobby、landing door 和对应 USD 层门 DOF。shaft boolean 使用完整建筑
高度，资产的 pit/overhead 也从建筑底/顶反推，所以省略物理底层或顶层不会把
井道截短。固定 smoke blueprint 仍是每层大厅/门洞，express 整楼拓扑应走随机
vertical-core 路径。

### 3.4 每层 7–8 个普通房间的完整内容场景

仓库提供一键脚本，默认执行本节的四层、每层 7–8 个普通房间、完整室内内容、
校验、USDC 导出和 articulation 组合流程：

```bash
./scripts/run_full_elevator_scene.sh
```

例如生成 8 层时使用 `N_STORIES=8 ./scripts/run_full_elevator_scene.sh`；脚本还接受
`SEED`、`MIN_ROOMS`、`MAX_ROOMS`、`ELEVATOR_MODE`、`FINE_TERRAIN`、
`OUTPUT_ROOT`、`EXPORT_RESOLUTION` 和 `DRY_RUN` 环境变量。`FINE_TERRAIN` 默认
为 `0`：它只关闭可选室外地形，完整室内家具、材质、灯光、相机、楼梯和电梯
仍全部生成。设置 `FINE_TERRAIN=1` 前，脚本会预检 `landlab/pkg_resources`，
避免在耗时生成已经开始后才因地形依赖失败。

`RoomConstants.min_rooms_per_floor/max_rooms_per_floor` 是 opt-in 的户型约束。
这里的普通房间包括卧室、客厅、厨房、卫生间、走廊、储藏室等可布置空间，
不计 `StaircaseRoom`、`ElevatorLobby`、`ElevatorRoom` 或井道占位。两项保持未设置
时继续使用原生 `4..15` 图约束及其旧统计口径，不改变默认生成路径。

多层随机户型可用 `home_room_constraints.fixed_contour=True` 请求所有楼层共享
外轮廓，从而提高楼梯和电梯核心拥有公共 XY 区域的成功率。下面的命令不包含
`disable/no_objects.gin`、`fast_solve.gin` 或 `restrict_solving.solve_max_rooms`；
`coarse` 会执行完整室内家具/小物件/门窗/材质/灯光/相机阶段；可选的
`fine_terrain` 只负责继续细化启用的室外地形。

```bash
N=4
SEED=305
ROOT="$PWD/outputs/elevator_full_${N}f_seed${SEED}"
SCENE="$ROOT/coarse"

python -m infinigen_examples.generate_indoors \
  --seed "$SEED" \
  --task coarse \
  --output_folder "$SCENE" \
  -g elevator.gin \
  -p RoomConstants.n_stories="$N" \
     RoomConstants.min_rooms_per_floor=7 \
     RoomConstants.max_rooms_per_floor=8 \
     home_room_constraints.fixed_contour=True \
     "compose_indoors.elevator_mode='animated'" \
     compose_indoors.terrain_enabled=False
```

参数解析、默认兼容约束和随机房间图样例为 `PASS`；完整高内容 N 层运行仍为
`NOT RUN`，应预留显著长于轻内容 smoke 的运行时间和磁盘空间。对 indoor，
单独再跑 `--task populate` 没有作用，因为当前 `populate_scene_func=None`。

### 3.5 非均匀标高、地下层和自定义 level ID

`BuildingLevels` 支持任意严格递增的物理标高。建议新增一个项目配置，例如
`infinigen_examples/configs_indoor/custom_elevator_levels.gin`：

```gin
include 'infinigen_examples/configs_indoor/elevator.gin'

RoomConstants.n_stories = 4
RoomConstants.fixed_contour = True
RoomConstants.building_levels = [
  {'index': 0, 'elevation': -3.4, 'height': 3.2, 'level_id': 'B1'},
  {'index': 1, 'elevation':  0.0, 'height': 3.6, 'level_id': 'G'},
  {'index': 2, 'elevation':  3.8, 'height': 3.0, 'level_id': 'L1'},
  {'index': 3, 'elevation':  7.1, 'height': 3.0, 'level_id': 'L2'},
]
```

然后使用：

```bash
python -m infinigen_examples.generate_indoors \
  --seed 306 \
  --task coarse \
  --output_folder outputs/elevator_nonuniform4/coarse \
  -g custom_elevator_levels.gin disable/no_objects.gin \
  -p compose_indoors.terrain_enabled=False
```

状态：配置解析为 `PASS`，完整 coarse 为 `NOT RUN`。

约束：

- index 必须是自底向上的连续 `0..N-1`；地下层仍使用非负 index。
- `RoomConstants.n_stories` 必须与列表长度相同。
- `elevation` 必须严格递增，`level_id` 必须唯一。
- 应避免楼层壳体重叠，并给轿厢高度、门高和运行间隙留下足够的相邻停靠距离。
- manifest 的 `stop_z` 是 native finished-floor Z，即
  `LevelSpec.elevation + wall_thickness / 2`，不能直接使用 shell 基准
  `elevation`，也不能用名义层高推算。
- 当前原生 `room_stairs()` 仍使用单一 `constants.wall_height`，尚未逐层读取
  `LevelSpec`。因此非均匀/地下电梯 stop 模型和配置解析已完成，但包含原生楼梯
  的完整非均匀建筑还不能视为闭环能力。

## 4. 静态与动画模式

### 4.1 静态

`elevator.gin` 和 `four_story_elevator.gin` 默认：

```gin
compose_indoors.elevator_mode = 'static'
compose_indoors.elevator_static_doors_open = False
```

需要在初始层静态开门时可加：

```bash
-p compose_indoors.elevator_static_doors_open=True
```

初始层可用楼层 index 或 `level_id`。例如：

```bash
-p compose_indoors.elevator_initial_level=2
```

静态模式不为轿厢、门板或控制状态写动画曲线，适合检查结构、语义和
manifest，也适合作为独立 USD articulation 的建筑生成入口。

### 4.2 动画

随机四层动画已有配置 `four_story_elevator_animated.gin`。固定四层动画应在
固定配置上覆盖 mode：

状态：`PASS`。最终整楼输出在
`/tmp/infinigen_elevator_fixed4_animated_final/coarse`，场景验收为
`20/20 PASS`、0 failed、0 global errors，frame range 为 `1..543`。

```bash
SCENE=/tmp/infinigen_elevator_fixed4_animated_final/coarse
python -m infinigen_examples.generate_indoors \
  --seed 307 \
  --task coarse \
  --output_folder "$SCENE" \
  -g four_story_elevator_fixed.gin disable/no_objects.gin \
  -p compose_indoors.elevator_mode=animated \
     compose_indoors.elevator_animation_route=all \
     compose_indoors.terrain_enabled=False \
     compose_indoors.animate_cameras_enabled=False \
     compose_indoors.pose_cameras_enabled=False
```

`animation_route=all` 会从初始层出发，依次访问其他被服务层；它不会自动回到
初始层。显式路线可以使用 index 或 level ID：

```bash
-p "compose_indoors.elevator_animation_route=[3,1,0]"
```

可调动画参数：

| Gin 参数 | 默认值 | 含义 |
|---|---:|---|
| `compose_indoors.elevator_animation_fps` | `24.0` | 状态机采样与 Blender 关键帧 FPS |
| `compose_indoors.elevator_car_speed` | `1.0` | 最大轿厢速度 |
| `compose_indoors.elevator_car_acceleration` | `1.0` | 加/减速度 |
| `compose_indoors.elevator_door_open_time` | `0.8` | 完全开门时间 |
| `compose_indoors.elevator_door_close_time` | `0.8` | 完全关门时间 |
| `compose_indoors.elevator_dwell_time` | `1.5` | 开门驻留时间 |

Blender 状态机会保证：

- 轿厢运动或平层时所有门关闭；
- 只有轿厢对齐的当前层门可以开启；
- 轿门与当前层门开度相同；
- 运动使用梯形或短程三角形加减速曲线。

这些互锁不会自动成为 Isaac 运行时控制器；见第 10 节。

该 `.blend` 的动画 USD 导出也已验收：

```text
/tmp/infinigen_elevator_export_real/blender_animated_nodes.usda
```

其中有 65 个 elevator-named prim、12 个 animated xform，time range
为 `1..543`。这是 Blender 动画 time sample 保留证据，不是 Physics
articulation 或 Isaac 运动证据。已写出的 F1 开门渲染图为：

```text
/tmp/infinigen_elevator_fixed4_animated_final/render/elevator_F1_open_balanced.png
```

原始曝光版仍保留为同目录的 `elevator_F1_open.png`。

## 5. coarse 输出与只读验证

完整 coarse 成功后，`$SCENE` 应至少包含：

```text
scene.blend
MaskTag.json
solve_state.json
elevator_manifest.json
pipeline_coarse.csv
```

随机 vertical-core 路径通常还会写：

```text
vertical_core_manifest.json
```

固定预定义蓝图不保证存在 `vertical_core_manifest.json`；判断电梯能否导出应以
`elevator_manifest.json` 为准。

查看 manifest：

```bash
python -m json.tool "$SCENE/elevator_manifest.json"
```

### 5.1 `.blend` 对 manifest 的验收器

CLI 会只读打开 `.blend`，不会保存它；同时检查层数、标高、井道边界、稳定
对象路径、门板索引、静态/动画曲线和 MaskTag。

状态：`PASS`。最终整楼验收矩阵为：

| 输出 | mode | 结果 |
|---|---|---:|
| `/tmp/infinigen_elevator_fixed_302_aligned/coarse` | static fixed4 | `19/19 PASS` |
| `/tmp/infinigen_elevator_fixed8_seed303/coarse` | static fixed8 | `19/19 PASS` |
| `/tmp/infinigen_elevator_random4_seed302_core8/coarse` | static random4 | `19/19 PASS` |
| `/tmp/infinigen_elevator_fixed4_animated_final/coarse` | animated fixed4 | `20/20 PASS` |

所有报告均为 0 failed、0 global errors。static 检查包含 native landing
opening 从 finished-floor Z 起始，以及 native floor/ceiling mesh 不阻挡
car sweep。animated 多一项完整关键帧/控制曲线验收。

```bash
python -m infinigen.tools.validate_elevator_scene \
  --blend "$SCENE/scene.blend" \
  --manifest "$SCENE/elevator_manifest.json" \
  --masktag-json "$SCENE/MaskTag.json" \
  --mode static \
  --output "$SCENE/elevator_validation.json"
```

动画场景将 `--mode static` 改为 `--mode animated`；不想预设模式时使用默认
`auto`。退出码：

- `0`：全部检查通过；
- `1`：场景成功读取，但一个或多个验收项失败；
- `2`：输入、Blender、manifest 或 JSON fatal error。

## 6. 在 Blender 中查看

仓库内的 `blender/blender` 当前是 Blender 4.2.0，helper 命令存在。完整四层
`.blend` 已生成并被无界面验证器打开；人工 GUI/Timeline 观察本身仍为
`NOT RUN`。

```bash
python -m infinigen.launch_blender "$SCENE/scene.blend"
```

打开后：

1. 在 Outliner 中找到并取消隐藏 `unique_assets:elevators`。
2. 展开 `ElevatorSystem_00`；它是 `elevator_role=system` 的 root。
3. 轿厢稳定相对路径是 `Car`，门板位于 `Car.Door.Panel.Left/Right`。
4. 层门位于 `Shaft.Landings.Landing.<index>_<level>.Door.Panel.Left/Right`。
5. root 的 Custom Properties 应含 `elevator_id`、`elevator_mode`、
   `elevator_stop_z`、`elevator_served_levels_json` 和 `elevator_seed`。
6. 动画场景在 Timeline 从 `elevator_animation_frame_start` 播放到
   `elevator_animation_frame_end`，观察轿厢 Z、轿门 X 和对应层门 X。

对象名可能被 Blender 自动加后缀。自动化工具应优先使用每个节点的
`elevator_node_path`，不要依赖绝对对象名。

## 7. manifest 语义

`elevator_manifest.json` 是 Blender 场景和独立 USD articulation 之间的正式
数据边界。主要字段：

- `schema_version`：当前必须是 `1`；
- `meters_per_unit`：当前是 `1.0`；
- `up_axis`：当前必须是 `Z`；
- `scene_id`、`seed`：生成溯源；
- `elevators[]`：支持一个或多个电梯；
- `origin_xy`、`yaw_degrees`：电梯 root 的实际世界位姿；
- `shaft.inner_size/z_min/z_max`：井道内边界；
- `cabin`、`cabin.door`：独立 USD 的轿厢、门和质量代理；
- `served_floors[]`：`floor_id` 与绝对世界 `stop_z`；
- `lift_drive`、`door_drive`：linear Drive 参数。

Blender root 上的 `elevator_stop_z` 是 root-local，manifest 的 `stop_z` 是世界
绝对 finished-car-floor 标高。场景集成使用
`LevelSpec.elevation + wall_thickness / 2` 与原生 support surface 对齐；root 还
明确记录：

```text
elevator_coordinate_space = root_local
elevator_stop_reference = finished_car_floor
```

不要手工用楼层序号乘名义层高替换 manifest stop。非均匀层、地下层和 root Z
偏移都会使这种推算错误。

## 8. 无 `pxr` 的 USD plan-only

plan-only 会严格验证 manifest，并输出不依赖 OpenUSD 的
`elevator_plan.json`。

状态：`PASS`。

```bash
POST=outputs/elevator_fixed4/elevator_usd
python -m infinigen.tools.build_elevator_usd \
  --manifest "$SCENE/elevator_manifest.json" \
  --output-dir "$POST" \
  --plan-only
```

工具默认拒绝覆盖已有的 tool-owned 输出。需要重建时请选择新目录，或明确加
`--overwrite`。

检查计划：

```bash
python -m json.tool "$POST/elevator_plan.json"
```

单个服务 N 层的电梯应有 `3 + 2N` 个 PrismaticJoint：

- 1 个 `CabinLift`；
- 2 个轿门 joint；
- 每层 2 个 landing-door joint。

因此四层单梯预期 `dof_count=11`。`stop_targets` 是相对最低服务层的 drive
位移，而 manifest 的 `stop_z` 是绝对标高。

## 9. 导出静态建筑并生成独立 articulation USD

### 9.1 导出时排除 Blender 电梯视觉件

必须使用 `--exclude_elevators`，否则静态建筑层会保留一套 Blender 电梯，和
独立 articulation 重叠。

状态：`PASS`。真实四层 Infinigen 建筑已导出到
`/tmp/infinigen_elevator_export_real`。`export_logs.log` 记录
`Excluded 60 elevator-role objects from static export`。当前实现会从打开后的
内存副本删除 role object，然后再烘焙/导出；不再仅依靠会被烘焙
流程重置的 hide 标志，也不会保存覆盖源 `.blend`。

```bash
SCENE=/tmp/infinigen_elevator_fixed4_animated_final/coarse
EXPORT=/tmp/infinigen_elevator_export_real
python -m infinigen.tools.export \
  --input_folder "$SCENE" \
  --output_folder "$EXPORT" \
  --format usda \
  --resolution 1024 \
  --omniverse \
  --exclude_elevators
```

当前 exporter 的预期建筑路径为：

```bash
BUILDING="$EXPORT/export_scene.blend/export_scene.usda"
```

exporter 还会把 `elevator_manifest.json`、`vertical_core_manifest.json`（若存在）
和 `solve_state.json` 复制到 `$EXPORT` 根目录。

### 9.2 临时 OpenUSD 25.5.1 环境

不要为了 plan-only 修改主 conda。需要实际写 USD 时，可以把精确版本安装到
独立临时目录。

状态：`PASS`。

```bash
PXR_DIR=/tmp/infinigen_usd_core_25_5_1
python -m pip install --target "$PXR_DIR" 'usd-core==25.5.1'
PYTHONPATH="$PXR_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python -c 'from pxr import Usd; print(Usd.GetVersion())'
```

预期版本为 `(0, 25, 5)`。如果 `$PXR_DIR` 已有其他内容，使用新的空目录，
不要把不同 OpenUSD 版本混装。

运行 pxr schema/compliance 测试：

```bash
PYTHONPATH="$PXR_DIR${PYTHONPATH:+:$PYTHONPATH}" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest -q tests/sim/test_elevator_usd_pxr.py
```

状态：`PASS`。最终 OpenUSD/`pxr` 批次为 `14 passed`，覆盖真实
schema、author、runtime target、copy/in-place 和独立 articulation
compliance。完整 wrapper 还包含 base 建筑材质，其 ComplianceChecker 会受
当前 OpenUSD 材质检查环境影响；不应把独立 articulation 的 0/0
误写成完整 wrapper 的 0/0。

### 9.3 写 articulation 和组合 wrapper

CLI 已用真实导出的四层 Infinigen `$BUILDING` 跑通。最终证据目录为
`/tmp/infinigen_elevator_export_real/articulation`。

```bash
PYTHONPATH="$PXR_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python -m infinigen.tools.build_elevator_usd \
    --manifest "$SCENE/elevator_manifest.json" \
    --building-usd "$BUILDING" \
    --output-dir "$POST" \
    --elevator-format usda
```

固定输出：

```text
$POST/elevator_plan.json
$POST/elevator_articulation.usda
$POST/scene_with_elevators.usda
```

如果选择 `--elevator-format usdc`，第二个文件改为
`elevator_articulation.usdc`；wrapper 始终是文本 `.usda`，并用相对 subLayer
路径组合静态建筑和电梯。

快速检查 composition 中的 articulation root：

```bash
PYTHONPATH="$PXR_DIR${PYTHONPATH:+:$PYTHONPATH}" python - <<PY
from pxr import Usd, UsdPhysics

stage = Usd.Stage.Open("$POST/scene_with_elevators.usda")
assert stage is not None
roots = [
    str(prim.GetPath())
    for prim in stage.Traverse()
    if prim.HasAPI(UsdPhysics.ArticulationRootAPI)
]
print(roots)
PY
```

单梯预期：

```text
['/World/ElevatorSystems/elevator_0']
```

真实输出的结构计数为：

```text
1 ArticulationRoot
12 rigid links
11 PhysicsPrismaticJoint DOF
1 PhysicsFixedJoint
11 linear drives
```

`elevator_articulation.usda` 的 ComplianceChecker 为 0 errors/0 failed
checks。`scene_with_elevators.usda` 同时 sublayer 真实建筑与电梯层，
已由 `pxr` 打开并看到上述 articulation；由于 base 材质检查的环境
影响，不声称完整 wrapper 的 ComplianceChecker 为 0/0。

## 10. Isaac Sim 导入与控制

本节必须拆成两种状态：OpenUSD/`pxr` 离线 target authoring 为 `PASS`；Isaac
Sim GUI、Timeline、Play 和 PhysX 闭环运动均为 `NOT RUN`。当前代码已经生成
标准 OpenUSD Physics schema，但不能把离线属性写入描述成“电梯在 Isaac 中已
运动”。

### 10.1 GUI 导入步骤

1. 使用目标 Isaac Sim 版本启动 GUI。
2. 通过 `File > Open` 打开 `$POST/scene_with_elevators.usda`，不要只打开静态
   `export_scene.usdc`。
3. 在 Stage 中确认 `/World/ElevatorSystems/elevator_0` 带
   `ArticulationRootAPI`。
4. 确认 `/World/ElevatorSystems/elevator_0/Joints/CabinLift` 是 Z 轴
   PrismaticJoint，门 joint 是 X 轴 PrismaticJoint，Drive instance 名为
   `linear`。
5. 确认场景存在可运行的 PhysicsScene；若静态建筑没有提供，需要在 Isaac 中
   新建。
6. 点击 Play 后再写 drive target，并观察轿厢、轿门和层门的实际 joint
   position/velocity。

### 10.2 目标值

不要把绝对 `stop_z` 直接写入 `CabinLift`。从
`$POST/elevator_plan.json` 读取：

```text
elevators[i].stop_targets
elevators[i].joints[j].targets
```

`CabinLift` target 是相对最低服务层的 Z 位移。门 target 中 `closed` 为 0，
左右门的 `open` 分别为负/正 travel。

以下 Isaac Script Editor 片段与当前 USD 路径/schema 对应，但尚未在 Isaac 中
执行，状态为 `NOT RUN`：

```python
import omni.usd
from pxr import UsdPhysics

stage = omni.usd.get_context().get_stage()
joint = stage.GetPrimAtPath(
    "/World/ElevatorSystems/elevator_0/Joints/CabinLift"
)
drive = UsdPhysics.DriveAPI.Get(joint, "linear")
drive.GetTargetPositionAttr().Set(8.0)  # 必须替换为 elevator_plan.json 中的值
```

Isaac 版本之间的 articulation controller API 可能变化；在确认目标 Isaac
版本前，不要把上面的 USD 属性写法当作最终运行时控制器。

### 10.3 已验证的离线互锁 target CLI

`control_elevator_usd.py` 先用 manifest 重建 canonical plan，并可用 `--plan`
验证现有 JSON 完全一致。dry-run 不导入 `pxr`：

```bash
python -m infinigen.tools.control_elevator_usd \
  --manifest "$SCENE/elevator_manifest.json" \
  --plan "$POST/elevator_plan.json" \
  --elevator elevator_0 --floor F3 \
  --door-state closed --dry-run
```

离线输出副本需要 OpenUSD 环境。开门时 `--car-position` 是相对最低服务站的
实测 `CabinLift` joint position，不是绝对 manifest `stop_z`；缺失或未对层会以
interlock error 拒绝：

```bash
PYTHONPATH="$PXR_DIR${PYTHONPATH:+:$PYTHONPATH}" \
python -m infinigen.tools.control_elevator_usd \
  --manifest "$SCENE/elevator_manifest.json" \
  --plan "$POST/elevator_plan.json" \
  --usd "$POST/scene_with_elevators.usda" \
  --elevator elevator_0 --floor F2 \
  --door-state open --car-position 6.335131852675996 \
  --output "$POST/scene_F2_open.usda"
```

写入模式必须显式选择 `--output NEW.usd` 或 `--in-place`；默认不存在隐式覆盖。
`--output` 使用 session override 后导出 flatten 副本，不修改输入 layer；
`--in-place` 才保存输入。真实四层 11-DOF stage 的 dry-run、输出副本和 scratch
in-place 均已通过。真实 wrapper 的 F2 输出为
`/tmp/infinigen_elevator_export_real/articulation/scene_F2_open.usda`；`pxr` 重开后，
门的非零开门 target 只属于两扇轿门和两扇 F2 层门，F0/F1/F3 层门
均为 0。独立 articulation 合规检查为 0/0；不把该结果扩大为包含 base
材质的完整 wrapper ComplianceChecker 0/0。

这仍只是 drive target authoring。离线测试中的 `car-position` 是已知对层测试值，
不是 Isaac 实测反馈，因此不能证明轿厢真的移动或停稳。

### 10.4 Isaac 闭环仍必须实现的步骤

USD articulation 不会自动执行 Blender 状态机。现有 runtime 层保证每张命令
快照覆盖全部 DOF，并强制“移动目标全门关、开门目标只开当前层”；Isaac 闭环
仍至少应按以下顺序：

1. 将轿门和所有层门 target 设为 `closed`。
2. 等待所有门实际位置进入关闭容差，并确认门速度接近 0。
3. 设置 `CabinLift` 的目标楼层 target。
4. 等待轿厢位置进入平层容差、速度接近 0。
5. 只打开轿门和当前对齐层的两扇 landing door。
6. 驻留后关门；确认关闭后才允许下一次运行。
7. 超时、位置偏差、门未关或 joint fault 时停止轿厢并进入故障状态。

在该控制器和真实 Isaac 验收完成前，不应把系统描述为“Isaac 中已安全可用”。

## 11. 测试命令

证据快照和每一项“不证明什么”见 `docs/ELEVATOR_TEST_REPORT.md`。最终
固定记录为：

```text
main focused:              88 passed, 2 skipped
OpenUSD/pxr:               14 passed
broad constraints/export: 120 passed, 1 skipped
fixed4 static:             19/19 PASS
fixed8 static:             19/19 PASS
random4 static core8:      19/19 PASS
fixed4 animated:           20/20 PASS
```

OpenUSD 批次使用第 9.2 节的隔离 25.5.1 环境。skip 不计为 PASS；
不要用旧聚焦批次数字或旧 random4 `KeyError` 替代这个最终矩阵。

默认禁用 canonical A/B 的可复现命令：

```bash
python scripts/compare_indoor_outputs.py \
  /tmp/infinigen_ab_baseline_single_repeat/coarse \
  /tmp/infinigen_ab_candidate_single_final/coarse
```

实际结果为 2 个 JSON 同名匹配、0 缺失、0 多余，`MaskTag.json` 和
`solve_state.json` 都为 `SAME`，数值最大差为 0，`FINAL: PASS`。

本机 ROS 的 `launch_testing` pytest 自动插件可能因缺少 `lark` 导致 pytest
在收集前失败。`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 用于隔离该外部插件；由此产生
的 `Unknown config option: timeout` warning 不属于电梯失败。

## 12. 故障排查

### `No module named bpy`

未进入 Infinigen conda，或使用了系统 Python。重新执行第 2.1 节。对于
standalone Blender 安装也可使用 `python -m infinigen.launch_blender -m ... --`。

### Blender 版本 assertion

当前生成流程只接受 Blender `4.2.0`。不要用系统中的其他 Blender 打开并重新
保存后再继续自动流水线。

### 没有 `elevator_manifest.json`

检查：

- 是否加载了 `elevator.gin`、`four_story_elevator.gin` 或 fixed/animated 派生配置；
- `RoomConstants.elevator_enabled` 是否为 `True`；
- `n_stories` 是否大于 1；
- 日志是否已经进入 `room_elevator_structure`；
- 生成是否仍卡在此前的求解或原生楼梯阶段。

启用的移动电梯要求至少两个服务站。`RoomConstants` 已在配置阶段检查服务层
数量、排序、唯一性和索引范围；单站配置会在房间求解前直接报错。

### 固定四层在 `room_stairs` 很慢

旧固定蓝图的楼梯房过小，现已扩大到 8 m × 8 m。若进程在更新前已启动，它
不会自动采用新蓝图，应停止后用同一 seed/config 重新运行。原生楼梯仍可能是
耗时阶段。仅为定位电梯问题时，可临时覆盖
`compose_indoors.room_stairs_enabled=False`，但该命令状态为
`NOT RUN`，且会改变最终场景内容，不能作为正式四层验收结果。

### `Unable to place vertical core` 或 `No grid candidates`

随机楼层没有足够的公共 XY 区域。依次尝试：

- `RoomConstants.fixed_contour=True`；
- 减少 `n_elevators`；
- 减小 shaft、lobby depth 或 core clearance；
- 增大建筑轮廓。

不要把 `n_elevators=2` 传给固定四层 blueprint；它明确只支持一个井道。

### `adjacent stops are too close`

自定义 `building_levels` 的相邻 elevation 无法容纳轿厢/门。增大标高差，或在
确认物理净空后调整轿厢和门尺寸。不要绕过该验证。

### 初始层或 animation route 不被服务

`elevator_initial_level` 和 route 的每个元素都必须属于
`elevator_served_levels`。index 会被转换为 level ID；字符串必须与自定义
`level_id` 完全一致。express 配置无需包含建筑的最低或最高物理层；井道 core
和精确 shaft boolean 仍贯穿所有楼层，资产 pit/overhead 会把 shaft bounds 扩展
到建筑底/顶。至少需要两个有效服务站。

### 场景验证器报告 MaskTag 缺失

验证原始 coarse `scene.blend`，并传入同目录的 `MaskTag.json`。不要拿
`--exclude_elevators` 后的静态 USD 运行 Blender 场景验证器。

### 场景里有两套电梯

静态建筑导出时漏了 `--exclude_elevators`。重新导出静态建筑，再与独立
articulation wrapper 组合。

### `pxr` 缺失

- 只检查 manifest/plan：使用 `--plan-only`；
- 写 USD：使用第 9.2 节的隔离 OpenUSD 目录，或从 Isaac 自带 Python 执行；
- 不建议仅为 plan-only 污染主 Infinigen conda。

### 工具拒绝覆盖输出

这是预期的非破坏性行为。使用新 `--output-dir`；只有确认目录内是该工具旧
输出时才加 `--overwrite`。

### articulation 已导入但不运动

依次检查：

- Isaac 是否处于 Play；
- 是否打开 `scene_with_elevators.usda`；
- stage 是否有 PhysicsScene；
- joint drive instance 是否是 `linear`；
- target 是否来自 `elevator_plan.json` 的相对 target；
- 是否只修改了 Blender 动画，而没有修改 USD drive target。

### 轿厢穿透、跌落或不稳定

该情况必须作为 Isaac 验收失败处理。检查单位、PhysicsScene、RootFixed、碰撞
代理、重复静态电梯、质量和 drive gains。当前 Isaac 运行时尚未验证，不应通过
调大 stiffness 掩盖错误的 joint、单位或碰撞设置。

## 13. 最小验收清单

在宣称一个四层场景“可运动电梯可用”前，至少需要：

1. coarse 命令退出码为 0，并写出 `scene.blend`、`MaskTag.json` 和 manifest。
2. `validate_elevator_scene` 对正确 mode 返回 0。
3. manifest 有 4 个严格递增的实际 stop，并与 Blender landing 世界 Z 一致。
4. plan-only 得到单梯 11 DOF。
5. 静态建筑通过 `--exclude_elevators` 导出，没有重复电梯视觉件。
6. OpenUSD wrapper 可打开；独立 articulation 的 ComplianceChecker 为
   0 errors/0 failed checks，所有 PrismaticJoint 只有 linear Drive。
7. Isaac 中实际完成至少一次底层到顶层再返回的运动测试。
8. 运动全过程门关闭；只在平层后联动开启当前轿门和层门。
9. 故障、超时和非法开门请求能停止系统并留下可诊断状态。

固定四层/8 层 static、随机四层 static 和固定四层 animated 已满足各自
适用的第 1 至 4 项。真实 Infinigen 静态建筑已以删除内存副本中电梯
对象的方式导出，并与 articulation 组合，因此第 5 项和第 6 项的
wrapper-open/独立-articulation 部分为 `PASS`。由于 base 材质检查受当前
OpenUSD 环境影响，不声称完整 wrapper ComplianceChecker 0/0。第 7 至
9 项属于 Isaac GUI/timeline/PhysX 闭环，全部为 `NOT RUN`；完整普通
家具高内容场景也仍为 `NOT RUN`。
